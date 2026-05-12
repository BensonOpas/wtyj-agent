# BRIEF 262 — Source of Truth server-side persistence: GET/PUT endpoints + tenant-scoped storage
**Status:** Draft | **Files:** `wtyj/shared/state_registry.py`, `wtyj/dashboard/api.py`, `wtyj/tests/social/test_230_knowledge_files.py` | **Depends on:** Replit #28 (frontend SotBlock UI) | **Blocks:** issue #31 verification, SR frontend Replit task

## Context

Issue #31 P1 (Calvin product request): Replit #28 shipped editable Source-of-Truth (SOT) blocks in the dashboard Settings page (frontend `SotBlock[]` with `id` / `title` / `content?` / `items?` / `subsections?` shape — see `unboks-dashboard-api/artifacts/unboks/src/data/sot.ts:7-13`). Calvin verified the frontend editability works. But the current implementation saves to browser localStorage only (`saveSot()` at `sot.ts:223`), and the UI honestly displays a yellow warning: *"Edits are saved on this device while we wire up sync across browsers and team members."* Calvin's spec: SOT edits must sync across devices/browsers/operators per tenant. Browser-only is not the final state.

Backend audit:
- **`info_updates` table** (Brief 233 era, `state_registry.py:468`) — short additive operator notes injected into Marina's prompt via `_build_info_updates_block` at `marina_agent.py:364`. NOT a fit for SOT: info_updates is short-term overrides; SOT is the structured "what we are / how we work" tenant knowledge.
- **`brand_profile` table** (Brief 244, `state_registry.py:656`) — flat brand-voice rules with `category` / `rule`. Not a fit: SOT is nested (block → subsection → items).
- **`knowledge_files` table** (Brief 230) — uploaded PDFs/DOCX. Different surface.
- **No existing SOT-shaped table.** New persistence is required.

Frontend `SotBlock` shape (verbatim from `sot.ts:1-13`):
```ts
export interface SotSubsection {
  title: string;
  content?: string;
  items?: string[];
}
export interface SotBlock {
  id: string;
  title: string;
  content?: string;
  items?: string[];
  subsections?: SotSubsection[];
}
```

Calvin's preferred endpoint shape (from issue #31): `GET /dashboard/api/source-of-truth` returns `{"blocks": [...]}`; `PUT` accepts the same shape and returns the canonical saved blocks.

## Why This Approach

Three options considered:

1. **New `source_of_truth` table, single row per tenant, `blocks_json TEXT` blob (chosen)** — one row per tenant carrying the entire blocks array as JSON. GET reads the row, returns the parsed blocks. PUT validates the incoming blocks (caps + type checks), serializes, UPSERTs. Atomic save (no partial-update concerns), simple schema, matches the frontend's "load whole array → edit → save whole array" pattern. Validation lives in Python at the API boundary.

2. **New `source_of_truth` table, one row per block** — `(id, block_id, title, content, items_json, subsections_json, position, updated_at)`. More queryable; supports per-block partial updates. Rejected for two reasons: (a) Calvin's frontend PUTs the full blocks array, so per-block granularity isn't surfaced anywhere; (b) PUT would require atomic delete-and-reinsert of all rows, defeating the per-row benefit.

3. **Reuse `info_updates` with a `block_id` column** — squash SOT into the existing operator-notes table by namespacing. Rejected: `info_updates` semantics (short-term additive notes injected into the prompt) are different from SOT (structured tenant facts). Mixing them risks Marina's prompt picking up SOT content via the existing `_build_info_updates_block` injection.

Trade-off accepted: option 1 stores the entire SOT as a single JSON blob, so future per-block queries (e.g., "give me just the pricing block") require parsing the whole blob server-side. This is acceptable because the only consumers Calvin describes are (a) frontend GET/PUT and (b) future Agent/persona/knowledge-pipeline integration that needs the whole SOT anyway. If a per-block query becomes necessary, a future brief can split into one-row-per-block without changing the API shape.

