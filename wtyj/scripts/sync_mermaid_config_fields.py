#!/usr/bin/env python3
"""Synchronize reviewed Mermaid knowledge fields without replacing live state.

The live client.json contains generated credentials and provider-binding state
that must never be sourced from Git or printed. This tool copies only the two
reviewed content fields listed in SYNC_PATHS from the tracked template into an
existing Mermaid client.json. It defaults to a read-only dry run.
"""

from __future__ import annotations

import argparse
import copy
import fcntl
import json
import os
import stat
import tempfile
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SOURCE = REPOSITORY_ROOT / "clients" / "mermaid" / "config" / "client.json"
SYNC_PATHS = (
    ("agent_persona", "freeform_notes"),
    ("faq", "gluten_free"),
)


def _load_object_bytes(raw: bytes, label: str) -> dict[str, Any]:
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} is not valid UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label} must contain a JSON object")
    return value


def _get_path(document: dict[str, Any], path: tuple[str, ...]) -> Any:
    current: Any = document
    for part in path:
        if not isinstance(current, dict) or part not in current:
            raise ValueError(f"missing required source field {'.'.join(path)}")
        current = current[part]
    return current


def _set_path(document: dict[str, Any], path: tuple[str, ...], value: Any) -> None:
    current: Any = document
    for part in path[:-1]:
        child = current.get(part) if isinstance(current, dict) else None
        if not isinstance(child, dict):
            raise ValueError(f"target parent field {'.'.join(path[:-1])} is not an object")
        current = child
    current[path[-1]] = copy.deepcopy(value)


def merge_reviewed_fields(
    source: dict[str, Any],
    target: dict[str, Any],
) -> tuple[dict[str, Any], list[str]]:
    if source.get("slug") != "mermaid" or target.get("slug") != "mermaid":
        raise ValueError("source and target must both be the Mermaid tenant")
    updated = copy.deepcopy(target)
    changed: list[str] = []
    for path in SYNC_PATHS:
        source_value = _get_path(source, path)
        if not isinstance(source_value, str) or not source_value.strip():
            raise ValueError(f"source field {'.'.join(path)} must be a non-empty string")
        try:
            target_value = _get_path(target, path)
        except ValueError:
            target_value = None
        if target_value != source_value:
            _set_path(updated, path, source_value)
            changed.append(".".join(path))
    return updated, changed


