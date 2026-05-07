# test_219_marina_uses_learnings.py
# Brief 219: Marina injects an APPROVED ANSWERS prompt block from
# escalation_learnings (Brief 215 storage). Behind feature flag
# client.json::features.approved_learnings_in_prompt (default false).
# When the flag is off OR no rows match (channel/status/ai_may_use), the
# block is omitted entirely.
#
# Helper-level tests (1-4) use a synthetic channel "test_219_chan" so
# pre-existing rows from other tests in the shared SQLite don't pollute
# row counts. Integration tests (5-6) use "whatsapp" because the prompt
# branches by channel — those tests only check substring presence of
# their own seeded answer text.

import os

os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")

from unittest.mock import patch
from agents.marina import marina_agent
from shared import state_registry, config_loader

_TEST_CHANNEL = "test_219_chan"
_TEST_CHANNEL_OTHER = "test_219_chan_other"


def _wipe_219_learnings():
    """Drop test-prefixed escalation_learnings rows so reruns don't accumulate."""
    conn = state_registry._get_conn()
    conn.execute("DELETE FROM escalation_learnings WHERE conversation_id LIKE '219_%'")
    conn.execute(
        "DELETE FROM escalation_learnings WHERE channel IN (?, ?)",
        (_TEST_CHANNEL, _TEST_CHANNEL_OTHER))
    conn.commit()
    conn.close()


# --- Test 1: helper returns [] when no rows exist for this channel
def test_helper_returns_empty_when_no_rows():
    try:
        _wipe_219_learnings()
        rows = state_registry.get_approved_learnings_for_prompt(_TEST_CHANNEL)
        assert rows == []
    finally:
        _wipe_219_learnings()


# --- Test 2: helper filters by channel
def test_helper_filters_by_channel():
    try:
        _wipe_219_learnings()
        state_registry.save_escalation_learning(
            conversation_id="219_chan_a", channel=_TEST_CHANNEL,
            source_question="q1", human_answer="a1")
        state_registry.save_escalation_learning(
            conversation_id="219_chan_b", channel=_TEST_CHANNEL,
            source_question="q2", human_answer="a2")
        state_registry.save_escalation_learning(
            conversation_id="219_chan_c", channel=_TEST_CHANNEL_OTHER,
            source_question="qe", human_answer="ae")

        primary = state_registry.get_approved_learnings_for_prompt(_TEST_CHANNEL)
        other = state_registry.get_approved_learnings_for_prompt(_TEST_CHANNEL_OTHER)
        assert len(primary) == 2
        assert len(other) == 1
        assert all(r["answer"] in ("a1", "a2") for r in primary)
        assert other[0]["answer"] == "ae"
    finally:
        _wipe_219_learnings()


# --- Test 3: helper excludes unapproved + opt-out rows
def test_helper_excludes_unapproved_and_opt_out():
    try:
        _wipe_219_learnings()
        # Suggested status: excluded
        state_registry.save_escalation_learning(
            conversation_id="219_excl_sugg", channel=_TEST_CHANNEL,
            source_question="q", human_answer="suggested",
            status="suggested")
        # Approved but ai_may_use=False: excluded
        state_registry.save_escalation_learning(
            conversation_id="219_excl_optout", channel=_TEST_CHANNEL,
            source_question="q", human_answer="opt-out",
            status="approved", ai_may_use=False)
        # Should be excluded after marking deleted
        sav_id = state_registry.save_escalation_learning(
            conversation_id="219_excl_del", channel=_TEST_CHANNEL,
            source_question="q", human_answer="deleted")
        state_registry.update_escalation_learning_status(sav_id, "deleted")

        rows = state_registry.get_approved_learnings_for_prompt(_TEST_CHANNEL)
        assert rows == [], f"expected empty, got {rows}"

        # Now add one approved + ai_may_use=True row
        state_registry.save_escalation_learning(
            conversation_id="219_incl_ok", channel=_TEST_CHANNEL,
            source_question="q", human_answer="ok answer")
        rows = state_registry.get_approved_learnings_for_prompt(_TEST_CHANNEL)
        assert len(rows) == 1
        assert rows[0]["answer"] == "ok answer"
    finally:
        _wipe_219_learnings()


