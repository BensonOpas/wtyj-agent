import copy
import importlib.util
import json
import os
from pathlib import Path
import stat
import subprocess
import sys

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
