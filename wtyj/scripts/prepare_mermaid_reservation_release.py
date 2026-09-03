#!/usr/bin/env python3
"""Prepare or apply a credential-preserving Mermaid-only release snapshot.

Never emits configuration contents or secrets. Preparation does not mutate live
files. Apply requires byte-identical originals and uses the canonical config lock.
The caller owns container recreation, health checks, activation and rollback.
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

from sync_mermaid_config_fields import _canonical_client_json_lock


LIVE = Path("/root/clients/mermaid")
FILES = {"client.json": LIVE / "config/client.json", "platform.env": LIVE / "config/platform.env", "docker-compose.yml": LIVE / "docker-compose.yml"}


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
    updated = copy.deepcopy(live)
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


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--release", type=Path, required=True)
    parser.add_argument("--image", required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if not re.fullmatch(r"wtyj-agent:mermaid-reservations-[a-f0-9]{7,40}", args.image):
        raise ValueError("Expected a Mermaid-only revision image tag")
    release = args.release
    if not release.is_absolute() or not str(release).startswith("/root/backups/mermaid-reservations/"):
        raise ValueError("Protected Mermaid release directory required")
    if args.apply:
        manifest = json.loads((release / "manifest.json").read_text())
        with _canonical_client_json_lock(FILES["client.json"]):
            for name, live_path in FILES.items():
                if live_path.is_symlink() or hashlib.sha256(live_path.read_bytes()).hexdigest() != manifest["original_hashes"][name]:
                    raise RuntimeError(f"Live {name} changed after preparation")
            for name, live_path in FILES.items():
                private_write(live_path, (release / "staged" / name).read_bytes())
            private_write(LIVE / "config/reservation_catalog.json", (release / "staged/reservation_catalog.json").read_bytes())
        print(json.dumps({"applied": True, "image": args.image, "backup": str(release)}))
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
    compose = originals["docker-compose.yml"].decode()
    if "container_name: wtyj-mermaid" not in compose:
        raise ValueError("Unexpected compose target")
    compose, count = re.subn(r"(?m)^(\s*image:)\s*[^\n]+", rf"\1 {args.image}", compose)
    if count != 1:
        raise ValueError("Expected exactly one Mermaid image")
    private_write(release / "staged/docker-compose.yml", compose.encode())
    private_write(release / "staged/reservation_catalog.json", (args.source / "clients/mermaid/config/reservation_catalog.json").read_bytes())
    db = LIVE / "data/state_registry.db"
    if db.is_file():
        with sqlite3.connect(f"file:{db}?mode=ro", uri=True) as src, sqlite3.connect(release / "original/state_registry.db") as dst:
            src.backup(dst)
        (release / "original/state_registry.db").chmod(0o600)
    image = subprocess.check_output(["docker", "inspect", "wtyj-mermaid", "--format", "{{.Image}} {{.Config.Image}}"], text=True).strip()
    containers = subprocess.check_output(["docker", "ps", "--format", "{{.Names}} {{.Image}} {{.ID}}"], text=True)
    manifest = {"original_hashes": {key: hashlib.sha256(value).hexdigest() for key, value in originals.items()}, "previous_image": image, "candidate_image": args.image, "containers_before": containers}
    private_write(release / "manifest.json", json.dumps(manifest, indent=2).encode())
    print(json.dumps({"prepared": True, "backup": str(release), "provider_binding_preserved": True, "live_files_changed": False}))


if __name__ == "__main__":
    main()
