# BRIEF 260 — Cloud knowledge connectors: backend status endpoint + frontend contract (Google/OneDrive/Dropbox; remove SharePoint/Box)
**Status:** Draft | **Files:** `wtyj/dashboard/api.py`, `wtyj/tests/social/test_230_knowledge_files.py` | **Depends on:** Brief 230 (knowledge files), Brief 196 (Google Drive photos OAuth) | **Blocks:** issue #29 verification, SR frontend Replit task

## Context

Issue #29 P1 (Calvin product request 2026-05-11): the dashboard's Source-of-Truth knowledge-connector area currently shows "Google Drive will be connected by the Unboks team. Cloud connections aren't switched on for your workspace yet." for ALL 5 connector cards (Google Drive, OneDrive, Dropbox, SharePoint, Box). The frontend stub at `unboks-dashboard-api/artifacts/unboks/src/hooks/use-cloud-knowledge-connections.ts:65-78` reads from localStorage and forces every provider to `connected: false`. Comment in that file: *"Connect flows are not wired to a backend yet — the calling component shows a calm 'Cloud connections will be connected by the Unboks team.' note when the user clicks Connect, and we never flip `connected` to true on our own."*

Backend reality:
- **Google Drive**: OAuth flow EXISTS (Brief 196 era), wired to PHOTOS via `_GOOGLE_CLIENT_ID` / `_GOOGLE_CLIENT_SECRET` env vars at `wtyj/dashboard/api.py:26-29`, scope `drive.readonly` at line 29. Endpoints: `/google/auth`, `/google/callback`, `/google/status`, `/google/disconnect`, `/google/folders`, `/google/folder`, `/google/sync`. Tokens stored via `state_registry.save_oauth_tokens("google_drive", ...)`. Status check at `api.py:620-630` is BlueMarlin-shaped (photos use case) — needs a knowledge-files surface too.
- **OneDrive**: NO OAuth flow, NO env vars, NO endpoints. Full Microsoft Graph integration requires an Azure AD app registration that only Calvin can do.
- **Dropbox**: NO OAuth flow, NO env vars, NO endpoints. Requires a Dropbox developer-console app that only Calvin can do.
- **SharePoint** + **Box**: Calvin explicitly says hide/remove. No backend, no frontend cleanup yet.

Calvin's spec explicitly allows partial implementation: *"Make cloud knowledge connectors real enough for the unboks tenant flow, OR clearly define the missing OAuth/backend work if full implementation cannot be completed in this brief."* The right MVP is a real status endpoint that breaks the localStorage stub, surfaces honest per-provider state to the dashboard, and documents exactly which external app registrations are needed before any provider beyond Google Drive can flip to `connected`.

## Why This Approach

Three options considered:

1. **Backend status endpoint + frontend contract; OAuth implementation deferred for OneDrive/Dropbox (chosen)** — ships the smallest piece that breaks Calvin's "will be connected by the Unboks team" dead-end stub on the dashboard. The endpoint returns honest `connected` / `setup_required` / `not_configured` states based on env-var presence + token presence in `oauth_tokens`. Google Drive flips to `setup_required` (env vars set, no tokens yet) or `connected` (tokens stored). OneDrive + Dropbox flip to `not_configured` until Calvin registers external apps and adds the env vars. SR's existing `CloudKnowledgeConnections.tsx` component is wired to the API instead of localStorage and the SharePoint/Box cases are dropped. **Smallest scope that delivers product value AND fully documents the external blockers.**

2. **Full OAuth implementation for all three providers in this brief (rejected)** — would require me to invent placeholder env vars, write OAuth flows that can't be tested against the real provider until Calvin registers apps externally, and ship dead code paths. Worse: the OAuth scopes / token shapes differ per provider (Microsoft Graph vs Google vs Dropbox), so each needs its own client. Risk of shipping broken OAuth flows that look wired but break on first use. Calvin's spec explicitly says "clearly define the missing OAuth/backend work if full implementation cannot be completed" — option 1 is the spec-aligned path.

