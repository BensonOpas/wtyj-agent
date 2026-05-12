# OUTPUT 260 — Cloud knowledge connectors status endpoint

## What was done

P1 backend for issue #29. The dashboard's Source-of-Truth knowledge-connector area was showing the placeholder "Google Drive will be connected by the Unboks team. Cloud connections aren't switched on for your workspace yet." for ALL 5 provider cards — the frontend's `useCloudKnowledgeConnections` hook at `unboks-dashboard-api/artifacts/unboks/src/hooks/use-cloud-knowledge-connections.ts:65-78` is a localStorage-only stub that forces every provider to `connected: false`. Brief 260 ships the backend status endpoint that lets SR's frontend replace the stub with real data. Calvin's narrowed provider set (Google Drive, OneDrive, Dropbox) becomes the new shape; SharePoint and Box are dropped.

`GET /knowledge/cloud-connections` returns `{"providers": [...]}` — a fixed-order list of 3 provider dicts with `provider` / `label` / `blurb` / `status` / `needs_provider_app_registration` fields, plus optional `folder_name` / `last_synced_at` when applicable. Status is computed from (a) OAuth env-var presence on the deploy and (b) `oauth_tokens` row presence for the provider. Three states: `connected` (env vars set AND tokens stored), `setup_required` (env vars set but no tokens — operator can click Connect), `not_configured` (env vars missing — provider-app registration required first). Google Drive reuses Brief 196's existing `GOOGLE_OAUTH_CLIENT_ID` / `GOOGLE_OAUTH_CLIENT_SECRET` env vars and the existing `oauth_tokens` row keyed by `google_drive` — no modification to the existing photos-OAuth flow.

## Tests

1106 passing / 0 failures (1102 baseline + 4 new = 1106). All four tests are real TestClient round-trips with `monkeypatch`-controlled env + `_reset_oauth_tokens()` controlled DB state — not source-string greps. Test 4 (`onedrive_and_dropbox_not_configured_without_env`) is the load-bearing assertion that the brief honestly surfaces external blockers instead of pretending the connectors are wired.

## What's actually implemented now

- **Backend endpoint live**: `GET /api/{tenant}/dashboard/api/knowledge/cloud-connections` returns 3 providers with computed status. Authenticated via the same `_check_auth` pattern as other dashboard endpoints. Tenant-aware automatically (each container reads its own `oauth_tokens` table + the deploy-level env vars).
- **Google Drive status**: on the live unboks container today, `GOOGLE_OAUTH_CLIENT_ID` + `GOOGLE_OAUTH_CLIENT_SECRET` are present (verified via Brief 196 photos flow already working on BlueMarlin/Adamus), so unboks's Google Drive status reports `setup_required` (env vars set, no tokens stored for unboks tenant yet). Operator can click Connect → existing `/google/auth` flow stores a token row → next status call reports `connected`.
- **OneDrive status**: `not_configured` (no env vars on any production deploy). `needs_provider_app_registration: true`.
- **Dropbox status**: `not_configured`. `needs_provider_app_registration: true`.

## What remains blocked by OAuth/provider registration

Brief 260 ships the status surface but does NOT add new OAuth flows for OneDrive or Dropbox. Two external app registrations are required before either provider can flip from `not_configured` to `setup_required`:

### OneDrive — Microsoft Graph (Azure AD app registration)