# --- Test 4: helper respects limit
def test_helper_respects_limit():
    try:
        _wipe_219_learnings()
        for i in range(25):
            state_registry.save_escalation_learning(
                conversation_id=f"219_limit_{i:02d}", channel=_TEST_CHANNEL,
                source_question=f"q{i}", human_answer=f"a{i}")

        five = state_registry.get_approved_learnings_for_prompt(_TEST_CHANNEL, limit=5)
        twenty = state_registry.get_approved_learnings_for_prompt(_TEST_CHANNEL, limit=20)
        assert len(five) == 5
        assert len(twenty) == 20
    finally:
        _wipe_219_learnings()


# --- Test 5: prompt OMITS APPROVED ANSWERS block when feature flag is off
def test_prompt_omits_block_when_feature_flag_off():
    sentinel = "BRIEF_219_FLAG_OFF_SENTINEL_should_not_appear"
    try:
        _wipe_219_learnings()
        # Seed a row that would otherwise show — uses production channel
        # so the helper would surface it if the flag were on.
        state_registry.save_escalation_learning(
            conversation_id="219_flag_off", channel="whatsapp",
            source_question="q", human_answer=sentinel)

        # Default config has features.approved_learnings_in_prompt absent or false
        prompt = marina_agent._build_system_prompt(thread_flags={}, channel="whatsapp")
        assert "APPROVED ANSWERS" not in prompt
        assert sentinel not in prompt
    finally:
        # Specific row cleanup since the channel was "whatsapp" not test channel
        conn = state_registry._get_conn()
        conn.execute(
            "DELETE FROM escalation_learnings WHERE conversation_id = ?",
            ("219_flag_off",))
        conn.commit()
        conn.close()


# --- Test 6: prompt INCLUDES block when flag on with entries; positioning correct
def test_prompt_includes_block_when_flag_on_with_entries():
    original_get_raw = config_loader.get_raw
    sentinel_a = "BRIEF_219_we_close_at_unique_marker_alpha_xyz"
    sentinel_b = "BRIEF_219_small_dogs_only_unique_marker_beta_xyz"

    def patched_get_raw():
        raw = dict(original_get_raw())
        features = dict(raw.get("features", {}) or {})
        features["approved_learnings_in_prompt"] = True
        raw["features"] = features
        return raw

    try:
        # Seed under "whatsapp" channel because _build_system_prompt
        # passes the channel through to the helper.
        conn = state_registry._get_conn()
        conn.execute(
            "DELETE FROM escalation_learnings WHERE conversation_id LIKE '219_flag_on_%'")
        conn.commit()
        conn.close()

        state_registry.save_escalation_learning(
            conversation_id="219_flag_on_1", channel="whatsapp",
            source_question="What time do you close?",
            human_answer=sentinel_a)
        state_registry.save_escalation_learning(
            conversation_id="219_flag_on_2", channel="whatsapp",
            source_question="Do you take dogs?",
            human_answer=sentinel_b)

        with patch.object(config_loader, "get_raw", patched_get_raw):
            prompt = marina_agent._build_system_prompt(thread_flags={}, channel="whatsapp")

        assert "APPROVED ANSWERS" in prompt
        assert sentinel_a in prompt
        assert sentinel_b in prompt
        # Position check: APPROVED ANSWERS must come BEFORE WRITING STYLE
        # (sits in the factual-context zone, not the voice/style zone)
        idx_approved = prompt.index("APPROVED ANSWERS")
        idx_writing = prompt.index("WRITING STYLE")
        assert idx_approved < idx_writing, (
            f"APPROVED ANSWERS at {idx_approved} must come before WRITING STYLE at {idx_writing}"
        )
    finally:
        conn = state_registry._get_conn()
        conn.execute(
            "DELETE FROM escalation_learnings WHERE conversation_id LIKE '219_flag_on_%'")
        conn.commit()
        conn.close()
