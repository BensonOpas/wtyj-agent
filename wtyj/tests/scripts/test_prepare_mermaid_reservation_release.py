import copy
import importlib.util
import json
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys

import pytest


SCRIPTS = Path(__file__).parents[2] / "scripts"
sys.path.insert(0, str(SCRIPTS))
SPEC = importlib.util.spec_from_file_location("prepare_mermaid_reservation_release", SCRIPTS / "prepare_mermaid_reservation_release.py")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


PREVIOUS_IMAGE_ID = "sha256:" + "a" * 64
ROLLBACK_IMAGE = MODULE._rollback_image_tag(PREVIOUS_IMAGE_ID)


def test_merge_preserves_all_live_credentials_bindings_and_other_features():
    source = json.loads((Path(__file__).parents[3] / "clients/mermaid/config/client.json").read_text())
    live = copy.deepcopy(source)
    live.update(password="protected", access_key="protected-key", channel_account_allowlist={"mode": "strict", "zernio_accounts": ["exact-account"]})
    live["features"]["other_feature"] = True
    live["social_profiles"] = {"facebook": {"id": "do-not-change"}}
    original = copy.deepcopy(live)
    result = MODULE.merged_config(live, source)
    assert live == original
    assert result["password"] == original["password"]
    assert result["access_key"] == original["access_key"]
    assert result["channel_account_allowlist"] == original["channel_account_allowlist"]
    assert result["social_profiles"] == original["social_profiles"]
    assert result["features"]["other_feature"] is True
    assert result["features"]["mermaid_reminders"] is False


@pytest.mark.parametrize("slug,accounts", [("ali-car-rental", ["one"]), ("mermaid", []), ("mermaid", ["one", "two"])])
def test_merge_rejects_wrong_tenant_or_account_binding(slug, accounts):
    with pytest.raises(ValueError):
        MODULE.merged_config({"slug": slug, "channel_account_allowlist": {"mode": "strict", "zernio_accounts": accounts}}, {"slug": "mermaid"})


def test_env_retains_credentials_and_reuses_signing_secret():
    original = "# Protected\nANTHROPIC_API_KEY=keep-it\nMERMAID_DEMO_SIGNING_SECRET=keep-signature\nTENANT_SLUG=mermaid\n"
    prepared = MODULE.prepared_env(original)
    assert "ANTHROPIC_API_KEY=keep-it\n" in prepared
    assert "MERMAID_DEMO_SIGNING_SECRET=keep-signature\n" in prepared
    assert prepared.count("TENANT_SLUG=") == 1
    assert "UNBOKS_PUBLIC_BASE_URL=https://api.unboks.org/api/mermaid\n" in prepared
    assert "TENANT_RUNTIME_CONTROLS_REQUIRED=true\n" in prepared


def test_private_write_is_complete_and_owner_only(tmp_path):
    path = tmp_path / "protected/value"
    MODULE.private_write(path, b"first")
    MODULE.private_write(path, b"replacement")
    assert path.read_bytes() == b"replacement"
    assert path.stat().st_mode & 0o777 == 0o600
    assert list(path.parent.iterdir()) == [path]