def _fsync_directory(directory: Path) -> None:
    descriptor = os.open(directory, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _no_follow_flag(label: str) -> int:
    no_follow = getattr(os, "O_NOFOLLOW", None)
    if no_follow is None:
        raise ValueError(f"safe no-follow {label} access is unavailable")
    return no_follow


def _read_regular_file_no_follow(
    path: Path,
    *,
    label: str,
) -> tuple[bytes, os.stat_result]:
    """Read one regular file without following its final path component."""
    flags = os.O_RDONLY | _no_follow_flag(label)
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    if hasattr(os, "O_NONBLOCK"):
        flags |= os.O_NONBLOCK
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise ValueError(f"{label} must be a regular file, not a symlink") from exc
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise ValueError(f"{label} must be a regular file, not a symlink")
        with os.fdopen(descriptor, "rb") as stream:
            descriptor = -1
            return stream.read(), metadata
    finally:
        if descriptor >= 0:
            os.close(descriptor)


@contextmanager
def _canonical_client_json_lock(target_path: Path):
    """Use the exact sidecar lock shared by runtime and Nr3 config writers."""
    lock_path = target_path.with_suffix(target_path.suffix + ".lock")
    flags = os.O_RDWR | os.O_CREAT | _no_follow_flag("client.json lock")
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    try:
        descriptor = os.open(lock_path, flags, 0o600)
    except OSError as exc:
        raise ValueError("client.json lock must be a regular file, not a symlink") from exc
    locked = False
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise ValueError("client.json lock must be a regular file, not a symlink")
        os.fchmod(descriptor, 0o600)
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        locked = True
        yield
    finally:
        if locked:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


def _assert_target_unchanged(
    target_path: Path,
    expected_stat: os.stat_result,
    expected_bytes: bytes,
) -> None:
    """Safely reject non-cooperating replacement or in-place target edits."""
    try:
        current, current_stat = _read_regular_file_no_follow(
            target_path,
            label="target",
        )
    except ValueError as exc:
        raise RuntimeError("target changed during sync; refusing replacement") from exc
    if (
        current_stat.st_dev != expected_stat.st_dev
        or current_stat.st_ino != expected_stat.st_ino
        or current != expected_bytes
    ):
        raise RuntimeError("target changed during sync; refusing replacement")


def _write_backup(backup_dir: Path, original: bytes) -> Path:
    if not backup_dir.is_absolute():
        raise ValueError("backup directory must be an absolute path outside the repository")
    backup_dir = backup_dir.resolve()
    repository = REPOSITORY_ROOT.resolve()
    if backup_dir == repository or repository in backup_dir.parents:
        raise ValueError("backup directory must be outside the repository")
    backup_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    if backup_dir.is_symlink() or not backup_dir.is_dir():
        raise ValueError("backup directory must be a real directory")
    backup_dir.chmod(0o700)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    backup_path = backup_dir / f"client.json.before-content-sync-{stamp}"
    descriptor = os.open(
        backup_path,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL,
        0o600,
    )
    try:
        with os.fdopen(descriptor, "wb") as stream:
            os.fchmod(stream.fileno(), 0o600)
            stream.write(original)
            stream.flush()
            os.fsync(stream.fileno())
    except BaseException:
        backup_path.unlink(missing_ok=True)
        raise
    _fsync_directory(backup_dir)
    return backup_path


def sync(
    source_path: Path,
    target_path: Path,
    backup_dir: Path,
    *,
    apply: bool,
) -> tuple[list[str], Path | None]:
    if os.path.abspath(source_path) == os.path.abspath(target_path):
        raise ValueError("source and target must be different files")
    source_bytes, source_stat = _read_regular_file_no_follow(
        source_path,
        label="source",
    )
    source = _load_object_bytes(source_bytes, "source")

    def synchronize_snapshot() -> tuple[list[str], Path | None]:
        target_bytes, target_stat = _read_regular_file_no_follow(
            target_path,
            label="target",
        )
        if (
            source_stat.st_dev == target_stat.st_dev
            and source_stat.st_ino == target_stat.st_ino
        ):
            raise ValueError("source and target must be different files")
        if stat.S_IMODE(target_stat.st_mode) != 0o600:
            raise ValueError("target client.json must have mode 0600 before sync")
        target = _load_object_bytes(target_bytes, "target")
        updated, changed = merge_reviewed_fields(source, target)
        if not apply or not changed:
            return changed, None

        backup_path = _write_backup(backup_dir, target_bytes)
        rendered = (
            json.dumps(updated, indent=2, ensure_ascii=False) + "\n"
        ).encode("utf-8")
        stage_path: Path | None = None
        try:
            stage_descriptor, stage_name = tempfile.mkstemp(
                prefix=f".{target_path.name}.content-sync.",
                dir=target_path.parent,
            )
            stage_path = Path(stage_name)
            with os.fdopen(stage_descriptor, "wb") as stage:
                stage.write(rendered)
                stage.flush()
                os.fchmod(stage.fileno(), 0o600)
                os.fchown(stage.fileno(), target_stat.st_uid, target_stat.st_gid)
                os.fsync(stage.fileno())

            _assert_target_unchanged(target_path, target_stat, target_bytes)
            os.replace(stage_path, target_path)
            stage_path = None
            _fsync_directory(target_path.parent)
            return changed, backup_path
        finally:
            if stage_path is not None:
                stage_path.unlink(missing_ok=True)

    if not apply:
        # Dry-run remains filesystem read-only. Its snapshot may become stale,
        # but it cannot overwrite a concurrent writer.
        return synchronize_snapshot()
    with _canonical_client_json_lock(target_path):
        return synchronize_snapshot()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--target", type=Path, required=True)
    parser.add_argument("--backup-dir", type=Path, required=True)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="write the two reviewed fields; without this flag, perform a dry run",
    )
    args = parser.parse_args()

    changed, backup_path = sync(
        args.source,
        args.target,
        args.backup_dir,
        apply=args.apply,
    )
    mode = "applied" if args.apply else "dry-run"
    fields = ", ".join(changed) if changed else "none"
    print(f"{mode}: changed fields: {fields}")
    if backup_path is not None:
        print(f"protected backup: {backup_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