**Setup steps Calvin needs to do**:
1. Sign in to https://portal.azure.com with a Microsoft 365 admin account.
2. Azure Active Directory → App registrations → New registration.
3. Name: `Unboks - Knowledge Connector` (or similar).
4. Supported account types: "Accounts in any organizational directory and personal Microsoft accounts" (multi-tenant + personal Microsoft accounts).
5. Redirect URI (Web platform): `https://api.unboks.org/dashboard/api/onedrive/callback` (the endpoint will be added in a follow-up brief).
6. Register → copy the **Application (client) ID** → set as `ONEDRIVE_OAUTH_CLIENT_ID` env var on each tenant container.
7. Certificates & secrets → New client secret (expires 24 months) → copy the **Value** field (NOT the Secret ID) → set as `ONEDRIVE_OAUTH_CLIENT_SECRET` env var.
8. API permissions → Add a permission → Microsoft Graph → Delegated permissions:
   - `Files.Read.All` (read all files the operator can access)
   - `Sites.Read.All` (optional — only if SharePoint document libraries should be readable; SharePoint is out of scope per #29 so probably skip)
   - `offline_access` (required for refresh tokens — without this, tokens expire in ~1 hour with no refresh path)
9. Grant admin consent on the permissions (org-wide).
10. Save the **Tenant ID** (Directory tenant ID from Overview tab) as `ONEDRIVE_TENANT_ID` env var — required for the token endpoint URL.

**Env vars required on each container's `platform.env`**:
- `ONEDRIVE_OAUTH_CLIENT_ID=<application client id from step 6>`
- `ONEDRIVE_OAUTH_CLIENT_SECRET=<client secret value from step 7>`
- `ONEDRIVE_TENANT_ID=<directory tenant id from step 10>`

**Redirect URL** to whitelist in Azure AD: `https://api.unboks.org/dashboard/api/onedrive/callback`

### Dropbox — Dropbox developer console app

**Setup steps Calvin needs to do**:
1. Sign in to https://www.dropbox.com/developers/apps with the operator account.
2. Create app → Scoped access → Full Dropbox (or App folder if you only want a single Unboks folder — recommend Full Dropbox so operators can pick any folder).
3. Name: `Unboks Knowledge Connector` (or similar — Dropbox enforces unique app names globally).
4. Permissions tab → toggle ON:
   - `files.metadata.read`
   - `files.content.read`
5. Redirect URIs (Settings tab) → add: `https://api.unboks.org/dashboard/api/dropbox/callback`
6. App key → copy → set as `DROPBOX_OAUTH_CLIENT_ID` env var.
7. App secret → copy → set as `DROPBOX_OAUTH_CLIENT_SECRET` env var.

**Env vars required**:
- `DROPBOX_OAUTH_CLIENT_ID=<app key from step 6>`
- `DROPBOX_OAUTH_CLIENT_SECRET=<app secret from step 7>`

**Redirect URL** to whitelist: `https://api.unboks.org/dashboard/api/dropbox/callback`

### Once env vars are set
A follow-up brief (Brief 26X) will add `/onedrive/auth`, `/onedrive/callback`, `/dropbox/auth`, `/dropbox/callback` endpoints mirroring the existing Google flow. The status endpoint Brief 260 ships requires no changes; once a token row appears in `oauth_tokens` for the provider, status flips to `connected` automatically.

## Frontend contract for SR (Replit task)

Update `unboks-dashboard-api/artifacts/unboks/src/hooks/use-cloud-knowledge-connections.ts`:

1. **Drop SharePoint and Box** from `CloudProvider` type union (line 11-16) and from `CLOUD_PROVIDERS` array (lines 53-62). New type:
   ```ts
   export type CloudProvider = "google_drive" | "onedrive" | "dropbox";
   ```
2. **Drop their cases** from `CloudKnowledgeConnections.tsx` (lines 72-77 of switch statement).
3. **Replace `readFromStorage`** (line 65) with a React Query hook that fetches `GET /api/{tenant}/dashboard/api/knowledge/cloud-connections`. The response shape:
   ```ts
   interface CloudConnectionsResponse {
     providers: {
       provider: "google_drive" | "onedrive" | "dropbox";
       label: string;          // "Google Drive" / "OneDrive" / "Dropbox"
       blurb: string;          // short subtitle for the card
       status: "connected" | "setup_required" | "not_configured";
       needs_provider_app_registration: boolean;
       folder_name?: string;   // optional, only when connected
       last_synced_at?: string; // optional ISO timestamp
     }[];
   }
   ```
4. **Connect button behavior**:
   - `status === "connected"` → show "Connected", display `folder_name` + `last_synced_at`. Button: "Reconnect" or "Disconnect".
   - `status === "setup_required"` → show "Not connected". Button: "Connect" → redirects to `/api/{tenant}/dashboard/api/google/auth?redirect_to={dashboard-url}` for Google Drive. For OneDrive/Dropbox, button stays disabled until those backend flows ship in a follow-up brief — show inline note "OneDrive connector backend in progress."
   - `status === "not_configured"` → show "Setup pending — contact Unboks team". Button disabled. The card stays visible so the operator knows the provider is on the roadmap, just not wired yet on this deploy.
5. **Disconnect**: keep the existing `disconnect` mutation but route through `DELETE /api/{tenant}/dashboard/api/google/disconnect` (existing endpoint) when provider is `google_drive`. OneDrive + Dropbox disconnect endpoints don't exist yet — disable the button or show "Not connected" instead.

## Endpoints changed/added

- **Added**: `GET /knowledge/cloud-connections` (under `_check_auth`, returns `{providers: [...]}`)
- **Unchanged**: `/google/auth`, `/google/callback`, `/google/status`, `/google/folders`, `/google/folder`, `/google/sync`, `/google/disconnect` (Brief 196 photos flow continues serving its existing use case)
- **Unchanged**: `/knowledge/files`, `/knowledge/files/{id}` (Brief 230 knowledge-files endpoints)

## Tests / build result

- 1106 tests passing / 0 failures (1102 baseline + 4 new).
- Targeted file `wtyj/tests/social/test_230_knowledge_files.py` runs 11/11.
- Test 4 (`test_brief_260_onedrive_and_dropbox_not_configured_without_env`) is the load-bearing honesty check: when env vars are absent, the endpoint returns `not_configured` not `connected`.

## Production / health

- Source commit `1fab650` ([HOTFIX] subject) deployed via CI.
- All 4 production containers healthy on the new image.

## Calvin retest steps

1. Open the dashboard's Source-of-Truth / knowledge connectors area on the unboks tenant.
2. **Expected (once SR's Replit task lands the frontend changes)**: 3 connector cards (Google Drive, OneDrive, Dropbox). No SharePoint, no Box.
3. **Google Drive card**: should show "Not connected" with a working "Connect" button. Click → redirect to Google consent → after approval, status flips to "Connected".
4. **OneDrive card**: should show "Setup pending — contact Unboks team". Connect button disabled. This confirms the honesty layer: until you provision the Azure AD app + env vars per the OAuth setup steps above, the connector stays in `not_configured` state.
5. **Dropbox card**: same as OneDrive — `not_configured` until Dropbox dev console app + env vars are provisioned.
6. **Backend smoke test (curl)**: `curl -H "Authorization: Bearer <token>" https://api.unboks.org/api/unboks/dashboard/api/knowledge/cloud-connections` should return the 3-provider JSON with correct statuses for the current deploy state.

If you provision the Azure AD app + Dropbox app and want the actual OAuth flows wired in a follow-up brief, J2-29-followup with the env vars set on the platform.env files and I'll ship the `/onedrive/auth`+`/onedrive/callback`+`/dropbox/auth`+`/dropbox/callback` endpoints + knowledge-file ingestion pipelines.