3. **Status endpoint stub that always returns `not_configured` for all three (rejected)** — simpler but dishonest. Google Drive is real today (the photos OAuth flow is live); the new endpoint should reflect that reality even if knowledge-files ingestion from Drive is a separate future brief. The status endpoint is the source of truth for the dashboard; returning `not_configured` when Google tokens ARE stored would mislead the operator.

Trade-off accepted: Brief 260 does NOT extend Google Drive ingestion to `knowledge_files` (that's a separate brief once SR's frontend wires the Connect flow). It also does NOT implement OneDrive or Dropbox OAuth. The brief documents these as deferred work with exact env-var names + provider-app setup steps in the OUTPUT, so Calvin can either (a) register the external apps and ship a follow-up brief that adds the actual OAuth flows, or (b) leave them at `not_configured` indefinitely without misleading the dashboard.

## Instructions

1. **Add new endpoint `GET /knowledge/cloud-connections`** in `wtyj/dashboard/api.py`, placed near the existing `list_knowledge_files` endpoint at `api.py:1078` (it's the natural neighbor for knowledge-related endpoints). Function signature:

   ```python
   @router.get("/knowledge/cloud-connections",
               dependencies=[Depends(_check_auth)])
   async def list_cloud_connections():
       """Brief 260: return the supported cloud connector providers and
       their per-tenant status. Issue #29 narrows the supported set to
       Google Drive, OneDrive, Dropbox; SharePoint and Box are excluded.

       Status per provider:
       - `connected`: OAuth env vars present AND tokens stored in oauth_tokens.
       - `setup_required`: OAuth env vars present but no tokens yet
         (operator can click Connect to start the OAuth flow).
       - `not_configured`: OAuth env vars missing on this deploy
         (provider-app registration + env vars required before Connect
         can do anything). UI should show this as a disabled card.
       """
       ...
   ```

2. **Status computation helpers** — three helper functions in the same file, placed immediately above the endpoint:

   ```python
   def _google_drive_connection_status() -> dict:
       """Brief 260: returns dict with keys: provider, status, label, blurb.
       `connected` requires both env-var presence AND a stored token.
       Reuses Brief 196 env vars _GOOGLE_CLIENT_ID + _GOOGLE_CLIENT_SECRET
       and the oauth_tokens row keyed by 'google_drive'."""

   def _onedrive_connection_status() -> dict:
       """Brief 260: returns dict for OneDrive provider. Reads
       ONEDRIVE_OAUTH_CLIENT_ID + ONEDRIVE_OAUTH_CLIENT_SECRET env vars
       (not yet provisioned; will return `not_configured` until Calvin
       registers the Azure AD app — see OUTPUT for setup steps)."""

   def _dropbox_connection_status() -> dict:
       """Brief 260: returns dict for Dropbox provider. Reads
       DROPBOX_OAUTH_CLIENT_ID + DROPBOX_OAUTH_CLIENT_SECRET env vars
       (not yet provisioned; will return `not_configured` until Calvin
       registers the Dropbox app — see OUTPUT for setup steps)."""
   ```

3. **Endpoint body**: call the three helpers in fixed order (Google, OneDrive, Dropbox), return a list:
   ```python
   return {
       "providers": [
           _google_drive_connection_status(),
           _onedrive_connection_status(),
           _dropbox_connection_status(),
       ],
   }
   ```
   Each provider dict shape:
   ```python
   {
       "provider": "google_drive",  # stable id
       "label": "Google Drive",     # human label for UI
       "blurb": "Docs, Sheets, PDFs, menus.",  # UI subtitle
       "status": "connected" | "setup_required" | "not_configured",
       "folder_name": "<optional>",  # only when connected + folder selected
       "last_synced_at": "<optional ISO>",  # only when connected and last sync recorded
       "needs_provider_app_registration": True | False,  # True when not_configured
   }
   ```

4. **NO changes to**: existing `/google/auth`, `/google/callback`, `/google/status`, `/google/folders`, `/google/folder`, `/google/sync`, `/google/disconnect` endpoints. Those continue serving the photos-OAuth use case unchanged. The new `/knowledge/cloud-connections` endpoint READS from the same `oauth_tokens` row (`provider="google_drive"`) but does not modify it.

5. **NO new OAuth flow code** for OneDrive or Dropbox. The status helpers for those return `not_configured` whenever the env vars are absent. When Calvin registers the external apps and sets the env vars, a future brief can add the actual `/onedrive/auth` and `/dropbox/auth` endpoints.

6. **NO new env var fallback values** — `os.environ.get("ONEDRIVE_OAUTH_CLIENT_ID", "")` style only. Missing env vars must surface as `not_configured`, never as a fake "configured" state.

## Tests

Append 4 tests to `wtyj/tests/social/test_230_knowledge_files.py` (canonical per-module file for knowledge-related dashboard endpoints; Brief 230 named it). All tests exercise the new endpoint via the FastAPI TestClient with `monkeypatch` to control env-var + oauth_tokens state.

1. **test_brief_260_cloud_connections_returns_three_providers_in_fixed_order** — call `GET /dashboard/api/knowledge/cloud-connections` with auth. Assert response has `providers` list of length 3, IDs in order `google_drive`, `onedrive`, `dropbox`. Assert SharePoint and Box are NOT in the response.

2. **test_brief_260_google_drive_setup_required_when_env_set_but_no_tokens** — monkeypatch `_GOOGLE_CLIENT_ID` + `_GOOGLE_CLIENT_SECRET` to truthy values, ensure no `oauth_tokens` row for `google_drive` (call `_reset()` or delete the row), hit the endpoint. Assert Google Drive provider has `status="setup_required"` AND `needs_provider_app_registration=False`.

3. **test_brief_260_google_drive_connected_when_env_set_and_tokens_stored** — monkeypatch env vars truthy, call `state_registry.save_oauth_tokens("google_drive", "access", "refresh", "<future ISO>")` to seed a token row, hit the endpoint. Assert Google Drive provider has `status="connected"`. Cleanup token row in teardown.

4. **test_brief_260_onedrive_and_dropbox_not_configured_without_env** — ensure `ONEDRIVE_OAUTH_CLIENT_ID` and `DROPBOX_OAUTH_CLIENT_ID` are NOT set in the test env (monkeypatch.delenv or assert absent), hit the endpoint. Assert OneDrive AND Dropbox both have `status="not_configured"` AND `needs_provider_app_registration=True`. This is the load-bearing assertion that the brief honestly surfaces external blockers instead of pretending the connectors are wired.

## Success Condition

After Brief 260 deploys:
- `curl http://localhost:8004/dashboard/api/knowledge/cloud-connections` with auth returns the 3-provider list (Google Drive / OneDrive / Dropbox). No SharePoint, no Box.
- For unboks live state today: Google Drive shows `setup_required` (env vars set on production, no tokens stored yet for unboks tenant); OneDrive + Dropbox show `not_configured` (env vars not set).
- All 4 production containers healthy post-deploy.
- The OUTPUT report (Brief 260) lists exactly which env vars + OAuth redirect URLs Calvin needs to provision for OneDrive (Azure AD) and Dropbox (Dropbox dev console) before those can flip to `setup_required`.
- Frontend contract for SR is fully documented in the OUTPUT report: which fields to read, which providers to drop from the legacy 5-provider list, how to wire the existing Connect button to the existing `/google/auth` endpoint.

## Rollback

```
ssh root@108.61.192.52 "bash /root/wtyj/scripts/rollback.sh all"
```

Canonical rollback per `wtyj/briefs/infra.md:188`. Pure additive change (one new endpoint, three new helpers, no schema migration, no modification of existing endpoints). Revert restores the prior state in <30s: dashboard frontend falls back to its localStorage stub (already the production behavior pre-Brief-260), `/knowledge/cloud-connections` 404s. No data loss possible.
