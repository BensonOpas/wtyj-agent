import copy
import importlib.util
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import threading

import pytest


SCRIPT = Path(__file__).parents[2] / "scripts" / "sync_mermaid_config_fields.py"
SPEC = importlib.util.spec_from_file_location("sync_mermaid_config_fields", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def _source():
    return {
        "slug": "mermaid",
        "agent_persona": {"freeform_notes": "reviewed prompt with gluten-free boundary"},
        "faq": {"gluten_free": "reviewed gluten-free answer", "contact": "published"},
        "channel_account_allowlist": {"mode": "strict", "zernio_accounts": []},
    }


def _target():
    return {
        "slug": "mermaid",
        "password": "live-password-must-survive",
        "access_key": "live-access-key-must-survive",
        "whatsapp_connect_token": "live-connect-token-must-survive",
        "whatsapp_connect_token_expires_at": "2099-01-01T00:00:00Z",
        "agent_persona": {"freeform_notes": "older reviewed prompt"},
        "faq": {"contact": "published"},
        "channel_account_allowlist": {
            "mode": "strict",
            "zernio_accounts": ["live-provider-account"],
        },
        "social_profiles": {
            "demo_facebook": {
                "url": "https://example.invalid/live-page",
                "connection_status": "connected",
            }
        },
    }


def _write_json(path, value, mode=0o600):
    path.write_text(json.dumps(value, indent=2) + "\n")
    path.chmod(mode)


def test_merge_changes_only_the_two_reviewed_content_fields():
    source = _source()
    target = _target()
    expected = copy.deepcopy(target)
    expected["agent_persona"]["freeform_notes"] = source["agent_persona"][
        "freeform_notes"
    ]
    expected["faq"]["gluten_free"] = source["faq"]["gluten_free"]

    updated, changed = MODULE.merge_reviewed_fields(source, target)

    assert updated == expected
    assert changed == ["agent_persona.freeform_notes", "faq.gluten_free"]
    assert target == _target()


def test_dry_run_does_not_write_or_create_secret_backup(tmp_path):
    source_path = tmp_path / "source.json"
    target_path = tmp_path / "client.json"
    backup_dir = tmp_path / "outside" / "backups"
    _write_json(source_path, _source())
    _write_json(target_path, _target())
    original = target_path.read_bytes()

    changed, backup = MODULE.sync(
        source_path,
        target_path,
        backup_dir,
        apply=False,
    )

    assert changed == ["agent_persona.freeform_notes", "faq.gluten_free"]
    assert backup is None
    assert target_path.read_bytes() == original
    assert not backup_dir.exists()
    assert not target_path.with_suffix(".json.lock").exists()


def test_apply_preserves_credentials_provider_state_and_file_mode(tmp_path, monkeypatch):
    repository = tmp_path / "repository"
    repository.mkdir()
    monkeypatch.setattr(MODULE, "REPOSITORY_ROOT", repository)
    source_path = repository / "source.json"
    target_path = tmp_path / "live" / "client.json"
    target_path.parent.mkdir()
    backup_dir = tmp_path / "protected-backups"
    _write_json(source_path, _source())
    _write_json(target_path, _target())
    original = target_path.read_bytes()

    changed, backup = MODULE.sync(
        source_path,
        target_path,
        backup_dir,
        apply=True,
    )

    assert changed == ["agent_persona.freeform_notes", "faq.gluten_free"]
    assert backup is not None
    assert backup.read_bytes() == original
    assert stat.S_IMODE(backup.stat().st_mode) == 0o600
    assert stat.S_IMODE(backup_dir.stat().st_mode) == 0o700
    assert stat.S_IMODE(target_path.stat().st_mode) == 0o600
    assert stat.S_IMODE(target_path.with_suffix(".json.lock").stat().st_mode) == 0o600
    live = json.loads(target_path.read_text())
    assert live["password"] == _target()["password"]
    assert live["access_key"] == _target()["access_key"]
    assert live["whatsapp_connect_token"] == _target()["whatsapp_connect_token"]
    assert live["channel_account_allowlist"] == _target()["channel_account_allowlist"]
    assert live["social_profiles"] == _target()["social_profiles"]
    assert live["agent_persona"]["freeform_notes"] == _source()["agent_persona"][
        "freeform_notes"
    ]
    assert live["faq"]["gluten_free"] == _source()["faq"]["gluten_free"]


def test_cli_never_prints_live_values(tmp_path):
    source_path = tmp_path / "source.json"
    target_path = tmp_path / "client.json"
    backup_dir = tmp_path / "backups"
    _write_json(source_path, _source())
    _write_json(target_path, _target())

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--source",
            str(source_path),
            "--target",
            str(target_path),
            "--backup-dir",
            str(backup_dir),
        ],
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "dry-run: changed fields:" in result.stdout
    for value in (
        _target()["password"],
        _target()["access_key"],
        _target()["whatsapp_connect_token"],
        _target()["channel_account_allowlist"]["zernio_accounts"][0],
    ):
        assert value not in result.stdout
        assert value not in result.stderr


