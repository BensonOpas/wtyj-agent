# tests/social/test_109_brand_training.py
# Brief 109 — Brand training backend tests

import os
import sys
import pytest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

os.environ.setdefault("DASHBOARD_PASSWORD", "testpass")

from shared import state_registry


@pytest.fixture(autouse=True)
def _use_temp_db(tmp_path, monkeypatch):
    db_path = str(tmp_path / "test.db")
    monkeypatch.setattr(state_registry, "DB_PATH", db_path)


# --- Training Examples ---

def test_training_example_crud():
    eid = state_registry.save_training_example("Great sunset post #curaçao", platform="instagram")
    examples = state_registry.get_training_examples()
    assert len(examples) == 1
    assert examples[0]["id"] == eid
    assert examples[0]["caption_text"] == "Great sunset post #curaçao"
    assert examples[0]["platform"] == "instagram"
    # Delete
    state_registry.delete_training_example(eid)
    assert len(state_registry.get_training_examples()) == 0


def test_training_example_with_image():
    eid = state_registry.save_training_example("Caption", image_path="/tmp/test.jpg")
    ex = state_registry.get_training_examples()[0]
    assert ex["image_path"] == "/tmp/test.jpg"
    deleted_path = state_registry.delete_training_example(eid)
    assert deleted_path == "/tmp/test.jpg"


# --- Brand Profile ---

def test_brand_rule_crud():
    rid = state_registry.save_brand_rule("voice_rules", "Always use short sentences", source="manual")
    rules = state_registry.get_brand_rules()
    assert len(rules) == 1
    assert rules[0]["rule"] == "Always use short sentences"
    assert rules[0]["source"] == "manual"
    # Update
    ok = state_registry.update_brand_rule(rid, rule="Use very short sentences")
    assert ok is True
    rules = state_registry.get_brand_rules()
    assert rules[0]["rule"] == "Use very short sentences"
    # Delete (deactivate)
    ok = state_registry.delete_brand_rule(rid)
    assert ok is True
    assert len(state_registry.get_brand_rules()) == 0


def test_brand_rules_by_category():
    state_registry.save_brand_rule("voice_rules", "Rule A")
    state_registry.save_brand_rule("boundaries", "Rule B")
    state_registry.save_brand_rule("voice_rules", "Rule C")
    voice = state_registry.get_brand_rules(category="voice_rules")
    assert len(voice) == 2
    bounds = state_registry.get_brand_rules(category="boundaries")
    assert len(bounds) == 1


def test_replace_brand_rules_preserves_manual():
    # Add manual rule
    state_registry.save_brand_rule("voice_rules", "Manual rule", source="manual")
    # Add analysis rules
    state_registry.save_brand_rule("voice_rules", "Old analysis rule 1", source="analysis")
    state_registry.save_brand_rule("voice_rules", "Old analysis rule 2", source="analysis")
    assert len(state_registry.get_brand_rules(category="voice_rules")) == 3
    # Replace analysis rules
    new_ids = state_registry.replace_brand_rules("voice_rules", ["New rule 1", "New rule 2"])
    assert len(new_ids) == 2
    rules = state_registry.get_brand_rules(category="voice_rules")
    # Should have: 1 manual + 2 new analysis = 3
    assert len(rules) == 3
    rule_texts = [r["rule"] for r in rules]
    assert "Manual rule" in rule_texts
    assert "New rule 1" in rule_texts
    assert "New rule 2" in rule_texts
    assert "Old analysis rule 1" not in rule_texts


# --- Prompt Injection ---

def test_brand_profile_injected_into_prompt():
    state_registry.save_brand_rule("voice_rules", "Use short sentences")
    state_registry.save_brand_rule("boundaries", "Never mention competitors")
    from agents.social.content_agent import _build_system_prompt
    prompt = _build_system_prompt(3)
    assert "BRAND PROFILE" in prompt
    assert "Use short sentences" in prompt
    assert "Never mention competitors" in prompt


def test_brand_profile_absent_when_empty():
    from agents.social.content_agent import _build_system_prompt
    prompt = _build_system_prompt(3)
    assert "BRAND PROFILE" not in prompt


# --- API Endpoint ---

from fastapi.testclient import TestClient
from agents.social.webhook_server import app

_client = TestClient(app)


def _login():
    resp = _client.post("/dashboard/api/login", json={"password": "testpass"})
    return resp.json()["token"]


def test_api_training_example_upload():
    token = _login()
    resp = _client.post(
        "/dashboard/api/training/examples",
        headers={"Authorization": f"Bearer {token}"},
        data={"caption_text": "Beautiful sunset over the water", "platform": "instagram"},
    )
    assert resp.status_code == 200
    assert resp.json()["ok"] is True
    assert resp.json()["id"] > 0
    # Verify it's listed
    list_resp = _client.get(
        "/dashboard/api/training/examples",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert len(list_resp.json()) == 1
    assert list_resp.json()[0]["caption_text"] == "Beautiful sunset over the water"