def test_apply_backs_up_stopped_database_and_rollback_preserves_live_audit(
    monkeypatch, tmp_path,
):
    source_root = tmp_path / "source"
    source_config = source_root / "clients/mermaid/config"
    source_config.mkdir(parents=True)
    repository_config = Path(__file__).parents[3] / "clients/mermaid/config"
    shutil.copy(repository_config / "client.json", source_config / "client.json")
    shutil.copy(
        repository_config / "reservation_catalog.json",
        source_config / "reservation_catalog.json",
    )
    shutil.copy(
        repository_config / "response_policy.json",
        source_config / "response_policy.json",
    )

    live = tmp_path / "live"
    (live / "config").mkdir(parents=True)
    (live / "data").mkdir()
    client = json.loads((source_config / "client.json").read_text())
    client["password"] = "preserve-secret"
    client["channel_account_allowlist"] = {
        "mode": "strict",
        "zernio_accounts": ["preserve-account"],
    }
    (live / "config/client.json").write_text(json.dumps(client))
    (live / "config/platform.env").write_text(
        "ANTHROPIC_API_KEY=preserve-key\nMERMAID_DEMO_SIGNING_SECRET=preserve-signing\n"
    )
    (live / "docker-compose.yml").write_text(
        "services:\n  agent:\n    image: wtyj-agent:latest\n"
        "    container_name: wtyj-mermaid\n"
    )
    (live / "config/reservation_catalog.json").write_text(
        '{"version":"old-live-catalog"}\n'
    )
    (live / "config/response_policy.json").write_text(
        '{"version":"old-live-policy"}\n'
    )
    with sqlite3.connect(live / "data/state_registry.db") as connection:
        connection.execute("CREATE TABLE audit (value TEXT)")
        connection.execute("INSERT INTO audit VALUES ('before')")

    files = {
        "client.json": live / "config/client.json",
        "platform.env": live / "config/platform.env",
        "docker-compose.yml": live / "docker-compose.yml",
        "reservation_catalog.json": live / "config/reservation_catalog.json",
        "response_policy.json": live / "config/response_policy.json",
    }
    originals = {name: path.read_bytes() for name, path in files.items()}
    backup_root = tmp_path / "backups"
    release = backup_root / "release-123"
    running = {"value": "true"}
    tagged = []

    def docker_output(command, **_kwargs):
        if command[:3] == ["docker", "inspect", "wtyj-mermaid"]:
            if "{{.State.Running}}" in command:
                return running["value"] + "\n"
            return f"{PREVIOUS_IMAGE_ID} wtyj-agent:latest\n"
        if command[:2] == ["docker", "tag"]:
            assert command == ["docker", "tag", PREVIOUS_IMAGE_ID, ROLLBACK_IMAGE]
            tagged.append(tuple(command))
            return ""
        if command[:3] == ["docker", "image", "inspect"]:
            assert command == [
                "docker", "image", "inspect", "--format", "{{.Id}}",
                ROLLBACK_IMAGE,
            ]
            return PREVIOUS_IMAGE_ID + "\n"
        if command[:2] == ["docker", "ps"]:
            return "wtyj-mermaid wtyj-agent:latest old-id\n"
        raise AssertionError(command)

    monkeypatch.setattr(MODULE, "LIVE", live)
    monkeypatch.setattr(MODULE, "FILES", files)
    monkeypatch.setattr(MODULE, "BACKUP_ROOT", backup_root)
    monkeypatch.setattr(MODULE.subprocess, "check_output", docker_output)
    monkeypatch.setattr(sys, "argv", [
        "prepare_mermaid_reservation_release.py",
        "--source", str(source_root),
        "--release", str(release),
        "--image", "wtyj-agent:tracy-wheelchair-abcdef1",
    ])
    MODULE.main()

    assert not (release / "original/state_registry.db").exists()
    manifest = json.loads((release / "manifest.json").read_text())
    assert manifest["previous_image_id"] == PREVIOUS_IMAGE_ID
    assert manifest["previous_image_reference"] == "wtyj-agent:latest"
    assert manifest["rollback_image"] == ROLLBACK_IMAGE
    assert "image: wtyj-agent:latest\n" in (
        release / "original/docker-compose.yml"
    ).read_text()
    assert f"image: {ROLLBACK_IMAGE}\n" in (
        release / "rollback/docker-compose.yml"
    ).read_text()
    running["value"] = "false"
    monkeypatch.setattr(sys, "argv", [
        "prepare_mermaid_reservation_release.py",
        "--source", str(source_root),
        "--release", str(release),
        "--image", "wtyj-agent:tracy-wheelchair-abcdef1",
        "--apply", "--service-stopped",
    ])
    MODULE.main()

    assert (release / "original/state_registry.db").is_file()
    assert "wtyj-agent:tracy-wheelchair-abcdef1" in (
        live / "docker-compose.yml"
    ).read_text()
    assert (live / "config/reservation_catalog.json").read_bytes() == (
        source_config / "reservation_catalog.json"
    ).read_bytes()
    assert (live / "config/response_policy.json").read_bytes() == (
        source_config / "response_policy.json"
    ).read_bytes()
    with sqlite3.connect(live / "data/state_registry.db") as connection:
        connection.execute("INSERT INTO audit VALUES ('after')")

    monkeypatch.setattr(sys, "argv", [
        "prepare_mermaid_reservation_release.py",
        "--source", str(source_root),
        "--release", str(release),
        "--image", "wtyj-agent:tracy-wheelchair-abcdef1",
        "--rollback", "--service-stopped",
    ])
    MODULE.main()

    expected_rollback = dict(originals)
    expected_rollback["docker-compose.yml"] = MODULE._compose_with_image(
        originals["docker-compose.yml"], ROLLBACK_IMAGE
    )
    assert {name: path.read_bytes() for name, path in files.items()} == expected_rollback
    assert len(tagged) == 3
    with sqlite3.connect(live / "data/state_registry.db") as connection:
        assert connection.execute("SELECT value FROM audit ORDER BY rowid").fetchall() == [
            ("before",), ("after",),
        ]