def test_apply_rejects_insecure_live_file_mode(tmp_path, monkeypatch):
    repository = tmp_path / "repository"
    repository.mkdir()
    monkeypatch.setattr(MODULE, "REPOSITORY_ROOT", repository)
    source_path = repository / "source.json"
    target_path = tmp_path / "client.json"
    _write_json(source_path, _source())
    _write_json(target_path, _target(), mode=0o644)

    with pytest.raises(ValueError, match="mode 0600"):
        MODULE.sync(
            source_path,
            target_path,
            tmp_path / "backups",
            apply=True,
        )


def test_sync_rejects_wrong_tenant_and_symlink_target(tmp_path):
    source_path = tmp_path / "source.json"
    real_target = tmp_path / "client.json"
    linked_target = tmp_path / "linked-client.json"
    wrong = _target()
    wrong["slug"] = "unboks"
    _write_json(source_path, _source())
    _write_json(real_target, wrong)
    linked_target.symlink_to(real_target)

    with pytest.raises(ValueError, match="must both be the Mermaid tenant"):
        MODULE.sync(
            source_path,
            real_target,
            tmp_path / "backups",
            apply=False,
        )
    with pytest.raises(ValueError, match="not a symlink"):
        MODULE.sync(
            source_path,
            linked_target,
            tmp_path / "backups",
            apply=False,
        )


def test_sync_rejects_same_source_and_target_path(tmp_path):
    client_path = tmp_path / "client.json"
    _write_json(client_path, _source())

    with pytest.raises(ValueError, match="must be different files"):
        MODULE.sync(
            client_path,
            client_path,
            tmp_path / "backups",
            apply=False,
        )


def test_apply_waits_for_canonical_writer_and_preserves_its_replacement(
    tmp_path,
    monkeypatch,
):
    repository = tmp_path / "repository"
    repository.mkdir()
    monkeypatch.setattr(MODULE, "REPOSITORY_ROOT", repository)
    source_path = repository / "source.json"
    target_path = tmp_path / "live" / "client.json"
    target_path.parent.mkdir()
    backup_dir = tmp_path / "protected-backups"
    _write_json(source_path, _source())
    _write_json(target_path, _target())

    lock_path = target_path.with_suffix(".json.lock")
    lock_descriptor = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
    original_flock = MODULE.fcntl.flock
    original_flock(lock_descriptor, MODULE.fcntl.LOCK_EX)
    lock_stat = os.fstat(lock_descriptor)
    attempted = threading.Event()
    acquired = threading.Event()

    def observed_flock(descriptor, operation):
        if (
            operation & MODULE.fcntl.LOCK_EX
            and os.fstat(descriptor).st_dev == lock_stat.st_dev
            and os.fstat(descriptor).st_ino == lock_stat.st_ino
        ):
            attempted.set()
            result = original_flock(descriptor, operation)
            acquired.set()
            return result
        return original_flock(descriptor, operation)

    monkeypatch.setattr(MODULE.fcntl, "flock", observed_flock)
    outcome = {}

    def run_sync():
        try:
            outcome["result"] = MODULE.sync(
                source_path,
                target_path,
                backup_dir,
                apply=True,
            )
        except BaseException as exc:  # pragma: no cover - surfaced below
            outcome["error"] = exc

    sync_thread = threading.Thread(target=run_sync)
    sync_thread.start()
    assert attempted.wait(timeout=5)
    try:
        assert not acquired.is_set()
        provider_update = _target()
        provider_update["password"] = "provider-writer-password"
        provider_update["channel_account_allowlist"]["zernio_accounts"] = [
            "provider-writer-account"
        ]
        replacement = target_path.parent / ".provider-replacement"
        _write_json(replacement, provider_update)
        replacement.replace(target_path)
    finally:
        original_flock(lock_descriptor, MODULE.fcntl.LOCK_UN)
        os.close(lock_descriptor)

    assert acquired.wait(timeout=5)
    sync_thread.join(timeout=5)
    assert not sync_thread.is_alive()
    assert "error" not in outcome
    changed, backup = outcome["result"]
    assert changed == ["agent_persona.freeform_notes", "faq.gluten_free"]
    assert backup is not None
    assert json.loads(backup.read_text()) == provider_update
    live = json.loads(target_path.read_text())
    assert live["password"] == "provider-writer-password"
    assert live["channel_account_allowlist"]["zernio_accounts"] == [
        "provider-writer-account"
    ]
    assert live["agent_persona"]["freeform_notes"] == _source()["agent_persona"][
        "freeform_notes"
    ]
    assert live["faq"]["gluten_free"] == _source()["faq"]["gluten_free"]


