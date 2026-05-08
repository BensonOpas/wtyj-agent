# BRIEF 216 — Your Info / Settings + Your Info Updates
**Status:** Draft | **Files:** `wtyj/shared/config_loader.py`, `wtyj/shared/state_registry.py`, `wtyj/dashboard/api.py`, `wtyj/agents/marina/marina_agent.py`, `wtyj/tests/social/test_216_your_info.py` | **Depends on:** Brief 219 (`_build_*_block` injection precedent in `_build_system_prompt`) | **Blocks:** TASK-021 Sections 4 + 5 — SR's "Your Info" + "Your Info Updates" frontend

## Context

Two halves of SR's product contract Section 4-5:

**Your Info (Section 4):** SR's frontend exposes a Settings page where the operator edits business knowledge — name, contact email, support email, phone, WhatsApp, location, languages, operating days. Today these live in `client.json` and require Benson to SSH into the VPS, edit the file, restart the container. SR wants the operator to edit them from the dashboard. Per Benson's directive (this session): "Path A confirmed — GET/PUT over a whitelisted set of `client.json` fields." Edits land in `client.json`; Marina reads it like she always has.

**Your Info Updates (Section 5):** A separate concept. Temporary or special notes the operator wants Marina to know about — promotions, holiday hours, "we're fully booked Saturday," "new pickup location for the week." Per Benson's earlier conversation: TWO flavors:
- **Permanent** — operator-removed only. Example: "We now offer kid-friendly snorkeling gear." Stays until the operator deletes it.
- **Scheduled** — auto-expires at `end_date`. Example: "Valentine's Day promotion: free dessert for couples Feb 13-14." Marina uses it during the window, ignores it before/after.

Both halves need to land for SR's Settings → Your Info + Your Info Updates pages to work. The frontend will GET/PUT both endpoints, render forms, and display the active updates.

## Why This Approach

**Considered:** ship Your Info Updates only this brief, defer the client.json write-through to a follow-up. Rejected: SR's Settings page needs both panels rendered + savable from day one — partial-shipping leaves the page half-broken. Both are scoped tightly enough to coexist in one brief (whitelist is small, info_updates table is simple).

