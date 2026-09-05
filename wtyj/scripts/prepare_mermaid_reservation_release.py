#!/usr/bin/env python3
"""Prepare, apply, or roll back a credential-preserving Mermaid release.

Never emits configuration contents or secrets. Preparation does not mutate live
files. Apply and rollback require exact manifest hashes and use the canonical
config lock. The scoped shell wrapper owns container recreation and health gates.
"""

import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import sqlite3
import subprocess
import tempfile

from sync_mermaid_config_fields import _canonical_client_json_lock, merge_reviewed_fields


LIVE = Path(os.environ.get("WTYJ_MERMAID_LIVE_DIR", "/root/clients/mermaid"))
BACKUP_ROOT = Path(os.environ.get(
    "WTYJ_MERMAID_BACKUP_ROOT", "/root/backups/mermaid-reservations"
))
FILES = {
    "client.json": LIVE / "config/client.json",
    "platform.env": LIVE / "config/platform.env",
    "docker-compose.yml": LIVE / "docker-compose.yml",
    "reservation_catalog.json": LIVE / "config/reservation_catalog.json",
    "response_policy.json": LIVE / "config/response_policy.json",
}


def private_write(path: Path, payload: bytes):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=".mermaid-release-")
    try:
        with os.fdopen(fd, "wb") as stream:
            os.fchmod(stream.fileno(), 0o600)
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def merged_config(live: dict, source: dict) -> dict:
    if live.get("slug") != "mermaid" or source.get("slug") != "mermaid":
        raise ValueError("Mermaid identity required")
    allowlist = live.get("channel_account_allowlist") or {}
    if allowlist.get("mode") != "strict" or len(allowlist.get("zernio_accounts") or []) != 1:
        raise ValueError("Expected one strict Mermaid provider account")
    updated, _ = merge_reviewed_fields(source, live)
    updated["workflow"] = copy.deepcopy(source["workflow"])
    for key, value in source["features"].items():
        if key.startswith("mermaid_"):
            updated.setdefault("features", {})[key] = value
    updated["features"]["mermaid_reminders"] = False
    for key in ("languages", "operating_mode"):
        updated.setdefault("business", {})[key] = copy.deepcopy(source["business"][key])
    updated.setdefault("agent_persona", {})["reservation_demo_override"] = source["agent_persona"]["reservation_demo_override"]
    updated.setdefault("payment", {})["policy"] = source["payment"]["policy"]
    if updated["channel_account_allowlist"] != live["channel_account_allowlist"]:
        raise ValueError("Provider binding changed")
    return updated


def prepared_env(original: str) -> str:
    existing = dict(line.split("=", 1) for line in original.splitlines() if "=" in line and not line.lstrip().startswith("#"))
    replacements = {
        "UNBOKS_PUBLIC_BASE_URL": "https://api.unboks.org/api/mermaid",
        "MERMAID_DEMO_SIGNING_SECRET": existing.get("MERMAID_DEMO_SIGNING_SECRET", "").strip() or secrets.token_urlsafe(48),
        "MERMAID_DOCUMENT_ROOT": "/app/data/mermaid-documents",
        "TENANT_ID": "mermaid", "TENANT_SLUG": "mermaid",
        "TENANT_ACCOUNT_ALLOWLIST_REQUIRED": "true", "TENANT_RUNTIME_CONTROLS_REQUIRED": "true",
    }
    lines = [line for line in original.splitlines() if line.split("=", 1)[0] not in replacements]
    lines.extend(f"{key}={value}" for key, value in replacements.items())
    return "\n".join(lines) + "\n"