def test_apply_holds_canonical_lock_through_atomic_replace(
    tmp_path,
    monkeypatch,
):
    repository = tmp_path / "repository"
    repository.mkdir()
    monkeypatch.setattr(MODULE, "REPOSITORY_ROOT", repository)
    source_path = repository / "source.json"
    target_path = tmp_path / "live" / "client.json"
    target_path.parent.mkdir()
    backup_dir = tmp_path / "protected-backups"
    _write_json(source_path, _source())
    _write_json(target_path, _target())

    target_checked = threading.Event()
    permit_replace = threading.Event()
    original_assert_unchanged = MODULE._assert_target_unchanged

    def pause_after_final_check(path, expected_stat, expected_bytes):
        original_assert_unchanged(path, expected_stat, expected_bytes)
        target_checked.set()
        assert permit_replace.wait(timeout=5)

    monkeypatch.setattr(
        MODULE,
        "_assert_target_unchanged",
        pause_after_final_check,
    )
    sync_outcome = {}
    writer_outcome = {}

    def run_sync():
        try:
            sync_outcome["result"] = MODULE.sync(
                source_path,
                target_path,
                backup_dir,
                apply=True,
            )
        except BaseException as exc:  # pragma: no cover - surfaced below
            sync_outcome["error"] = exc

    writer_attempted = threading.Event()
    writer_acquired = threading.Event()

    def run_provider_writer():
        lock_path = target_path.with_suffix(".json.lock")
        descriptor = os.open(lock_path, os.O_RDWR)
        try:
            writer_attempted.set()
            MODULE.fcntl.flock(descriptor, MODULE.fcntl.LOCK_EX)
            writer_acquired.set()
            value = json.loads(target_path.read_text())
            value["channel_account_allowlist"]["zernio_accounts"] = [
                "later-provider-account"
            ]
            replacement = target_path.parent / ".later-provider-replacement"
            _write_json(replacement, value)
            replacement.replace(target_path)
            writer_outcome["finished"] = True
        except BaseException as exc:  # pragma: no cover - surfaced below
            writer_outcome["error"] = exc
        finally:
            MODULE.fcntl.flock(descriptor, MODULE.fcntl.LOCK_UN)
            os.close(descriptor)

    sync_thread = threading.Thread(target=run_sync)
    sync_thread.start()
    assert target_checked.wait(timeout=5)
    writer_thread = threading.Thread(target=run_provider_writer)
    writer_thread.start()
    assert writer_attempted.wait(timeout=5)
    assert not writer_acquired.is_set()
    permit_replace.set()

    sync_thread.join(timeout=5)
    writer_thread.join(timeout=5)
    assert not sync_thread.is_alive()
    assert not writer_thread.is_alive()
    assert "error" not in sync_outcome
    assert "error" not in writer_outcome
    assert writer_outcome["finished"] is True
    live = json.loads(target_path.read_text())
    assert live["channel_account_allowlist"]["zernio_accounts"] == [
        "later-provider-account"
    ]
    assert live["agent_persona"]["freeform_notes"] == _source()["agent_persona"][
        "freeform_notes"
    ]
    assert live["faq"]["gluten_free"] == _source()["faq"]["gluten_free"]


def test_apply_rejects_late_target_symlink_without_touching_its_destination(
    tmp_path,
    monkeypatch,
):
    repository = tmp_path / "repository"
    repository.mkdir()
    monkeypatch.setattr(MODULE, "REPOSITORY_ROOT", repository)
    source_path = repository / "source.json"
    target_path = tmp_path / "live" / "client.json"
    target_path.parent.mkdir()
    backup_dir = tmp_path / "protected-backups"
    victim_path = tmp_path / "victim.json"
    _write_json(source_path, _source())
    _write_json(target_path, _target())
    victim = {"slug": "victim", "secret": "must-not-be-read-or-modified"}
    _write_json(victim_path, victim)
    victim_bytes = victim_path.read_bytes()
    original_write_backup = MODULE._write_backup

    def swap_target_after_read(path, original):
        backup = original_write_backup(path, original)
        target_path.unlink()
        target_path.symlink_to(victim_path)
        return backup

    monkeypatch.setattr(MODULE, "_write_backup", swap_target_after_read)

    with pytest.raises(RuntimeError, match="target changed during sync"):
        MODULE.sync(
            source_path,
            target_path,
            backup_dir,
            apply=True,
        )

    assert target_path.is_symlink()
    assert victim_path.read_bytes() == victim_bytes
    assert list(target_path.parent.glob(".client.json.content-sync.*")) == []


def test_apply_rejects_symlinked_canonical_lock(tmp_path, monkeypatch):
    repository = tmp_path / "repository"
    repository.mkdir()
    monkeypatch.setattr(MODULE, "REPOSITORY_ROOT", repository)
    source_path = repository / "source.json"
    target_path = tmp_path / "live" / "client.json"
    target_path.parent.mkdir()
    backup_dir = tmp_path / "protected-backups"
    lock_destination = tmp_path / "unrelated-lock"
    _write_json(source_path, _source())
    _write_json(target_path, _target())
    lock_destination.write_text("untouched")
    lock_path = target_path.with_suffix(".json.lock")
    lock_path.symlink_to(lock_destination)

    with pytest.raises(ValueError, match="client.json lock"):
        MODULE.sync(
            source_path,
            target_path,
            backup_dir,
            apply=True,
        )

    assert lock_path.is_symlink()
    assert lock_destination.read_text() == "untouched"
    assert json.loads(target_path.read_text()) == _target()
