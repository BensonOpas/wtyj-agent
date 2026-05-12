# OUTPUT 262 — Source of Truth server-side persistence

## What was done

P1 for issue #31. Replit #28 had shipped a frontend SotBlock editor that saved to browser localStorage — Calvin verified the editability worked but the implementation honestly displayed a yellow warning that edits stayed device-only. Brief 262 ships the server-side persistence layer so SOT syncs across devices/browsers/operators per tenant.

Backend audit caught that none of the existing knowledge-adjacent tables (`info_updates` for short additive notes, `brand_profile` for flat brand-voice rules, `knowledge_files` for uploaded docs) match the nested `SotBlock[]` shape from the frontend (`id` / `title` / `content?` / `items?` / `subsections?`). Brief 262 adds a new table and exposes simple GET/PUT endpoints. No marina_agent.py integration (Calvin's spec defers Agent/persona/knowledge-pipeline consumption to a future brief — backend stores; downstream consumers will pull when wired).

## Storage model

- **New table `source_of_truth`** at `wtyj/shared/state_registry.py:671` (created adjacent to `system_settings` via `CREATE TABLE IF NOT EXISTS`). Schema: `id INTEGER PRIMARY KEY`, `blocks_json TEXT NOT NULL DEFAULT '[]'`, `updated_at TEXT NOT NULL DEFAULT ''`. Single row per tenant keyed by `id=1`; tenant isolation is by construction (each container has its own SQLite DB file via `STATE_REGISTRY_DB_PATH`).
- **New helpers**:
  - `source_of_truth_get() -> list` — SELECT the single row, parse the JSON. Returns `[]` on missing row or corrupted JSON (defensive).
  - `source_of_truth_set(blocks: list) -> list` — UPSERT (`INSERT ... ON CONFLICT(id) DO UPDATE`). Returns the parsed-back blocks to verify round-trip cleanliness.

## Endpoints

- **`GET /api/{tenant}/dashboard/api/source-of-truth`** — auth-gated, returns `{"blocks": [...]}`. Empty list on a fresh tenant (frontend seeds its `DEFAULT_SOT` on first PUT).
- **`PUT /api/{tenant}/dashboard/api/source-of-truth`** — auth-gated, accepts `{"blocks": [...]}` body. Validates via `_validate_sot_blocks()`, persists, returns the canonical saved blocks (post-validation, with unknown keys stripped).
- **`GET /knowledge/files` + `DELETE /knowledge/files/{id}` + `GET /knowledge/cloud-connections`** — unchanged (Brief 230, Brief 260).

## Validation limits

| Field | Limit |
|---|---|
| Number of blocks per tenant | 50 |
| Subsections per block | 20 |
| Items per list (block-level + per subsection) | 50 each |
| `id` length | 200 chars |
| `title` length (block + subsection) | 200 chars |
| `content` length (block + subsection) | 4096 chars |
| `items[i]` length | 4096 chars each |
| Allowed top-level block keys | `id`, `title`, `content`, `items`, `subsections` (others silently stripped) |
| Allowed subsection keys | `title`, `content`, `items` (others stripped) |

On validation failure: HTTP 400 with detail (`"Block 0: content exceeds 4096 chars"`, `"Too many blocks (max 50)"`, etc.) and NO partial save — subsequent GET returns the prior state.

## Tenant isolation behavior

Each tenant container reads its own SQLite DB file. The `source_of_truth.id=1` row is therefore tenant-scoped by construction. A future Replit task could call the unboks tenant URL and the BlueMarlin tenant URL and the two responses would carry independent blocks. No cross-tenant leak is possible by the storage model.

## Migration / default-seeding behavior

Backend does NOT carry a default SOT constant. Frontend's `DEFAULT_SOT` at `unboks-dashboard-api/artifacts/unboks/src/data/sot.ts:15` remains the authoring source for the default content. On a fresh tenant: GET returns `{"blocks": []}` → frontend detects empty → frontend PUTs `DEFAULT_SOT` → next GET returns the seeded blocks. This avoids duplicating the default-content array on the backend (where it would drift from the frontend version).

## Tests

1116 passing / 0 failures (1111 baseline + 5 new). New tests in `wtyj/tests/social/test_230_knowledge_files.py`:

1. **GET returns empty blocks on fresh tenant** — exact `{"blocks": []}` shape contract.
2. **PUT persists, GET returns** — round-trip contract.
3. **PUT validation: oversized content rejected** — HTTP 400 + no partial save (prior state preserved).
4. **PUT strips unknown keys** — `internal_prompt`, `debug_only`, `_admin_field` round-trip out cleanly; not in response, not in subsequent GET response text. Load-bearing security assertion.
5. **Subsections round-trip intact** — nested `title` / `content` / `items` survive validation + storage.

## Frontend contract for SR (Replit task)

Replace localStorage persistence in `unboks-dashboard-api/artifacts/unboks/src/data/sot.ts` + `pages/Settings.tsx`:

1. **Delete `STORAGE_KEY` localStorage usage** in `loadSot()` / `saveSot()`. Replace with React Query hooks:
   ```ts
   import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
   import { DEFAULT_SOT, type SotBlock } from "@/data/sot";

   export function useSot() {
     const qc = useQueryClient();
     const query = useQuery({
       queryKey: ["source-of-truth"],
       queryFn: async () => {
         const r = await fetch(
           `/api/${tenant}/dashboard/api/source-of-truth`,
           { headers: { Authorization: `Bearer ${token}` } },
         );
         const data: { blocks: SotBlock[] } = await r.json();
         return data.blocks;
       },
       staleTime: 30_000,
     });

     const save = useMutation({
       mutationFn: async (blocks: SotBlock[]) => {
         const r = await fetch(
           `/api/${tenant}/dashboard/api/source-of-truth`,
           {
             method: "PUT",
             headers: {
               "Content-Type": "application/json",
               Authorization: `Bearer ${token}`,
             },
             body: JSON.stringify({ blocks }),
           },
         );
         if (!r.ok) throw new Error(await r.text());
         const data: { blocks: SotBlock[] } = await r.json();
         return data.blocks;
       },
       onSuccess: (saved) =>
         qc.setQueryData(["source-of-truth"], saved),
     });

     return { blocks: query.data ?? [], isLoading: query.isLoading, save };
   }
   ```

2. **Seed DEFAULT_SOT on empty GET**: when the initial GET returns `[]`, automatically PUT `DEFAULT_SOT` so subsequent loads return the canonical blocks:
   ```ts
   useEffect(() => {
     if (!query.isLoading && (query.data?.length ?? 0) === 0) {
       save.mutate(DEFAULT_SOT);
     }
   }, [query.isLoading, query.data]);
   ```

3. **Remove the yellow local-only warning** from `pages/Settings.tsx`. Replace with a green sync indicator like *"Synced across your workspace"* once `save` resolves.

4. **Validation errors**: if PUT returns 400, surface the `detail` field (already a frontend-renderable string from the backend validator) in a toast/banner so the operator sees exactly which block exceeded a cap.

5. **Multi-device retest** for Calvin:
   - Open the unboks Settings page on Browser A. Edit a SOT block. Click Save.
   - Open Settings on Browser B (or on mobile). Should see the same edits.
   - Open on a different device with a different operator login. Should see the same edits.
   - Hard-refresh: edits persist (no localStorage dependency).

## Production health

CI deploy queued post-commit `c8c3b97`. All 4 containers expected healthy. Schema migration runs on first boot of each container (idempotent via `CREATE TABLE IF NOT EXISTS`).

## Calvin retest steps

1. **Backend smoke test (curl)**:
   ```
   # Login + token
   curl -X POST https://api.unboks.org/api/unboks/dashboard/api/login \
     -H "Content-Type: application/json" \
     -d '{"password": "<dashboard pw>"}'
   # GET initial state (should be empty)
   curl -H "Authorization: Bearer <token>" \
     https://api.unboks.org/api/unboks/dashboard/api/source-of-truth
   # Expected: {"blocks":[]}
   # PUT a test block
   curl -X PUT https://api.unboks.org/api/unboks/dashboard/api/source-of-truth \
     -H "Authorization: Bearer <token>" -H "Content-Type: application/json" \
     -d '{"blocks":[{"id":"core-value","title":"Core Value","content":"We save time."}]}'
   # Expected: {"blocks":[{"id":"core-value","title":"Core Value","content":"We save time."}]}
   # GET again - should match
   curl -H "Authorization: Bearer <token>" \
     https://api.unboks.org/api/unboks/dashboard/api/source-of-truth
   ```
2. **Validation test**: PUT a block with `content` longer than 4 KB → expect HTTP 400 with detail like `"Block 0: content exceeds 4096 chars"`. Then GET → blocks should be unchanged from step 1.
3. **Unknown-key strip test**: PUT `{"blocks": [{"id":"x","title":"y","content":"z","internal_prompt":"leak"}]}` → response should NOT contain `internal_prompt`.
4. **Cross-tenant isolation test**: same curl flow against BlueMarlin's URL (`https://api.bluemarlin.org/api/bluemarlin/dashboard/api/source-of-truth`). Should return BlueMarlin's blocks (or empty), independent of unboks.
5. **End-to-end (after SR's Replit task)**: edit a SOT block on browser A → save → reload browser B → edits visible. Hard-refresh A → edits persist.

If anything misbehaves, paste the request + response and I'll iterate.