Default seeding: backend returns `{"blocks": []}` when no row exists for the tenant. The frontend's existing `DEFAULT_SOT` constant at `sot.ts:15` is the seed source — on first load, if the GET returns empty blocks, the frontend can PUT its DEFAULT_SOT. This keeps the default-content authoring in one place (frontend) rather than duplicating the constant on the backend (where it would drift from the frontend version).

## Instructions

1. **New table in `wtyj/shared/state_registry.py`** — schema migration block near the other CREATE TABLE statements. Single-row-per-tenant shape:
   ```sql
   CREATE TABLE IF NOT EXISTS source_of_truth (
       id INTEGER PRIMARY KEY,
       blocks_json TEXT NOT NULL DEFAULT '[]',
       updated_at TEXT NOT NULL DEFAULT ''
   )
   ```
   Idempotent via `CREATE TABLE IF NOT EXISTS`. Single row keyed by `id=1` (tenant scoping is implicit — each tenant has its own DB file).

2. **New helpers in `wtyj/shared/state_registry.py`**:
   - `source_of_truth_get() -> list` — SELECT `blocks_json` from row id=1, return parsed list. If no row exists, return `[]`. Defensive: `try/except json.JSONDecodeError: return []` so a corrupted row never crashes the API.
   - `source_of_truth_set(blocks: list) -> list` — UPSERT row id=1 with `blocks_json = json.dumps(blocks, ensure_ascii=False)` and `updated_at = now`. Return the parsed-back blocks for caller verification (proves round-trip clean). Caller is responsible for validation before calling this helper.

3. **Validation helper in `wtyj/dashboard/api.py`** — `_validate_sot_blocks(blocks: list) -> list` enforces Calvin's caps:
   - Max 50 blocks (otherwise HTTP 400 `"Too many blocks (max 50)"`).
   - Per block: `id` and `title` required strings, ≤200 chars each.
   - Per block: `content` optional string, ≤4096 chars.
   - Per block: `items` optional list of strings; max 50 items per list; each item ≤4096 chars.
   - Per block: `subsections` optional list; max 20 per block. Each subsection: `title` required ≤200 chars; `content` optional ≤4096 chars; `items` optional list of strings, same caps as block-level items.
   - Reject any unknown top-level keys per block (`id`/`title`/`content`/`items`/`subsections` allowed; everything else stripped or rejected — STRIP to be lenient).
   - Reject any non-string values in string fields (HTTP 400 `"Field <name> must be a string"`).
   - Return the cleaned blocks list (with stripped unknown keys) so the canonical-saved-blocks response matches the actual saved state.

4. **New endpoints in `wtyj/dashboard/api.py`** — placed near the existing `/knowledge/cloud-connections` endpoint from Brief 260 (knowledge-related neighbor):
   ```python
   class SourceOfTruthRequest(BaseModel):
       blocks: list = []

   @router.get("/source-of-truth", dependencies=[Depends(_check_auth)])
   async def get_source_of_truth():
       """Brief 262: load tenant SOT blocks. Returns empty list on
       fresh tenant; frontend's DEFAULT_SOT seeds on first PUT."""
       return {"blocks": state_registry.source_of_truth_get()}

   @router.put("/source-of-truth", dependencies=[Depends(_check_auth)])
   async def put_source_of_truth(req: SourceOfTruthRequest):
       """Brief 262: save tenant SOT blocks. Validates + persists.
       Returns the canonical saved blocks (post-validation, with any
       stripped unknown keys removed)."""
       try:
           cleaned = _validate_sot_blocks(req.blocks)
       except ValueError as e:
           raise HTTPException(status_code=400, detail=str(e))
       saved = state_registry.source_of_truth_set(cleaned)
       return {"blocks": saved}
   ```