def test_rollback_is_idempotent_when_apply_never_changed_files(
    monkeypatch, tmp_path,
):
    live = tmp_path / "live"
    (live / "config").mkdir(parents=True)
    files = {
        "client.json": live / "config/client.json",
        "platform.env": live / "config/platform.env",
        "docker-compose.yml": live / "docker-compose.yml",
        "reservation_catalog.json": live / "config/reservation_catalog.json",
        "response_policy.json": live / "config/response_policy.json",
    }
    for name, path in files.items():
        path.write_text(name)
    release = tmp_path / "backups/release"
    (release / "original").mkdir(parents=True)
    (release / "staged").mkdir()
    (release / "rollback").mkdir()
    for name, path in files.items():
        (release / "original" / name).write_bytes(path.read_bytes())
        (release / "staged" / name).write_text("staged-" + name)
        (release / "rollback" / name).write_bytes(path.read_bytes())
    manifest = {
        "candidate_image": "wtyj-agent:tracy-wheelchair-abcdef1",
        "original_hashes": {
            name: MODULE._digest(path.read_bytes()) for name, path in files.items()
        },
        "staged_hashes": {
            name: MODULE._digest((release / "staged" / name).read_bytes())
            for name in files
        },
        "rollback_hashes": {
            name: MODULE._digest((release / "rollback" / name).read_bytes())
            for name in files
        },
        "previous_image_id": PREVIOUS_IMAGE_ID,
        "rollback_image": ROLLBACK_IMAGE,
    }
    (release / "manifest.json").write_text(json.dumps(manifest))

    monkeypatch.setattr(MODULE, "LIVE", live)
    monkeypatch.setattr(MODULE, "FILES", files)
    monkeypatch.setattr(MODULE, "BACKUP_ROOT", release.parent)
    monkeypatch.setattr(MODULE, "_ensure_rollback_image", lambda *_args: None)
    monkeypatch.setattr(
        MODULE.subprocess,
        "check_output",
        lambda *_args, **_kwargs: "false\n",
    )
    monkeypatch.setattr(sys, "argv", [
        "prepare_mermaid_reservation_release.py",
        "--source", str(tmp_path),
        "--release", str(release),
        "--image", "wtyj-agent:tracy-wheelchair-abcdef1",
        "--rollback", "--service-stopped",
    ])

    MODULE.main()
    assert {name: path.read_bytes() for name, path in files.items()} == {
        name: name.encode() for name in files
    }


