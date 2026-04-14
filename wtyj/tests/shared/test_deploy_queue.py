import pytest
from shared import deploy_queue


@pytest.fixture(autouse=True)
def isolated_queue(monkeypatch, tmp_path):
    qpath = str(tmp_path / "deploy_queue.json")
    monkeypatch.setattr(deploy_queue, "QUEUE_PATH", qpath)
    yield qpath


def test_extract_brief_number_from_various_messages():
    assert deploy_queue.extract_brief_number("Brief 196: foo") == 196
    assert deploy_queue.extract_brief_number("brief 12 — bar") == 12
    assert deploy_queue.extract_brief_number("CI: retry health check") is None
    assert deploy_queue.extract_brief_number("Brief: 196") is None  # no digit after Brief word
    assert deploy_queue.extract_brief_number("") is None


def test_enqueue_appends_with_brief_extraction():
    state = deploy_queue.enqueue("abc123", "abc123", "Brief 196: ship queue")
    assert len(state["queued"]) == 1
    assert state["queued"][0]["brief"] == 196
    assert state["queued"][0]["sha"] == "abc123"
    assert state["queued"][0]["subject"] == "Brief 196: ship queue"


def test_enqueue_is_idempotent_on_same_sha():
    deploy_queue.enqueue("abc", "abc", "Brief 1")
    deploy_queue.enqueue("abc", "abc", "Brief 1")
    state = deploy_queue.enqueue("abc", "abc", "Brief 1")
    assert len(state["queued"]) == 1


def test_claim_moves_all_queued_to_in_progress_and_clears_queue():
    deploy_queue.enqueue("a", "a", "Brief 1")
    deploy_queue.enqueue("b", "b", "Brief 2")
    deploy_queue.enqueue("c", "c", "Brief 3")
    claimed = deploy_queue.claim_for_deploy()
    assert claimed["deploy_sha"] == "c"  # latest = freshest main
    assert len(claimed["acknowledged_briefs"]) == 3
    state = deploy_queue.read_state()
    assert state["queued"] == []
    assert state["in_progress"]["deploy_sha"] == "c"
    # Second claim while in_progress is set returns None
    assert deploy_queue.claim_for_deploy() is None


def test_enqueue_during_in_progress_lands_in_fresh_queue():
    """A push that arrives during a deploy must NOT be swept by complete_deploy."""
    deploy_queue.enqueue("a", "a", "Brief 1")
    deploy_queue.claim_for_deploy()  # acknowledges Brief 1
    # New push arrives mid-deploy
    deploy_queue.enqueue("b", "b", "Brief 2")
    state = deploy_queue.read_state()
    assert len(state["queued"]) == 1
    assert state["queued"][0]["sha"] == "b"
    assert len(state["in_progress"]["acknowledged_briefs"]) == 1
    # Complete the in-flight deploy
    deploy_queue.complete_deploy("success", duration_s=87)
    state = deploy_queue.read_state()
    # Brief 1 in history (acknowledged at claim time)
    assert len(state["history"]) == 1
    assert state["history"][0]["sha"] == "a"
    # Brief 2 still in queue (arrived after claim)
    assert len(state["queued"]) == 1
    assert state["queued"][0]["sha"] == "b"
    assert state["in_progress"] is None


def test_complete_writes_per_brief_history_with_shared_timestamp():
    deploy_queue.enqueue("a", "a", "Brief 1: A")
    deploy_queue.enqueue("b", "b", "Brief 2: B")
    deploy_queue.claim_for_deploy()
    deploy_queue.complete_deploy("success", duration_s=87)
    state = deploy_queue.read_state()
    assert state["queued"] == []
    assert state["in_progress"] is None
    assert len(state["history"]) == 2
    assert state["history"][0]["deployed_via_sha"] == "b"
    assert state["history"][1]["deployed_via_sha"] == "b"
    assert state["history"][0]["deployed_at"] == state["history"][1]["deployed_at"]
    assert all(h["status"] == "success" for h in state["history"])
    assert all(h["duration_s"] == 87 for h in state["history"])
