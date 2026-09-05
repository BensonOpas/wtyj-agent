import os
from pathlib import Path
import subprocess

import pytest


REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPTS = REPO_ROOT / "wtyj/scripts"


def _script(name: str) -> str:
    return (SCRIPTS / name).read_text()


def test_generic_queue_cannot_target_or_health_check_mermaid():
    script = _script("process_deploy_queue.sh")

    default_clients = script.split('WTYJ_DEPLOY_CLIENTS:-', 1)[1].split('}"', 1)[0]
    assert "mermaid" not in default_clients.split()
    assert "mermaid)" in script
    assert "Refusing generic deployment of protected Mermaid tenant" in script
    assert 'mermaid) HEALTH_PORTS=' not in script
    assert "protected Mermaid container found in shared deployment target" in script
    assert "wtyj-agent:tracy-*|wtyj-agent:mermaid-*" in script
    assert script.index("wtyj-agent:tracy-*") < script.index("wtyj-agent|wtyj-agent:*")


@pytest.mark.parametrize(
    "targets,expected",
    [
        ("adamus mermaid unboks", "protected Mermaid tenant"),
        ("adamus fake/../mermaid unboks", "unknown shared deployment target"),
    ],
)
def test_generic_queue_rejects_unsafe_override_before_any_deploy_work(
    tmp_path, targets, expected,
):
    environment = os.environ.copy()
    environment.update({
        "WTYJ_DEPLOY_CLIENTS": targets,
        "WTYJ_SOURCE_ROOT": str(tmp_path / "source-does-not-exist"),
        "DEPLOY_QUEUE_PATH": str(tmp_path / "queue.json"),
        "WTYJ_DEPLOY_LOCK_PATH": str(tmp_path / "deploy.lock"),
    })

    completed = subprocess.run(
        ["bash", str(SCRIPTS / "process_deploy_queue.sh")],
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 1
    assert expected in completed.stdout
    assert not (tmp_path / "deploy.lock").exists()
    assert not (tmp_path / "queue.json").exists()


def test_generic_rollback_cannot_retag_or_recreate_mermaid():
    script = _script("rollback.sh")

    all_targets = script.split('DIRS="', 1)[1].split('"', 1)[0]
    assert "/root/clients/mermaid" not in all_targets.split()
    assert "mermaid)" in script
    assert "8102" not in script
    assert "protected Mermaid container found in shared target" in script
    assert "wtyj-agent:tracy-*|wtyj-agent:mermaid-*" in script
    assert script.index("wtyj-agent:tracy-*") < script.index("wtyj-agent|wtyj-agent:*")


@pytest.mark.parametrize("target", ["mermaid", "fake/../mermaid", "./mermaid"])
def test_generic_rollback_rejects_direct_and_indirect_mermaid_targets(
    tmp_path, target,
):
    environment = os.environ.copy()
    environment["WTYJ_DEPLOY_LOCK_PATH"] = str(tmp_path / "deploy.lock")

    completed = subprocess.run(
        ["bash", str(SCRIPTS / "rollback.sh"), target],
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 1
    assert "ROLLBACK ERROR" in completed.stdout
    assert not (tmp_path / "deploy.lock").exists()


def test_generic_and_scoped_deploys_share_one_operation_lock():
    generic = _script("process_deploy_queue.sh")
    rollback = _script("rollback.sh")
    scoped = _script("deploy_mermaid_release.sh")
    workflow = (REPO_ROOT / ".github/workflows/ci-deploy.yml").read_text()

    declaration = 'WTYJ_DEPLOY_LOCK_PATH:-/root/wtyj-production-deploy.lock'
    assert declaration in generic
    assert declaration in rollback
    assert declaration in scoped
    assert "WTYJ_DEPLOY_LOCK_PATH=/root/wtyj-production-deploy.lock" in workflow
    assert "flock -n 9" in generic
    assert "flock -n 9" in rollback
    assert "flock -n 9" in scoped
    assert "flock -n 9" in workflow
    assert "export WTYJ_DEPLOY_LOCK_HELD=1" in workflow
    assert generic.index("flock -n 9") < generic.index("claim_for_deploy")
    assert workflow.index("flock -n 9") < workflow.index("docker tag")


def test_scoped_release_addresses_only_mermaid_agent_service():
    script = _script("deploy_mermaid_release.sh")

    assert "docker compose down" not in script
    assert 'docker compose stop --timeout "$STOP_TIMEOUT" agent' in script
    assert "docker compose up -d --no-deps --force-recreate agent" in script
    assert "docker tag" not in script
    assert "wtyj-agent:latest" not in script


def test_portable_mermaid_compose_requires_an_explicit_immutable_image():
    compose = (REPO_ROOT / "clients/mermaid/docker-compose.yml").read_text()

    assert "image: wtyj-agent\n" not in compose
    assert "image: ${MERMAID_IMAGE:?MERMAID_IMAGE must pin an immutable Tracy revision}" in compose


def test_scoped_release_requires_every_live_peer_identity_to_stay_equal():
    script = _script("deploy_mermaid_release.sh")

    assert "docker ps --format '{{.Names}}'" in script
    assert '[ "$container" = "wtyj-mermaid" ] && continue' in script
    assert "LC_ALL=C sort" in script
    assert "PEER_CONTAINERS=" not in script
    assert "PEERS_BEFORE=$(snapshot_peers)" in script
    assert "PEERS_AFTER=$(snapshot_peers)" in script
    assert 'if [ "$PEERS_AFTER" != "$PEERS_BEFORE" ]' in script
    assert '"$PEER_COUNT"' in script


def test_scoped_release_never_restores_live_database_on_failure():
    script = _script("deploy_mermaid_release.sh")
    helper = _script("prepare_mermaid_reservation_release.py")

    assert "--rollback" in script
    assert "source_payloads = rollback_payloads if args.rollback else staged_payloads" in helper
    assert 'release / "rollback", manifest["rollback_hashes"]' in helper
    rollback_block = helper.split("if args.apply or args.rollback:", 1)[1]
    assert "state_registry.db" not in rollback_block
    assert "_database_backup(release)" in rollback_block
    assert '"response_policy.json": LIVE / "config/response_policy.json"' in helper
    assert 'release / "staged/response_policy.json"' in helper


def test_scoped_release_rollback_recreates_the_exact_pre_release_image():
    script = _script("deploy_mermaid_release.sh")
    helper = _script("prepare_mermaid_reservation_release.py")

    assert 'manifest.get("previous_image_id")' in helper
    assert 'manifest.get("rollback_image")' in helper
    assert '["docker", "tag", image_id, rollback_image]' in helper
    assert '["docker", "image", "inspect", "--format", "{{.Id}}", rollback_image]' in helper
    assert '_compose_with_image(\n        originals["docker-compose.yml"], rollback_image' in helper
    assert '["previous_image_id"]' in script
    assert '["rollback_image"]' in script
    assert 'RESTORED_IMAGE_ID=$(docker inspect --format \'{{.Image}}\' wtyj-mermaid)' in script
    assert 'RESTORED_IMAGE_TAG=$(docker inspect --format \'{{.Config.Image}}\' wtyj-mermaid)' in script
    assert '[ "$RESTORED_IMAGE_ID" != "$PREVIOUS_IMAGE_ID" ]' in script
    assert '[ "$RESTORED_IMAGE_TAG" != "$ROLLBACK_IMAGE" ]' in script