def _protected_release(tmp_path, *, live_state):
    live = tmp_path / "live"
    release = tmp_path / "backups/release"
    (live / "config").mkdir(parents=True)
    (live / "data").mkdir()
    (release / "original").mkdir(parents=True)
    (release / "staged").mkdir()
    (release / "rollback").mkdir()
    paths = {
        "client.json": live / "config/client.json",
        "platform.env": live / "config/platform.env",
        "docker-compose.yml": live / "docker-compose.yml",
        "reservation_catalog.json": live / "config/reservation_catalog.json",
        "response_policy.json": live / "config/response_policy.json",
    }
    original = {name: ("original-" + name).encode() for name in paths}
    staged = {name: ("staged-" + name).encode() for name in paths}
    for name, path in paths.items():
        path.write_bytes((original if live_state == "original" else staged)[name])
        (release / "original" / name).write_bytes(original[name])
        (release / "staged" / name).write_bytes(staged[name])
        (release / "rollback" / name).write_bytes(original[name])
    with sqlite3.connect(live / "data/state_registry.db") as connection:
        connection.execute("CREATE TABLE audit (value TEXT)")
    image = "wtyj-agent:tracy-safety-abcdef1"
    manifest = {
        "candidate_image": image,
        "original_hashes": {
            name: MODULE._digest(value) for name, value in original.items()
        },
        "staged_hashes": {
            name: MODULE._digest(value) for name, value in staged.items()
        },
        "rollback_hashes": {
            name: MODULE._digest(value) for name, value in original.items()
        },
        "previous_image_id": PREVIOUS_IMAGE_ID,
        "rollback_image": ROLLBACK_IMAGE,
    }
    (release / "manifest.json").write_text(json.dumps(manifest))
    return live, release, paths, original, staged, image


@pytest.mark.parametrize(
    "operation,live_state,tampered_directory",
    [
        ("--apply", "original", "staged"),
        ("--apply", "original", "original"),
        ("--rollback", "staged", "rollback"),
    ],
)
def test_changed_release_payload_cannot_be_applied_or_restored(
    monkeypatch, tmp_path, operation, live_state, tampered_directory,
):
    live, release, paths, original, staged, image = _protected_release(
        tmp_path, live_state=live_state
    )
    before = {name: path.read_bytes() for name, path in paths.items()}
    (release / tampered_directory / "client.json").write_bytes(b"unreviewed")
    monkeypatch.setattr(MODULE, "LIVE", live)
    monkeypatch.setattr(MODULE, "FILES", paths)
    monkeypatch.setattr(MODULE, "BACKUP_ROOT", release.parent)
    monkeypatch.setattr(MODULE, "_ensure_rollback_image", lambda *_args: None)
    monkeypatch.setattr(
        MODULE.subprocess, "check_output", lambda *_args, **_kwargs: "false\n"
    )
    monkeypatch.setattr(sys, "argv", [
        "prepare_mermaid_reservation_release.py",
        "--source", str(tmp_path), "--release", str(release),
        "--image", image, operation, "--service-stopped",
    ])

    with pytest.raises(RuntimeError, match="differs from prepared manifest"):
        MODULE.main()
    assert {name: path.read_bytes() for name, path in paths.items()} == before


@pytest.mark.parametrize(
    "operation,live_state,source_directory,expected_state",
    [
        ("--apply", "original", "staged", "staged"),
        ("--rollback", "staged", "rollback", "original"),
    ],
)
def test_verified_payload_bytes_are_used_if_release_file_changes_before_write(
    monkeypatch, tmp_path, operation, live_state, source_directory, expected_state,
):
    live, release, paths, original, staged, image = _protected_release(
        tmp_path, live_state=live_state
    )
    monkeypatch.setattr(MODULE, "LIVE", live)
    monkeypatch.setattr(MODULE, "FILES", paths)
    monkeypatch.setattr(MODULE, "BACKUP_ROOT", release.parent)
    monkeypatch.setattr(MODULE, "_ensure_rollback_image", lambda *_args: None)
    monkeypatch.setattr(
        MODULE.subprocess, "check_output", lambda *_args, **_kwargs: "false\n"
    )
    real_private_write = MODULE.private_write
    changed = {"done": False}
    def change_after_validation(path, payload):
        if path in paths.values() and not changed["done"]:
            changed["done"] = True
            (release / source_directory / "client.json").write_bytes(
                b"changed-after-validation"
            )
        real_private_write(path, payload)
    monkeypatch.setattr(MODULE, "private_write", change_after_validation)
    monkeypatch.setattr(sys, "argv", [
        "prepare_mermaid_reservation_release.py",
        "--source", str(tmp_path), "--release", str(release),
        "--image", image, operation, "--service-stopped",
    ])

    MODULE.main()
    expected = staged if expected_state == "staged" else original
    assert changed["done"] is True
    assert {name: path.read_bytes() for name, path in paths.items()} == expected
    assert (release / source_directory / "client.json").read_bytes() == (
        b"changed-after-validation"
    )