**Considered:** new `client_settings` table that Marina reads INSTEAD of client.json (so writes don't touch the on-disk file). Rejected: forks the source of truth. Operator edits in dashboard would land in DB; Benson edits via SSH would land in client.json. They'd diverge. Path A's "write through to client.json" keeps client.json the single source of truth — the dashboard becomes a friendlier UI for the same file.

**Considered:** include `services`, `payment`, `faq`, `booking_rules` in the editable whitelist. Rejected: those are nested objects with load-bearing schemas (e.g., `services.{key}.slots[].time`). A bad edit could break Marina's booking flow. Restrict the v1 whitelist to flat business fields with simple validation: name (str), email (str email), support_email (str email), phone (str), whatsapp (str), location (str), languages (list of strings), operating_days (str). Nested-object editing is a future brief with a per-field UI on the frontend side.

**Considered:** allow `info_updates.type` to be free-form. Rejected: SR's spec lists a fixed enum (`general | offer | holiday | hours | pricing | other`). Validate at the endpoint so the column doesn't accumulate noise.

**Chosen:** new `update_business_field(key, value)` helper in config_loader that atomically writes through to client.json (tempfile + rename) and invalidates the module cache so subsequent reads see the new value. Whitelist enforced at the endpoint. New `info_updates` table with the SR-spec'd shape. New helper `get_active_info_updates()` returns rows that are either type='permanent' OR within their `[start_date, end_date]` window. New `_build_info_updates_block(channel)` injects an "ACTIVE BUSINESS UPDATES" prompt block when there are rows; behind the same per-tenant feature flag pattern as Brief 219 (`features.info_updates_in_prompt`, default false for safety) — flip on tenant-by-tenant after eyeball validation.

**Marina prompt placement:** insert the info-updates block immediately AFTER the APPROVED ANSWERS block (same factual-context zone). Both blocks are knowledge Marina should treat as authoritative.

## Instructions

### Step 1: `update_business_field` helper in config_loader

In `wtyj/shared/config_loader.py`, add at the end of the file (after `get_raw`):

```python
import os as _os
import tempfile as _tempfile

# Brief 216: whitelist of business fields the dashboard's Your Info page
# is allowed to edit via PUT /settings/your-info. Restricting to flat
# string + list-of-string fields with simple validation. Nested objects
# (services, payment, faq, booking_rules) require their own per-field
# UIs and stay code-only for now.
_YOUR_INFO_WHITELIST = (
    "name", "email", "support_email", "phone", "whatsapp",
    "location", "languages", "operating_days",
)


def update_business_field(key: str, value) -> bool:
    """Brief 216: write a single business.<key> value through to
    client.json on disk, atomically (tempfile + rename) so a crash
    mid-write can't leave the file truncated. Invalidates the module
    cache so subsequent reads see the new value. Whitelist-enforced at
    the endpoint layer; this helper trusts its caller. Returns True on
    success, False on disk error or whitelist miss."""
    global _cache
    if key not in _YOUR_INFO_WHITELIST:
        return False
    try:
        with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
            current = json.load(f)
    except Exception:
        return False
    biz = dict(current.get("business", {}) or {})
    biz[key] = value
    current["business"] = biz
    # Atomic write: tempfile + rename
    try:
        dir_path = _os.path.dirname(_CONFIG_PATH) or "."
        with _tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", delete=False,
            dir=dir_path, prefix=".client.", suffix=".tmp",
        ) as tf:
            json.dump(current, tf, indent=2, ensure_ascii=False)
            tmp_path = tf.name
        _os.replace(tmp_path, _CONFIG_PATH)
    except Exception:
        return False
    # Invalidate cache so the next get_business() / get_raw() call re-reads.
    _cache = {}
    return True


def your_info_whitelist() -> tuple:
    """Brief 216: expose the whitelist so the endpoint layer can validate
    PUT requests + the GET endpoint can return only the editable fields."""
    return _YOUR_INFO_WHITELIST
```

### Step 2: `info_updates` table + 4 helpers in state_registry

Add the table near the other Brief 216 / Brief 215 / Brief 217 tables (around `wtyj/shared/state_registry.py:330+` — adjacent to `escalation_learnings`):

```python
# Brief 216: per-tenant temporary/permanent business updates that Marina
# injects into her prompt. Two flavors: permanent (no dates → always
# active) and scheduled (start_date + end_date → active only within
# the window). Type enum matches SR's product contract Section 5.
conn.execute(
    "CREATE TABLE IF NOT EXISTS info_updates ("
    "id INTEGER PRIMARY KEY AUTOINCREMENT, "
    "type TEXT NOT NULL DEFAULT 'general', "
    "text TEXT NOT NULL, "
    "active INTEGER NOT NULL DEFAULT 1, "
    "start_date TEXT, "
    "end_date TEXT, "
    "created_at TEXT NOT NULL, "
    "updated_at TEXT NOT NULL"
    ")"
)
```

Four helpers near the `escalation_learnings` helpers (around `state_registry.py:2580+`):

```python
_INFO_UPDATE_TYPES = {"general", "offer", "holiday", "hours", "pricing", "other"}


def info_update_create(text: str, type_: str = "general",
                       active: bool = True,
                       start_date: str = None,
                       end_date: str = None) -> int:
    """Brief 216: insert a new info_update row. Permanent rows omit
    start_date + end_date; scheduled rows include both. Returns row id."""
    if type_ not in _INFO_UPDATE_TYPES:
        type_ = "other"
    now = datetime.now(timezone.utc).isoformat()
    conn = _get_conn()
    cur = conn.execute(
        "INSERT INTO info_updates "
        "(type, text, active, start_date, end_date, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (type_, text, 1 if active else 0, start_date, end_date, now, now))
    row_id = cur.lastrowid
    conn.commit()
    conn.close()
    return row_id


def info_updates_list_all() -> list:
    """Brief 216: return ALL info_updates (active + inactive, in-window
    + out-of-window) for the dashboard's Settings → Your Info Updates
    management list. camelCase keys for SR's frontend."""
    conn = _get_conn()
    rows = conn.execute(
        "SELECT id, type, text, active, start_date, end_date, "
        "created_at, updated_at FROM info_updates "
        "ORDER BY created_at DESC").fetchall()
    conn.close()
    return [{
        "id": r[0], "type": r[1], "text": r[2],
        "active": bool(r[3]),
        "startDate": r[4], "endDate": r[5],
        "createdAt": r[6], "updatedAt": r[7],
    } for r in rows]


def info_update_delete(update_id: int) -> bool:
    """Brief 216: hard-delete an info_update row."""
    conn = _get_conn()
    cur = conn.execute("DELETE FROM info_updates WHERE id = ?", (update_id,))
    deleted = cur.rowcount > 0
    conn.commit()
    conn.close()
    return deleted


def get_active_info_updates() -> list:
    """Brief 216: return currently-active info_updates ready for prompt
    injection. Active iff active=1 AND (no dates OR within [start, end]).
    Returns [{type, text}] newest first. Used by marina_agent's prompt
    builder when the tenant opts in via features.info_updates_in_prompt."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    conn = _get_conn()
    rows = conn.execute(
        "SELECT type, text, start_date, end_date FROM info_updates "
        "WHERE active = 1 ORDER BY created_at DESC").fetchall()
    conn.close()
    out = []
    for type_, text, start_date, end_date in rows:
        # Permanent: no start AND no end
        if not start_date and not end_date:
            out.append({"type": type_, "text": text})
            continue
        # Scheduled: include only if today is within the window.
        # Half-open windows allowed (one of start/end set, the other
        # null) for "active from X" or "active until Y" semantics.
        if start_date and today < start_date:
            continue
        if end_date and today > end_date:
            continue
        out.append({"type": type_, "text": text})
    return out
```

### Step 3: 4 dashboard endpoints in api.py

Add a new section near the Brief 217 alert-settings endpoints (around `wtyj/dashboard/api.py:760+` where `/settings/escalation-alerts` lives):

```python
# ── Brief 216: Your Info ──────────────────────────────────────────────────────

@router.get("/settings/your-info", dependencies=[Depends(_check_auth)])
async def get_your_info():
    """Brief 216: return only the whitelisted business fields the
    dashboard's Your Info page is allowed to edit."""
    biz = config_loader.get_business() or {}
    whitelist = config_loader.your_info_whitelist()
    return {k: biz.get(k) for k in whitelist}


class YourInfoUpdate(BaseModel):
    name: str | None = None
    email: str | None = None
    support_email: str | None = None
    phone: str | None = None
    whatsapp: str | None = None
    location: str | None = None
    languages: list[str] | None = None
    operating_days: str | None = None


@router.put("/settings/your-info", dependencies=[Depends(_check_auth)])
async def put_your_info(req: YourInfoUpdate):
    """Brief 216: write through to client.json. Only fields explicitly
    set in the request body get updated; missing/None fields are
    untouched."""
    payload = req.model_dump(exclude_none=True)
    if not payload:
        raise HTTPException(status_code=400, detail="no editable fields supplied")
    failed = []
    for key, value in payload.items():
        ok = config_loader.update_business_field(key, value)
        if not ok:
            failed.append(key)
    if failed:
        raise HTTPException(status_code=500,
                            detail=f"failed to update: {', '.join(failed)}")
    biz = config_loader.get_business() or {}
    whitelist = config_loader.your_info_whitelist()
    return {k: biz.get(k) for k in whitelist}


# ── Brief 216: Your Info Updates ──────────────────────────────────────────────

class InfoUpdateCreate(BaseModel):
    text: str
    type: str = "general"
    active: bool = True
    startDate: str | None = None
    endDate: str | None = None


@router.get("/settings/info-updates", dependencies=[Depends(_check_auth)])
async def list_info_updates():
    """Brief 216: list ALL info_updates rows (active + inactive)
    for the dashboard's Your Info Updates management list."""
    return {"updates": state_registry.info_updates_list_all()}


@router.post("/settings/info-updates", dependencies=[Depends(_check_auth)])
async def create_info_update(req: InfoUpdateCreate):
    """Brief 216: create a permanent (no dates) or scheduled
    (start_date + end_date) info_update row."""
    text = (req.text or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="text required")
    row_id = state_registry.info_update_create(
        text=text, type_=req.type, active=req.active,
        start_date=req.startDate, end_date=req.endDate)
    return {"id": row_id, "ok": True}


@router.delete("/settings/info-updates/{update_id}",
               dependencies=[Depends(_check_auth)])
async def delete_info_update(update_id: int):
    """Brief 216: hard-delete an info_update row."""
    ok = state_registry.info_update_delete(update_id)
    if not ok:
        raise HTTPException(status_code=404, detail="info_update not found")
    return {"ok": True, "id": update_id}
```

### Step 4: Marina prompt block (`_build_info_updates_block`)

In `wtyj/agents/marina/marina_agent.py`, add a new helper directly after `_build_approved_answers_block` (Brief 219 added that around line 297-336). The helper mirrors Brief 219's pattern: feature flag + leading `\n\n` when non-empty.

```python
def _build_info_updates_block() -> str:
    """Brief 216: render an ACTIVE BUSINESS UPDATES prompt block listing
    operator-curated info_updates that are currently active (permanent
    OR within their scheduled window). Returns '' when the tenant
    hasn't opted in or no updates are active. Same leading-`\\n\\n`
    pattern as Brief 219's APPROVED ANSWERS block so the f-string
    spacing collapses cleanly when off."""
    features = config_loader.get_raw().get("features", {}) or {}
    if not features.get("info_updates_in_prompt"):
        return ""
    try:
        from shared import state_registry
        rows = state_registry.get_active_info_updates()
    except Exception:
        return ""
    if not rows:
        return ""
    bullets = []
    for r in rows:
        text = (r.get("text") or "").strip()
        if not text:
            continue
        bullets.append(f"- [{r.get('type', 'general')}] {text}")
    if not bullets:
        return ""
    return (
        "\n\nACTIVE BUSINESS UPDATES (operator-curated, time-sensitive):\n"
        "Use these as authoritative current context. They override older "
        "default information when relevant. Permanent items always apply; "
        "scheduled items apply only during their window (already filtered).\n\n"
        + "\n".join(bullets)
    )
```

Then thread the call into `_build_system_prompt` next to the existing `_approved_answers_block` invocation. Find the line:

```python
_approved_answers_block = _build_approved_answers_block(channel)
```

Add immediately after:

```python
_info_updates_block = _build_info_updates_block()
```

In the f-string template, find:

```python
{_customer_file_block}{_approved_answers_block}
```

Change to:

```python
{_customer_file_block}{_approved_answers_block}{_info_updates_block}
```

Same self-padding pattern: when `_info_updates_block == ""` the f-string output is unchanged from Brief 219; when non-empty the leading `\n\n` slots in cleanly between APPROVED ANSWERS and the writing-style block.

### Step 5: Test file `wtyj/tests/social/test_216_your_info.py`

Mirror the test harness pattern at `wtyj/tests/social/test_211_dashboard_contract_fields.py`. Key challenge: the `update_business_field` write-through MUTATES the real `client.json` on disk. Tests MUST monkeypatch `config_loader._CONFIG_PATH` to a temp file so the test config is isolated.

Required tests (6):

1. **`test_get_your_info_returns_whitelist_only`** — GET `/dashboard/api/settings/your-info`. Response keys are exactly the 8 whitelisted fields (name/email/support_email/phone/whatsapp/location/languages/operating_days). Should NOT include `services`, `payment`, etc.
2. **`test_put_your_info_writes_through_to_disk`** — monkeypatch `config_loader._CONFIG_PATH` to a tmp file containing a minimal client.json. PUT `/.../your-info` with `{"phone": "+12025550100"}`. Read the tmp file: `business.phone` is updated. Read `config_loader.get_business()`: returns the new value (cache invalidated).
3. **`test_put_your_info_rejects_unknown_key_via_pydantic`** — PUT with `{"services": {...}}` (not in whitelist). Pydantic strips unknown fields by default; verify `services` did NOT land in client.json.
4. **`test_info_update_create_permanent_and_scheduled`** — `state_registry.info_update_create(text="permanent x")` returns id, no dates. `info_update_create(text="valentine", start_date="2026-02-13", end_date="2026-02-14")` returns id with dates. `info_updates_list_all()` returns both with correct camelCase keys.
5. **`test_get_active_info_updates_window_filtering`** — seed 4 rows: (a) permanent active, (b) permanent inactive, (c) scheduled in-window (today within), (d) scheduled out-of-window (end_date in past). `get_active_info_updates()` returns only (a) and (c).
6. **`test_marina_prompt_includes_info_updates_when_flag_on`** — seed 1 active info_update. With feature flag on (monkeypatch `config_loader.get_raw`), `marina_agent._build_system_prompt(thread_flags={}, channel="email")` contains "ACTIVE BUSINESS UPDATES" + the seeded text. With flag off, prompt does NOT contain "ACTIVE BUSINESS UPDATES".

Cleanup pattern: each test deletes from `info_updates` rows it created.

## Tests

6 tests covering the write-through helper (whitelist + cache invalidate + atomic write), the storage helpers (create + list + window filter), and the prompt injection (feature flag + content presence). All assertions check real return values, real disk content, and substring presence in the actual rendered prompt.

## Success Condition

`python3 -m pytest wtyj/tests/ -q` passes at **1028 / 0** (1022 baseline + 6 new). Live verification post-deploy: GET `/api/unboks/dashboard/api/settings/your-info` returns 8 keys; PUT changes a value and the next GET shows it; POST `/settings/info-updates` with permanent + scheduled rows persists; GET shows them; flip `features.info_updates_in_prompt=true` in unboks's client.json and inspect Marina's rendered system prompt — the ACTIVE BUSINESS UPDATES block appears with the seeded text.

## Rollback

`git revert <commit>` and redeploy. Schema-leftover-column nothing (the new table just sits unused; rows-if-any are harmless). Endpoints disappear (404), helper functions become dead code, Marina's prompt loses the new block. Frontend Settings → Your Info page degrades to "will be connected by the Unboks team" copy. No data loss; the `info_updates` table can stay or be dropped manually with `DROP TABLE info_updates`.
