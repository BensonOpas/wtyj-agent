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
        "agent_persona": {
            "freeform_notes": "reviewed prompt with gluten-free boundary",
            "unsupported_attachment_handoff": {
                "enabled": True,
                "reply": "A person needs to review this attachment.",
            },
        },
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


def _assert_uncommitted_target(path):
    assert path.read_bytes() == MODULE._UNCOMMITTED_STAGE
    with pytest.raises(json.JSONDecodeError):
        json.loads(path.read_text())


def test_merge_changes_only_the_three_reviewed_content_fields():
    source = _source()
    target = _target()
    expected = copy.deepcopy(target)
    expected["agent_persona"]["freeform_notes"] = source["agent_persona"][
        "freeform_notes"
    ]
    expected["agent_persona"]["unsupported_attachment_handoff"] = source[
        "agent_persona"
    ]["unsupported_attachment_handoff"]
    expected["faq"]["gluten_free"] = source["faq"]["gluten_free"]

    updated, changed = MODULE.merge_reviewed_fields(source, target)

    assert updated == expected
    assert changed == ["agent_persona.freeform_notes", "agent_persona.unsupported_attachment_handoff", "faq.gluten_free"]
    assert target == _target()


@pytest.mark.parametrize("policy", [
    None,
    {"enabled": "true", "reply": "Review needed"},
    {"enabled": True, "reply": ""},
    {"enabled": True, "reply": "x" * 4097},
    {"enabled": True, "reply": "Review needed", "account_id": "must-not-copy"},
])
def test_attachment_policy_sync_rejects_unreviewed_shape(policy):
    source = _source()
    source["agent_persona"]["unsupported_attachment_handoff"] = policy
    target = _target()

    with pytest.raises(ValueError, match="unsupported_attachment_handoff"):
        MODULE.merge_reviewed_fields(source, target)

    assert target == _target()


def test_reviewed_attachment_policy_sync_is_idempotent_and_copies_no_siblings():
    source = _source()
    source["agent_persona"]["unreviewed_provider_setting"] = "do-not-copy"
    target = _target()
    target["agent_persona"]["live_operator_setting"] = "must-survive"

    updated, _ = MODULE.merge_reviewed_fields(source, target)
    repeated, changed = MODULE.merge_reviewed_fields(source, updated)

    assert changed == []
    assert repeated == updated
    assert updated["agent_persona"]["live_operator_setting"] == "must-survive"
    assert "unreviewed_provider_setting" not in updated["agent_persona"]


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

    assert changed == ["agent_persona.freeform_notes", "agent_persona.unsupported_attachment_handoff", "faq.gluten_free"]
    assert backup is None
    assert target_path.read_bytes() == original
    assert not backup_dir.exists()
    assert not target_path.with_suffix(".json.lock").exists()


def test_apply_requires_explicit_service_stopped_acknowledgement(tmp_path):
    source_path = tmp_path / "source.json"
    target_path = tmp_path / "client.json"
    backup_dir = tmp_path / "backups"
    _write_json(source_path, _source())
    _write_json(target_path, _target())
    original = target_path.read_bytes()

    with pytest.raises(ValueError, match="service_stopped=True"):
        MODULE.sync(
            source_path,
            target_path,
            backup_dir,
            apply=True,
        )

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
        service_stopped=True,
    )

    assert changed == ["agent_persona.freeform_notes", "agent_persona.unsupported_attachment_handoff", "faq.gluten_free"]
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
    assert live["agent_persona"]["unsupported_attachment_handoff"] == _source()[
        "agent_persona"
    ]["unsupported_attachment_handoff"]


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


def test_cli_apply_refuses_without_service_stopped_acknowledgement(tmp_path):
    source_path = tmp_path / "source.json"
    target_path = tmp_path / "client.json"
    backup_dir = tmp_path / "backups"
    _write_json(source_path, _source())
    _write_json(target_path, _target())
    original = target_path.read_bytes()

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
            "--apply",
        ],
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 2
    assert "--apply requires --service-stopped" in result.stderr
    assert target_path.read_bytes() == original
    assert not backup_dir.exists()


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
            service_stopped=True,
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
                service_stopped=True,
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
    assert changed == ["agent_persona.freeform_notes", "agent_persona.unsupported_attachment_handoff", "faq.gluten_free"]
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
                service_stopped=True,
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


