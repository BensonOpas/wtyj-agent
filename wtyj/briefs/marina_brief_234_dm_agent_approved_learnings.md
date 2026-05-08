# BRIEF 234 — Marina-uses-approved-learnings on IG/FB DM path
**Status:** Draft | **Files:** `wtyj/agents/social/dm_agent.py`, `wtyj/tests/social/test_234_dm_approved_learnings.py` | **Depends on:** Brief 219 (`get_approved_learnings_for_prompt` helper + `features.approved_learnings_in_prompt` flag + `_build_approved_answers_block` pattern in `marina_agent.py`) | **Blocks:** parity for unboks IG/FB DMs with the email/WhatsApp paths that already inject approved learnings into Marina's prompt

## Context

Brief 219 wired `state_registry.get_approved_learnings_for_prompt(channel)` into `marina_agent.process_message()`'s system prompt at `marina_agent.py:578`, gated on `client.json::features.approved_learnings_in_prompt`. The flag is currently `true` for unboks. Marina reads operator-curated approved learnings on:

- **email path** ✓ (channel `"email"`)
- **WhatsApp path** ✓ (channel `"whatsapp"`, via `webhook_server._flush_buffer` → `marina_agent.process_message`)
- **Instagram DM path** ✗ — `dm_agent.handle_incoming_dm` makes its own Claude call via `_build_dm_system_prompt` (dm_agent.py:18-148) with NO learnings injection
- **Facebook DM path** ✗ — same module, same gap

`escalation_learnings` rows from `dm_agent.py:225` get saved with `channel="instagram_dm"` or `channel="facebook_dm"` (the value passed through `create_pending_notification`), and `get_approved_learnings_for_prompt` filters by exact channel match — so calling the helper with `"instagram_dm"` returns ONLY Instagram learnings. Channel pools stay isolated, exactly what we want.

This brief mirrors Brief 219's pattern in `dm_agent._build_dm_system_prompt`: build an `APPROVED ANSWERS` block when the flag is on AND there's at least one matching row; inject between the intro/qa_role line and the services/FAQ blocks; collapse cleanly to empty when off.

## Why This Approach

**Chosen:** add a module-private `_build_dm_approved_answers_block(channel)` in `dm_agent.py` that mirrors `marina_agent._build_approved_answers_block(channel)` line-for-line. Inject the block into BOTH branches of `_build_dm_system_prompt` (master_prompt and fallback) so behavior is identical regardless of whether the tenant set `agent_persona.freeform_notes`.

**Why a separate helper instead of importing marina's.** `dm_agent` was deliberately kept as its own Claude call (Brief 131) — it doesn't go through `marina_agent.process_message`. Cross-importing a private helper from `marina_agent` to use here would create a hidden dependency between two modules that have stayed independent by design. Copying the 30-line helper is the honest cost. If a third channel later needs the same block, extract to `shared/` then.