5. **No changes to existing tables** (`info_updates` / `brand_profile` / `knowledge_files`). No code change in `marina_agent.py` for SOT injection — Calvin's spec defers Agent/persona/knowledge-pipeline integration to a future brief ("Must support future use by the Agent/persona/knowledge pipeline" — backend stores; downstream consumes when wired).

6. **Tenant isolation is automatic**: each tenant container reads its own SQLite DB file (set via `STATE_REGISTRY_DB_PATH` env var or default per-container path). No cross-tenant leakage possible by construction. Tests can verify this by monkeypatching the DB path between simulated tenants.

## Tests

Append 5 tests to `wtyj/tests/social/test_230_knowledge_files.py` (canonical per-module file for knowledge/SOT endpoints — Brief 230 named it, Brief 260's `/knowledge/cloud-connections` tests already extend it). All tests are real TestClient round-trips with `_reset()`-controlled DB state.

1. **test_brief_262_get_returns_empty_blocks_on_fresh_tenant** — wipe `source_of_truth` table, GET `/source-of-truth`. Assert response is `{"blocks": []}`. This is the seed-on-first-load contract; frontend's DEFAULT_SOT kicks in here.

2. **test_brief_262_put_persists_blocks_and_get_returns_them** — PUT `/source-of-truth` with body `{"blocks": [{"id": "pricing", "title": "Pricing", "content": "..."}]}`. Assert 200 + response carries the block. Then GET → assert same blocks returned. Asserts the round-trip contract.

3. **test_brief_262_put_validates_oversized_payload_rejected** — PUT with `{"blocks": [{"id": "x", "title": "y", "content": "A" * 10000}]}` (content exceeds 4 KB cap). Assert 400 response with a meaningful `detail` message. After failure, GET returns the prior state (validation failure does not partially save).

4. **test_brief_262_put_strips_unknown_keys_from_blocks** — PUT with `{"blocks": [{"id": "x", "title": "y", "internal_prompt": "<secret>", "debug_only": true}]}`. Assert 200 + the response blocks contain ONLY `{id, title}` keys (unknown keys stripped). This satisfies Calvin's "Do not expose internal prompt/debug fields" + "Do not trust client-sent titles blindly" constraints — Python rejects what isn't in the allowed-key whitelist.

5. **test_brief_262_subsections_round_trip_intact** — PUT with a block containing 2 subsections, each with title/content/items. Assert 200 + response carries the subsections array intact (titles, contents, items all preserved). This is the load-bearing round-trip test for the nested shape; without it a future refactor could quietly drop subsections during validation.

## Success Condition

After Brief 262 deploys:
- `curl -X GET https://api.unboks.org/api/unboks/dashboard/api/source-of-truth` with auth → returns `{"blocks": []}` on a fresh tenant.
- `curl -X PUT https://api.unboks.org/api/unboks/dashboard/api/source-of-truth` with a valid blocks body → 200, response echoes the canonical saved blocks.
- A second GET returns the saved blocks (persistence verified).
- Different tenants (BlueMarlin vs unboks) return different blocks because each container has its own DB file.
- Oversized or malformed payloads return 400 with a helpful detail message; no partial save.
- All 4 production containers healthy post-deploy.
- Frontend contract for SR documented in OUTPUT (replace `loadSot()` / `saveSot()` with GET / PUT calls; seed DEFAULT_SOT on empty GET; remove the yellow localStorage-only warning).

## Rollback

```
ssh root@108.61.192.52 "bash /root/wtyj/scripts/rollback.sh all"
```

Canonical rollback per `wtyj/briefs/infra.md:188`. The new table is created via `CREATE TABLE IF NOT EXISTS` so it survives a rollback on disk (harmless — the rolled-back code doesn't read it). All schema-level changes are additive; no existing tables touched. If a tenant has already PUT SOT data, a rollback would orphan the row in the DB but cause no functional breakage on the rolled-back code path. The frontend's localStorage stub continues to work as a fallback during any window where the backend is rolled back. Worst case: re-deploy Brief 262 after fixing the issue; saved blocks survive.