def test_rollback_accepts_verified_missing_container(monkeypatch, tmp_path):
    live, release, paths, original, _staged, image = _protected_release(
        tmp_path, live_state="staged"
    )
    monkeypatch.setattr(MODULE, "LIVE", live)
    monkeypatch.setattr(MODULE, "FILES", paths)
    monkeypatch.setattr(MODULE, "BACKUP_ROOT", release.parent)
    monkeypatch.setattr(MODULE, "_ensure_rollback_image", lambda *_args: None)
    def docker_output(command, **_kwargs):
        if command[:3] == ["docker", "inspect", "wtyj-mermaid"]:
            raise subprocess.CalledProcessError(1, command)
        assert command == ["docker", "ps", "-a", "--format", "{{.Names}}"]
        return "wtyj-unboks\nwtyj-ali-car-rental\n"
    monkeypatch.setattr(MODULE.subprocess, "check_output", docker_output)
    monkeypatch.setattr(sys, "argv", [
        "prepare_mermaid_reservation_release.py",
        "--source", str(tmp_path), "--release", str(release),
        "--image", image, "--rollback", "--service-stopped",
    ])

    MODULE.main()
    assert {name: path.read_bytes() for name, path in paths.items()} == original


def test_missing_container_inventory_error_fails_closed(monkeypatch, tmp_path):
    live, release, paths, _original, staged, image = _protected_release(
        tmp_path, live_state="staged"
    )
    monkeypatch.setattr(MODULE, "LIVE", live)
    monkeypatch.setattr(MODULE, "FILES", paths)
    monkeypatch.setattr(MODULE, "BACKUP_ROOT", release.parent)
    monkeypatch.setattr(
        MODULE.subprocess,
        "check_output",
        lambda command, **_kwargs: (_ for _ in ()).throw(
            subprocess.CalledProcessError(1, command)
        ),
    )
    monkeypatch.setattr(sys, "argv", [
        "prepare_mermaid_reservation_release.py",
        "--source", str(tmp_path), "--release", str(release),
        "--image", image, "--rollback", "--service-stopped",
    ])

    with pytest.raises(subprocess.CalledProcessError):
        MODULE.main()
    assert {name: path.read_bytes() for name, path in paths.items()} == staged


def test_apply_refuses_verified_missing_container(monkeypatch, tmp_path):
    live, release, paths, original, _staged, image = _protected_release(
        tmp_path, live_state="original"
    )
    monkeypatch.setattr(MODULE, "LIVE", live)
    monkeypatch.setattr(MODULE, "FILES", paths)
    monkeypatch.setattr(MODULE, "BACKUP_ROOT", release.parent)
    def docker_output(command, **_kwargs):
        if command[:3] == ["docker", "inspect", "wtyj-mermaid"]:
            raise subprocess.CalledProcessError(1, command)
        assert command == ["docker", "ps", "-a", "--format", "{{.Names}}"]
        return "wtyj-unboks\n"
    monkeypatch.setattr(MODULE.subprocess, "check_output", docker_output)
    monkeypatch.setattr(sys, "argv", [
        "prepare_mermaid_reservation_release.py",
        "--source", str(tmp_path), "--release", str(release),
        "--image", image, "--apply", "--service-stopped",
    ])

    with pytest.raises(RuntimeError, match="absent before release apply"):
        MODULE.main()
    assert {name: path.read_bytes() for name, path in paths.items()} == original
