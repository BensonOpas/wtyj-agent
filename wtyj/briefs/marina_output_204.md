# OUTPUT 204 — Add Gmail app-password auth path to email_adapter.py (IMAP + SMTP)

## What was done
Single file change to `wtyj/agents/marina/email_adapter.py`. Added module-level `EMAIL_PASSWORD = os.environ.get("EMAIL_PASSWORD", "")` and Gmail host constants. Both `imap_connect()` (line 99) and `smtp_send()` (line 108) now branch on `EMAIL_PASSWORD`: when set, connect to `imap.gmail.com:993` / `smtp.gmail.com:587` and use basic `LOGIN` auth (Gmail app password mode); when empty, fall through to the existing Microsoft OAuth XOAUTH2 path. The whitespace strip on the password handles Google's display format (4×4 chars space-separated). No changes to `email_poller.py` — the function signatures didn't change. Per /scope check earlier, dropped the heavy provider-abstraction plan in favor of this minimum-viable approach: ~30 lines of code change vs. the half-day refactor I was originally scoping. Brief-reviewer PASS first try with 4 advisory notes; took the SMTP-test recommendation (added 3rd test).

## Tests
920 passing / 0 failures (baseline 917 + 3 new — IMAP Gmail mode connects to imap.gmail.com with LOGIN; IMAP Microsoft regression preserves outlook.office365.com + XOAUTH2; SMTP Gmail mode connects to smtp.gmail.com:587 + STARTTLS + LOGIN, no XOAUTH2 docmd).

## Deployment
Source commit will be `<source-sha>`. Standard deploy via canary pipeline rebuilds the shared image and restarts all 4 production containers + staging. **Manual VPS step required after deploy:** add `EMAIL_ADDRESS=hello@unboks.org` and `EMAIL_PASSWORD=<16-char-no-spaces>` to `/root/clients/unboks/config/platform.env`, then `docker compose down && docker compose up -d` for the unboks container. Without those env vars set, calvin-csa's email path stays inactive (graceful exit per Brief 146 guard), and BlueMarlin/Adamus continue using OAuth unchanged.