**Why both branches need the injection.** The master_prompt branch (when `agent_persona.freeform_notes` is set) and the fallback branch (when it isn't) build their parts list separately. Missing the injection in either branch creates a per-tenant inconsistency where Marina reads learnings only when the tenant has freeform_notes set, OR vice versa. Same flag, same behavior, same code path on both sides.

**Why between intro/qa_role and services_block.** Visually parallels Brief 219's placement after `_customer_file_block` and before `writing_style_block` — the learnings provide context BEFORE structural data (services, FAQ) so Claude reads them as authoritative operator coaching, not as one more reference table. No claim that the order significantly changes Claude's behavior; the parallelism is for code-readability symmetry with the email/WA path.

**Channel value passed verbatim.** dm_agent's `channel` parameter at line 152 is the same string saved into `escalation_learnings.channel` when an operator answers a DM escalation — `"instagram_dm"` or `"facebook_dm"`. Same string flows back into the helper here, so a learning answered on Instagram is read back on Instagram (not bleeding into Facebook). Already enforced by Brief 219's exact-channel filter.

**Tradeoff: token budget.** A tenant with hundreds of approved learnings would see Claude's prompt grow proportionally. Brief 219's `limit=20` cap applies here too — keeps per-call token cost bounded. Same tradeoff Marina already lives with.

**Rejected:** lazy injection via shared helper that takes a callable. Pattern-matching for two callers that diverged historically; YAGNI for the third caller until it exists.

**Rejected:** unified channel name pool (e.g., `"dm"` instead of separating Instagram and Facebook). Operators answer in channel-specific contexts — a Spanish-speaking Facebook customer's answer might not be appropriate for an English Instagram audience. Per-channel isolation is correct.

## Instructions

### 1. Add `_build_dm_approved_answers_block` near top of `dm_agent.py`

Insert immediately AFTER the existing `_REPLY_WINDOW_SECONDS = 3600` constant (around line 15) and BEFORE the `_build_dm_system_prompt` function at line 18:

```python
def _build_dm_approved_answers_block(channel: str) -> str:
    """Brief 234: mirror of marina_agent._build_approved_answers_block for
    the IG/FB DM path. Returns an APPROVED ANSWERS prompt block listing
    recent operator-curated learnings for this channel, or '' when the
    tenant hasn't opted in or no learnings match.

    When non-empty the return starts with '\\n\\n' so the joiner in
    `_build_dm_system_prompt` keeps a clean blank-line break before the
    block; when empty it's omitted from the parts list entirely. Tenant
    opt-in via client.json::features.approved_learnings_in_prompt
    (default false). Channel filter is exact-string match so Instagram
    and Facebook learning pools stay isolated."""
    features = config_loader.get_raw().get("features", {}) or {}
    if not features.get("approved_learnings_in_prompt"):
        return ""
    try:
        rows = state_registry.get_approved_learnings_for_prompt(channel, limit=20)
    except Exception:
        return ""
    if not rows:
        return ""
    pairs = []
    for r in rows:
        q = (r.get("question") or "").strip()
        a = (r.get("answer") or "").strip()
        if not a:
            continue
        if q:
            pairs.append(f"Q: {q}\nA: {a}")
        else:
            pairs.append(f"A: {a}")
    if not pairs:
        return ""
    return (
        "APPROVED ANSWERS (operator-curated knowledge):\n"
        "The team has previously answered similar customer questions on this "
        "channel. Use these as authoritative context, they reflect how the "
        "human team wants you to handle these situations going forward. Match "
        "the spirit; do not copy verbatim if the customer phrasing differs.\n\n"
        + "\n\n".join(pairs)
    )
```

(Note: returns the block WITHOUT a leading `\n\n` — the parts list is joined with `"\n\n".join(parts)` already in `_build_dm_system_prompt`, so the joiner handles spacing. Marina's helper returns leading `\n\n` because its caller uses an f-string with literal newlines. The two helpers differ ONLY in this leading-newline detail to match each caller's join idiom.)

### 2. Wire into BOTH branches of `_build_dm_system_prompt`

In the function body, compute the block ONCE at the top (after the `agent_name`/`company_name` resolution, around line 47) so both branches use it. Add this line after `output_rule = ...` (around line 86):

```python
    approved_answers_block = _build_dm_approved_answers_block(channel)
```

**Master prompt branch** (lines 88-99): change

```python
        parts = [intro, qa_role_short, master_prompt, services_block, faq_block]
        if booking_flow:
            parts.append(booking_redirect_block)
        parts.extend([language_block, emoji_block, output_rule])
        return "\n\n".join(parts)
```

to

```python
        parts = [intro, qa_role_short, master_prompt]
        if approved_answers_block:
            parts.append(approved_answers_block)
        parts.extend([services_block, faq_block])
        if booking_flow:
            parts.append(booking_redirect_block)
        parts.extend([language_block, emoji_block, output_rule])
        return "\n\n".join(parts)
```

**Fallback branch** (lines 113-124 — the final return statement of the function). The actual existing order in source is:

```python
    return (
        intro + "\n\n"
        + qa_role_full + "\n\n"
        + services_block + "\n\n"
        + faq_block + "\n\n"
        + writing_style_block + "\n\n"
        + booking_redirect_block + "\n\n"
        + language_block + "\n\n"
        + avoid_block + "\n\n"
        + emoji_block + "\n\n"
        + output_rule
    )
```

Replace with a parts-list that PRESERVES this exact order, with the new approved-answers block inserted between `qa_role_full` and `services_block` (parallels the master_prompt branch placement: between the role intro and the structural data blocks):

```python
    fallback_parts = [intro, qa_role_full]
    if approved_answers_block:
        fallback_parts.append(approved_answers_block)
    fallback_parts.extend([
        services_block, faq_block, writing_style_block,
        booking_redirect_block, language_block, avoid_block,
        emoji_block, output_rule,
    ])
    return "\n\n".join(fallback_parts)
```

For the NO-BLOCK case (flag off), this is byte-equivalent to the original concatenation: `"\n\n".join([intro, qa_role_full, services_block, faq_block, writing_style_block, booking_redirect_block, language_block, avoid_block, emoji_block, output_rule])` produces the same string as the original `+ "\n\n" +` chain. Verify by re-reading lines 113-124 and confirming the order matches.

## Tests

Place at `wtyj/tests/social/test_234_dm_approved_learnings.py`.

```python
"""Tests for Brief 234 — APPROVED ANSWERS injection on IG/FB DM path."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")

from unittest.mock import patch

from agents.social.dm_agent import _build_dm_approved_answers_block, _build_dm_system_prompt


def test_block_empty_when_flag_off():
    """Brief 234: with features.approved_learnings_in_prompt unset/False,
    the helper returns empty string regardless of stored learnings."""
    with patch("agents.social.dm_agent.config_loader.get_raw",
               return_value={"features": {"approved_learnings_in_prompt": False}}):
        result = _build_dm_approved_answers_block("instagram_dm")
    assert result == ""


def test_block_empty_when_flag_on_but_no_learnings():
    """Brief 234: flag on but no matching rows → still empty."""
    with patch("agents.social.dm_agent.config_loader.get_raw",
               return_value={"features": {"approved_learnings_in_prompt": True}}), \
         patch("agents.social.dm_agent.state_registry.get_approved_learnings_for_prompt",
               return_value=[]):
        result = _build_dm_approved_answers_block("instagram_dm")
    assert result == ""


def test_block_renders_qa_pairs_when_present():
    """Brief 234: flag on + learnings → block contains 'APPROVED ANSWERS'
    header and each Q/A pair."""
    rows = [
        {"question": "Do you ship outside Curaçao?",
         "answer": "Not yet — local pickup or delivery only."},
        {"question": "Refund policy?",
         "answer": "Within 7 days of purchase, full refund."},
    ]
    with patch("agents.social.dm_agent.config_loader.get_raw",
               return_value={"features": {"approved_learnings_in_prompt": True}}), \
         patch("agents.social.dm_agent.state_registry.get_approved_learnings_for_prompt",
               return_value=rows):
        result = _build_dm_approved_answers_block("instagram_dm")
    assert "APPROVED ANSWERS" in result
    assert "Do you ship outside Curaçao?" in result
    assert "Not yet" in result
    assert "Refund policy?" in result
    assert "Within 7 days" in result


def test_block_skips_rows_with_empty_answer():
    """Brief 234: a row with an empty answer is dropped — defensive
    guard against partial data."""
    rows = [
        {"question": "real q", "answer": "real a"},
        {"question": "also real", "answer": ""},
    ]
    with patch("agents.social.dm_agent.config_loader.get_raw",
               return_value={"features": {"approved_learnings_in_prompt": True}}), \
         patch("agents.social.dm_agent.state_registry.get_approved_learnings_for_prompt",
               return_value=rows):
        result = _build_dm_approved_answers_block("instagram_dm")
    assert "real q" in result
    assert "real a" in result
    assert "also real" not in result


def test_helper_failure_returns_empty_string():
    """Brief 234: state_registry exception is swallowed; helper returns
    empty string. Never raises into _build_dm_system_prompt's call chain."""
    with patch("agents.social.dm_agent.config_loader.get_raw",
               return_value={"features": {"approved_learnings_in_prompt": True}}), \
         patch("agents.social.dm_agent.state_registry.get_approved_learnings_for_prompt",
               side_effect=Exception("db down")):
        result = _build_dm_approved_answers_block("instagram_dm")
    assert result == ""


def test_system_prompt_includes_learnings_when_flag_on(monkeypatch):
    """Brief 234: end-to-end — _build_dm_system_prompt's full output
    contains the APPROVED ANSWERS block when the flag is on AND
    learnings exist. Tests the master_prompt branch (freeform_notes set)."""
    rows = [{"question": "test234 question?", "answer": "test234 answer."}]
    fake_raw = {
        "features": {"approved_learnings_in_prompt": True, "booking_flow": False},
        "agent_persona": {"freeform_notes": "MASTER PROMPT BLOCK"},
        "terminology": {},
    }
    monkeypatch.setattr("agents.social.dm_agent.config_loader.get_raw",
                        lambda: fake_raw)
    monkeypatch.setattr("agents.social.dm_agent.config_loader.get_business",
                        lambda: {"name": "Test", "agent_name": "Marina"})
    monkeypatch.setattr("agents.social.dm_agent.config_loader.get_common_sense_knowledge",
                        lambda: {})
    monkeypatch.setattr("agents.social.dm_agent.config_loader.get_services",
                        lambda: {})
    monkeypatch.setattr("agents.social.dm_agent.config_loader.get_faq",
                        lambda: {})
    monkeypatch.setattr("agents.social.dm_agent.state_registry.get_approved_learnings_for_prompt",
                        lambda channel, limit=20: rows)
    prompt = _build_dm_system_prompt("instagram_dm")
    assert "APPROVED ANSWERS" in prompt
    assert "test234 question?" in prompt
    assert "test234 answer." in prompt


def test_system_prompt_omits_block_when_flag_off(monkeypatch):
    """Brief 234: with the flag off, _build_dm_system_prompt's output has
    NO 'APPROVED ANSWERS' header — verifies the if-block prepend is gated."""
    fake_raw = {
        "features": {"approved_learnings_in_prompt": False, "booking_flow": False},
        "agent_persona": {"freeform_notes": "MASTER PROMPT BLOCK"},
        "terminology": {},
    }
    monkeypatch.setattr("agents.social.dm_agent.config_loader.get_raw",
                        lambda: fake_raw)
    monkeypatch.setattr("agents.social.dm_agent.config_loader.get_business",
                        lambda: {"name": "Test", "agent_name": "Marina"})
    monkeypatch.setattr("agents.social.dm_agent.config_loader.get_common_sense_knowledge",
                        lambda: {})
    monkeypatch.setattr("agents.social.dm_agent.config_loader.get_services",
                        lambda: {})
    monkeypatch.setattr("agents.social.dm_agent.config_loader.get_faq",
                        lambda: {})
    prompt = _build_dm_system_prompt("instagram_dm")
    assert "APPROVED ANSWERS" not in prompt
```

## Success Condition

After deploy, an unboks DM (Instagram or Facebook) inbound triggers a `_build_dm_system_prompt` call that includes the `APPROVED ANSWERS` block whenever there are matching `escalation_learnings` rows for that channel. unboks's `features.approved_learnings_in_prompt` flag is already true, so the block fires immediately on next DM. Other tenants stay default-OFF. New regression tests cover flag-off, flag-on-no-rows, flag-on-with-rows, empty-answer drop, exception swallow, and end-to-end system-prompt assembly. Full suite stays at 1088 + 7 new = 1095 passing / 0 failures.

## Rollback

`git revert <commit>`. Removes the helper + the parts-list rewires; the IG/FB DM path returns to the no-injection state. No data migration; learnings table is untouched.