def _digest(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _compose_with_image(payload: bytes, image: str) -> bytes:
    """Return one Compose file with only its application image pinned."""
    compose = payload.decode()
    if "container_name: wtyj-mermaid" not in compose:
        raise ValueError("Unexpected compose target")
    compose, count = re.subn(
        r"(?m)^(\s*image:)\s*[^\n]+", rf"\1 {image}", compose
    )
    if count != 1:
        raise ValueError("Expected exactly one Mermaid image")
    return compose.encode()


def _rollback_image_tag(image_id: str) -> str:
    """Name the protected local tag from the exact Docker image identity."""
    match = re.fullmatch(r"sha256:([a-f0-9]{64})", str(image_id or ""))
    if not match:
        raise RuntimeError("Running Mermaid image did not have a full immutable ID")
    return f"wtyj-agent:tracy-rollback-{match.group(1)[:20]}"


def _ensure_rollback_image(image_id: str, rollback_image: str) -> None:
    """Point the deterministic rollback tag at, and verify, the exact image."""
    if rollback_image != _rollback_image_tag(image_id):
        raise RuntimeError("Release rollback image does not match its immutable ID")
    subprocess.check_output(
        ["docker", "tag", image_id, rollback_image],
        text=True,
        stderr=subprocess.DEVNULL,
    )
    resolved = subprocess.check_output(
        ["docker", "image", "inspect", "--format", "{{.Id}}", rollback_image],
        text=True,
        stderr=subprocess.DEVNULL,
    ).strip()
    if resolved != image_id:
        raise RuntimeError("Rollback tag did not resolve to the previous Mermaid image")


def _verified_release_payloads(
    directory: Path,
    expected_hashes: dict[str, str],
) -> dict[str, bytes]:
    """Read each protected payload once and authenticate it before use."""
    if set(expected_hashes) != set(FILES):
        raise RuntimeError("Release manifest protected-file set changed")
    payloads = {}
    for name in FILES:
        path = directory / name
        if path.is_symlink() or not path.is_file():
            raise RuntimeError(f"Release {name} must be a regular file")
        payload = path.read_bytes()
        if _digest(payload) != expected_hashes[name]:
            raise RuntimeError(f"Release {name} differs from prepared manifest")
        payloads[name] = payload
    return payloads


def _require_mermaid_stopped_or_absent(*, allow_absent: bool) -> None:
    """Fail closed unless Docker proves Mermaid is stopped or absent."""
    try:
        running = subprocess.check_output(
            ["docker", "inspect", "wtyj-mermaid", "--format", "{{.State.Running}}"],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except subprocess.CalledProcessError:
        container_names = subprocess.check_output(
            ["docker", "ps", "-a", "--format", "{{.Names}}"],
            text=True,
            stderr=subprocess.DEVNULL,
        ).split()
        if "wtyj-mermaid" in container_names:
            raise RuntimeError("Mermaid container exists but could not be inspected")
        if not allow_absent:
            raise RuntimeError("Mermaid container is absent before release apply")
        return
    if running != "false":
        raise RuntimeError("Stop only Mermaid before changing the release")


def _database_backup(release: Path) -> None:
    """Create a transactionally consistent DB backup after Mermaid is stopped."""
    source = LIVE / "data/state_registry.db"
    target = release / "original/state_registry.db"
    if source.is_symlink() or not source.is_file():
        raise RuntimeError("Mermaid state database must be a regular file")
    if target.exists():
        raise RuntimeError("Mermaid database backup already exists")
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    previous_umask = os.umask(0o077)
    try:
        with sqlite3.connect(f"file:{source}?mode=ro", uri=True) as src:
            with sqlite3.connect(target) as dst:
                src.backup(dst)
    finally:
        os.umask(previous_umask)
    target.chmod(0o600)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--release", type=Path, required=True)
    parser.add_argument("--image", required=True)
    operation = parser.add_mutually_exclusive_group()
    operation.add_argument("--apply", action="store_true")
    operation.add_argument("--rollback", action="store_true")
    parser.add_argument("--service-stopped", action="store_true")
    args = parser.parse_args()
    if not re.fullmatch(
        r"wtyj-agent:(?:mermaid|tracy)-[a-z0-9][a-z0-9._-]*-[a-f0-9]{7,40}",
        args.image,
    ):
        raise ValueError("Expected an immutable Mermaid/Tracy revision image tag")
    release = args.release
    try:
        protected_relative = release.resolve(strict=False).relative_to(
            BACKUP_ROOT.resolve(strict=False)
        )
    except ValueError:
        protected_relative = None
    if (
        not release.is_absolute()
        or protected_relative is None
        or protected_relative == Path(".")
    ):
        raise ValueError("Protected Mermaid release directory required")
    if args.apply or args.rollback:
        if not args.service_stopped:
            raise RuntimeError("Stop only Mermaid and pause config writers before changing the release")
        _require_mermaid_stopped_or_absent(allow_absent=args.rollback)
        manifest_path = release / "manifest.json"
        if manifest_path.is_symlink() or not manifest_path.is_file():
            raise RuntimeError("Release manifest must be a regular file")
        manifest = json.loads(manifest_path.read_text())
        if manifest["candidate_image"] != args.image:
            raise RuntimeError("Release image does not match prepared manifest")
        previous_image_id = str(manifest.get("previous_image_id") or "")
        rollback_image = str(manifest.get("rollback_image") or "")
        _ensure_rollback_image(previous_image_id, rollback_image)
        with _canonical_client_json_lock(FILES["client.json"]):
            original_payloads = _verified_release_payloads(
                release / "original", manifest["original_hashes"]
            )
            staged_payloads = _verified_release_payloads(
                release / "staged", manifest["staged_hashes"]
            )
            rollback_payloads = _verified_release_payloads(
                release / "rollback", manifest["rollback_hashes"]
            )
            source_payloads = rollback_payloads if args.rollback else staged_payloads
            current_hashes = {}
            for name, live_path in FILES.items():
                if live_path.is_symlink():
                    raise RuntimeError(f"Live {name} became a symlink")
                current_hashes[name] = _digest(live_path.read_bytes())
            if args.rollback and current_hashes == manifest["rollback_hashes"]:
                print(json.dumps({
                    "rolled_back": False,
                    "already_rollback": True,
                    "image": args.image,
                    "rollback_image": rollback_image,
                    "previous_image_id": previous_image_id,
                    "backup": str(release),
                }))
                return
            allowed_hashes = (
                (manifest["staged_hashes"], manifest["original_hashes"])
                if args.rollback
                else (manifest["original_hashes"],)
            )
            if not any(current_hashes == expected for expected in allowed_hashes):
                raise RuntimeError("Live protected files changed after preparation")
            if args.apply:
                _database_backup(release)
            try:
                for name, live_path in FILES.items():
                    private_write(live_path, source_payloads[name])
            except BaseException:
                # A failed multi-file apply must not leave Mermaid pointed at a
                # half-staged release. Restore every protected original while
                # the service and canonical writer lock are still held.
                if args.apply:
                    for name, live_path in FILES.items():
                        private_write(live_path, original_payloads[name])
                raise
        result = {
            "rolled_back" if args.rollback else "applied": True,
            "image": args.image,
            "rollback_image": rollback_image,
            "previous_image_id": previous_image_id,
            "backup": str(release),
        }
        print(json.dumps(result))
        return
    release.mkdir(parents=True, exist_ok=False, mode=0o700)
    originals = {}
    for name, live_path in FILES.items():
        if live_path.is_symlink() or not live_path.is_file():
            raise ValueError(f"Live {name} must be a regular file")
        originals[name] = live_path.read_bytes()
        private_write(release / "original" / name, originals[name])
    live_config = json.loads(originals["client.json"])
    source = json.loads((args.source / "clients/mermaid/config/client.json").read_text())
    updated = merged_config(live_config, source)
    private_write(release / "staged/client.json", (json.dumps(updated, indent=2, ensure_ascii=False) + "\n").encode())
    private_write(release / "staged/platform.env", prepared_env(originals["platform.env"].decode()).encode())
    private_write(
        release / "staged/docker-compose.yml",
        _compose_with_image(originals["docker-compose.yml"], args.image),
    )
    private_write(
        release / "staged/reservation_catalog.json",
        (args.source / "clients/mermaid/config/reservation_catalog.json").read_bytes(),
    )
    private_write(
        release / "staged/response_policy.json",
        (args.source / "clients/mermaid/config/response_policy.json").read_bytes(),
    )
    image = subprocess.check_output(["docker", "inspect", "wtyj-mermaid", "--format", "{{.Image}} {{.Config.Image}}"], text=True).strip()
    image_parts = image.split()
    if len(image_parts) != 2:
        raise RuntimeError("Could not read the running Mermaid image identity")
    previous_image_id, previous_image_reference = image_parts
    rollback_image = _rollback_image_tag(previous_image_id)
    _ensure_rollback_image(previous_image_id, rollback_image)
    rollback = dict(originals)
    rollback["docker-compose.yml"] = _compose_with_image(
        originals["docker-compose.yml"], rollback_image
    )
    for name, payload in rollback.items():
        private_write(release / "rollback" / name, payload)
    containers = subprocess.check_output(["docker", "ps", "--format", "{{.Names}} {{.Image}} {{.ID}}"], text=True)
    staged = {
        name: (release / "staged" / name).read_bytes()
        for name in FILES
    }
    manifest = {
        "original_hashes": {key: _digest(value) for key, value in originals.items()},
        "staged_hashes": {key: _digest(value) for key, value in staged.items()},
        "rollback_hashes": {key: _digest(value) for key, value in rollback.items()},
        "previous_image": image,
        "previous_image_id": previous_image_id,
        "previous_image_reference": previous_image_reference,
        "rollback_image": rollback_image,
        "candidate_image": args.image,
        "containers_before": containers,
    }
    private_write(release / "manifest.json", json.dumps(manifest, indent=2).encode())
    print(json.dumps({"prepared": True, "backup": str(release), "provider_binding_preserved": True, "live_files_changed": False}))


if __name__ == "__main__":
    main()