def test_apply_target_precondition_blocks_replacement_before_exchange(
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

    provider_update = _target()
    provider_update["password"] = "last-window-provider-password"
    provider_update["channel_account_allowlist"]["zernio_accounts"] = [
        "last-window-provider-account"
    ]
    original_assert_unchanged = MODULE._assert_target_unchanged
    platform_exchange_calls = []

    def replace_immediately_after_final_check(path, expected_stat, expected_bytes):
        original_assert_unchanged(path, expected_stat, expected_bytes)
        replacement = target_path.parent / ".noncooperating-provider-replacement"
        _write_json(replacement, provider_update)
        replacement.replace(target_path)

    monkeypatch.setattr(
        MODULE,
        "_assert_target_unchanged",
        replace_immediately_after_final_check,
    )
    monkeypatch.setattr(
        MODULE,
        "_exchange_directory_entries",
        lambda *_args: platform_exchange_calls.append(True),
    )

    with pytest.raises(RuntimeError, match="refusing replacement"):
        MODULE.sync(
            source_path,
            target_path,
            backup_dir,
            apply=True,
            service_stopped=True,
        )

    assert json.loads(target_path.read_text()) == provider_update
    assert list(target_path.parent.glob(".client.json.content-sync.*")) == []
    assert platform_exchange_calls == []


def test_apply_single_writer_in_capture_to_swap_window_never_leaves_stale_json_live(
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

    provider_update = _target()
    provider_update["password"] = "capture-to-swap-writer-must-be-recoverable"
    provider_update["channel_account_allowlist"]["zernio_accounts"] = [
        "capture-to-swap-provider-account"
    ]
    original_exchange = MODULE._exchange_directory_entries

    def replace_target_then_swap(first, second):
        replacement = target_path.parent / ".capture-to-swap-writer"
        _write_json(replacement, provider_update)
        replacement.replace(target_path)
        original_exchange(first, second)

    monkeypatch.setattr(
        MODULE,
        "_exchange_directory_entries",
        replace_target_then_swap,
    )

    with pytest.raises(RuntimeError, match="live target is uncommitted"):
        MODULE.sync(
            source_path,
            target_path,
            backup_dir,
            apply=True,
            service_stopped=True,
        )

    _assert_uncommitted_target(target_path)
    recovery_files = list(target_path.parent.glob(".client.json.content-sync.*"))
    assert len(recovery_files) == 1
    assert json.loads(recovery_files[0].read_text()) == provider_update


def test_apply_never_rolls_replaced_stage_entry_into_live_target(
    tmp_path,
    monkeypatch,
):
    repository = tmp_path / "repository"
    repository.mkdir()
    monkeypatch.setattr(MODULE, "REPOSITORY_ROOT", repository)
    source_path = repository / "source.json"
    target_path = tmp_path / "live" / "client.json"
    target_path.parent.mkdir()
    _write_json(source_path, _source())
    _write_json(target_path, _target())
    original_exchange = MODULE._atomic_exchange
    exchange_count = 0
    injected = {
        "slug": "mermaid",
        "password": "must-never-become-live",
    }

    def replace_stage_after_first_exchange(first, second, **kwargs):
        nonlocal exchange_count
        receipt = original_exchange(first, second, **kwargs)
        exchange_count += 1
        if exchange_count == 1:
            Path(first).unlink()
            _write_json(Path(first), injected)
        return receipt

    monkeypatch.setattr(
        MODULE,
        "_atomic_exchange",
        replace_stage_after_first_exchange,
    )

    with pytest.raises(RuntimeError, match="recovery file was preserved"):
        MODULE.sync(
            source_path,
            target_path,
            tmp_path / "protected-backups",
            apply=True,
            service_stopped=True,
        )

    _assert_uncommitted_target(target_path)
    recovery_files = list(
        target_path.parent.glob(".client.json.content-sync.*")
    )
    assert len(recovery_files) == 1
    assert json.loads(recovery_files[0].read_text()) == injected
    assert exchange_count == 1


def test_apply_receipt_capture_failure_preserves_recovery_and_invalid_live_target(
    tmp_path,
    monkeypatch,
):
    repository = tmp_path / "repository"
    repository.mkdir()
    monkeypatch.setattr(MODULE, "REPOSITORY_ROOT", repository)
    source_path = repository / "source.json"
    target_path = tmp_path / "live" / "client.json"
    target_path.parent.mkdir()
    _write_json(source_path, _source())
    _write_json(target_path, _target())
    original_exchange = MODULE._exchange_directory_entries
    original_capture = MODULE._capture_entry_snapshot
    exchange_finished = False

    def observe_exchange(first, second):
        nonlocal exchange_finished
        original_exchange(first, second)
        exchange_finished = True

    def fail_first_receipt_capture(path):
        if exchange_finished:
            raise OSError("injected receipt read failure")
        return original_capture(path)

    monkeypatch.setattr(MODULE, "_exchange_directory_entries", observe_exchange)
    monkeypatch.setattr(MODULE, "_capture_entry_snapshot", fail_first_receipt_capture)

    with pytest.raises(RuntimeError, match="receipt was unavailable"):
        MODULE.sync(
            source_path,
            target_path,
            tmp_path / "protected-backups",
            apply=True,
            service_stopped=True,
        )

    _assert_uncommitted_target(target_path)
    recovery_files = list(target_path.parent.glob(".client.json.content-sync.*"))
    assert len(recovery_files) == 1
    assert json.loads(recovery_files[0].read_text()) == _target()


def test_apply_system_exit_after_swap_preserves_displaced_live_config(
    tmp_path,
    monkeypatch,
):
    repository = tmp_path / "repository"
    repository.mkdir()
    monkeypatch.setattr(MODULE, "REPOSITORY_ROOT", repository)
    source_path = repository / "source.json"
    target_path = tmp_path / "live" / "client.json"
    target_path.parent.mkdir()
    _write_json(source_path, _source())
    _write_json(target_path, _target())
    original_exchange = MODULE._exchange_directory_entries

    def swap_then_exit(first, second):
        original_exchange(first, second)
        raise SystemExit("injected interruption after exchange")

    monkeypatch.setattr(MODULE, "_exchange_directory_entries", swap_then_exit)

    with pytest.raises(SystemExit, match="interruption after exchange"):
        MODULE.sync(
            source_path,
            target_path,
            tmp_path / "protected-backups",
            apply=True,
            service_stopped=True,
        )

    _assert_uncommitted_target(target_path)
    recovery_files = list(target_path.parent.glob(".client.json.content-sync.*"))
    assert len(recovery_files) == 1
    assert json.loads(recovery_files[0].read_text()) == _target()


def test_apply_detects_same_inode_edit_during_exchange_snapshot(
    tmp_path,
    monkeypatch,
):
    repository = tmp_path / "repository"
    repository.mkdir()
    monkeypatch.setattr(MODULE, "REPOSITORY_ROOT", repository)
    source_path = repository / "source.json"
    target_path = tmp_path / "live" / "client.json"
    target_path.parent.mkdir()
    _write_json(source_path, _source())
    _write_json(target_path, _target())
    original_read = MODULE._read_regular_file_no_follow
    original_exchange = MODULE._exchange_directory_entries
    armed = False
    mutated = False
    original_secret = _target()["password"].encode()
    mutated_secret = b"x" * len(original_secret)

    def arm_after_exchange(first, second):
        nonlocal armed
        original_exchange(first, second)
        armed = True

    def mutate_same_inode_after_read(path, *, label):
        nonlocal mutated
        raw, metadata = original_read(path, label=label)
        if armed and not mutated and Path(path).name.startswith(
            ".client.json.content-sync."
        ):
            replacement = raw.replace(original_secret, mutated_secret)
            assert len(replacement) == len(raw)
            assert replacement != raw
            with open(path, "r+b", buffering=0) as stream:
                stream.write(replacement)
                os.fsync(stream.fileno())
            mutated = True
        return raw, metadata

    monkeypatch.setattr(
        MODULE,
        "_exchange_directory_entries",
        arm_after_exchange,
    )
    monkeypatch.setattr(
        MODULE,
        "_read_regular_file_no_follow",
        mutate_same_inode_after_read,
    )

    with pytest.raises(RuntimeError, match="recovery file was preserved"):
        MODULE.sync(
            source_path,
            target_path,
            tmp_path / "protected-backups",
            apply=True,
            service_stopped=True,
        )

    assert mutated is True
    _assert_uncommitted_target(target_path)
    recovery_files = list(
        target_path.parent.glob(".client.json.content-sync.*")
    )
    assert len(recovery_files) == 1
    assert json.loads(recovery_files[0].read_text())["password"] == (
        mutated_secret.decode()
    )


def test_apply_keeps_latest_writer_live_during_exchange_receipt_race(
    tmp_path,
    monkeypatch,
):
    repository = tmp_path / "repository"
    repository.mkdir()
    monkeypatch.setattr(MODULE, "REPOSITORY_ROOT", repository)
    source_path = repository / "source.json"
    target_path = tmp_path / "live" / "client.json"
    target_path.parent.mkdir()
    _write_json(source_path, _source())
    _write_json(target_path, _target())

    writer_one = _target()
    writer_one["password"] = "first-concurrent-writer"
    writer_two = _target()
    writer_two["password"] = "second-concurrent-writer-must-remain-live"
    original_exchange = MODULE._exchange_directory_entries
    exchange_count = 0

    def install_two_writers_around_exchange(first, second):
        nonlocal exchange_count
        replacement = target_path.parent / ".first-concurrent-writer"
        _write_json(replacement, writer_one)
        replacement.replace(target_path)
        original_exchange(first, second)
        exchange_count += 1
        replacement = target_path.parent / ".second-concurrent-writer"
        _write_json(replacement, writer_two)
        replacement.replace(target_path)

    monkeypatch.setattr(
        MODULE,
        "_exchange_directory_entries",
        install_two_writers_around_exchange,
    )

    with pytest.raises(RuntimeError, match="recovery file was preserved"):
        MODULE.sync(
            source_path,
            target_path,
            tmp_path / "protected-backups",
            apply=True,
            service_stopped=True,
        )

    assert json.loads(target_path.read_text()) == writer_two
    recovery_files = list(
        target_path.parent.glob(".client.json.content-sync.*")
    )
    assert len(recovery_files) == 1
    assert json.loads(recovery_files[0].read_text()) == writer_one
    assert exchange_count == 1


def test_apply_writer_after_commit_fsync_remains_live(
    tmp_path,
    monkeypatch,
):
    repository = tmp_path / "repository"
    repository.mkdir()
    monkeypatch.setattr(MODULE, "REPOSITORY_ROOT", repository)
    source_path = repository / "source.json"
    target_path = tmp_path / "live" / "client.json"
    target_path.parent.mkdir()
    _write_json(source_path, _source())
    _write_json(target_path, _target())

    latest = _target()
    latest["password"] = "writer-after-generated-inode-fsync"
    original_overwrite = MODULE._overwrite_open_file

    def commit_then_replace_target(descriptor, payload):
        metadata = original_overwrite(descriptor, payload)
        replacement = target_path.parent / ".post-commit-writer"
        _write_json(replacement, latest)
        replacement.replace(target_path)
        return metadata

    monkeypatch.setattr(MODULE, "_overwrite_open_file", commit_then_replace_target)

    with pytest.raises(RuntimeError, match="target changed while"):
        MODULE.sync(
            source_path,
            target_path,
            tmp_path / "protected-backups",
            apply=True,
            service_stopped=True,
        )

    assert json.loads(target_path.read_text()) == latest
    recovery_files = list(target_path.parent.glob(".client.json.content-sync.*"))
    assert len(recovery_files) == 1
    assert json.loads(recovery_files[0].read_text()) == _target()


def test_apply_commit_write_failure_leaves_invalid_target_and_recovery(
    tmp_path,
    monkeypatch,
):
    repository = tmp_path / "repository"
    repository.mkdir()
    monkeypatch.setattr(MODULE, "REPOSITORY_ROOT", repository)
    source_path = repository / "source.json"
    target_path = tmp_path / "live" / "client.json"
    target_path.parent.mkdir()
    _write_json(source_path, _source())
    _write_json(target_path, _target())

    def fail_partial_commit(descriptor, _payload):
        os.lseek(descriptor, 0, os.SEEK_SET)
        os.ftruncate(descriptor, 0)
        os.write(descriptor, b"{")
        os.fsync(descriptor)
        raise OSError("injected durable write failure")

    monkeypatch.setattr(MODULE, "_overwrite_open_file", fail_partial_commit)

    with pytest.raises(OSError, match="durable write failure"):
        MODULE.sync(
            source_path,
            target_path,
            tmp_path / "protected-backups",
            apply=True,
            service_stopped=True,
        )

    with pytest.raises(json.JSONDecodeError):
        json.loads(target_path.read_text())
    recovery_files = list(target_path.parent.glob(".client.json.content-sync.*"))
    assert len(recovery_files) == 1
    assert json.loads(recovery_files[0].read_text()) == _target()


def test_apply_blocks_symlink_swap_before_atomic_exchange(tmp_path, monkeypatch):
    repository = tmp_path / "repository"
    repository.mkdir()
    monkeypatch.setattr(MODULE, "REPOSITORY_ROOT", repository)
    source_path = repository / "source.json"
    target_path = tmp_path / "live" / "client.json"
    target_path.parent.mkdir()
    victim_path = tmp_path / "victim.json"
    _write_json(source_path, _source())
    _write_json(target_path, _target())
    _write_json(victim_path, {"slug": "victim", "secret": "untouched"})
    victim_bytes = victim_path.read_bytes()
    original_assert_unchanged = MODULE._assert_target_unchanged

    def symlink_immediately_after_final_check(path, expected_stat, expected_bytes):
        original_assert_unchanged(path, expected_stat, expected_bytes)
        target_path.unlink()
        target_path.symlink_to(victim_path)

    monkeypatch.setattr(
        MODULE,
        "_assert_target_unchanged",
        symlink_immediately_after_final_check,
    )

    with pytest.raises(RuntimeError, match="refusing replacement"):
        MODULE.sync(
            source_path,
            target_path,
            tmp_path / "protected-backups",
            apply=True,
            service_stopped=True,
        )

    assert target_path.is_symlink()
    assert victim_path.read_bytes() == victim_bytes
    assert list(target_path.parent.glob(".client.json.content-sync.*")) == []


def test_apply_fails_closed_when_atomic_exchange_is_unavailable(tmp_path, monkeypatch):
    repository = tmp_path / "repository"
    repository.mkdir()
    monkeypatch.setattr(MODULE, "REPOSITORY_ROOT", repository)
    source_path = repository / "source.json"
    target_path = tmp_path / "live" / "client.json"
    target_path.parent.mkdir()
    _write_json(source_path, _source())
    _write_json(target_path, _target())
    original = target_path.read_bytes()

    def unavailable(*_args, **_kwargs):
        raise MODULE._AtomicExchangeNoMutationError(
            "safe atomic config exchange is unavailable"
        )

    monkeypatch.setattr(
        MODULE,
        "_atomic_exchange",
        unavailable,
    )

    with pytest.raises(RuntimeError, match="atomic config exchange is unavailable"):
        MODULE.sync(
            source_path,
            target_path,
            tmp_path / "protected-backups",
            apply=True,
            service_stopped=True,
        )

    assert target_path.read_bytes() == original
    assert list(target_path.parent.glob(".client.json.content-sync.*")) == []


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
            service_stopped=True,
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
            service_stopped=True,
        )

    assert lock_path.is_symlink()
    assert lock_destination.read_text() == "untouched"
    assert json.loads(target_path.read_text()) == _target()
