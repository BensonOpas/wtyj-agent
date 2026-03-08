# LESSONS — BlueMarlin Agent Briefs

One entry per brief. What worked, what was tricky, what to watch for next time.

---

## Brief 040 — Escalation system: semi + full
**Date:** 2026-03-08

Two reviewer passes needed: (1) format_sheets.py anchor had a double-space (`ALL_EVENTS_WIDTHS =  [...]`) that a single-space anchor would miss — always copy-paste exact whitespace from Read tool output when anchoring edits in files with aligned spacing; (2) relay block's `smtp_send` to customer was unguarded — any optional path that depends on a flag value (like `relay_customer_email`) that might be absent needs a try/except or an explicit guard before the send; (3) `semi_escalation` must cancel the soft hold created in Step 3b to avoid capacity leaks — whenever a `continue` path bypasses the normal booking flow, check whether Step 3b already ran and clean up any side effects.

---

## Brief 039 — Capacity-aware booking with soft holds
**Date:** 2026-03-08

Two review cycles were needed: (1) `{N}` inside an f-string in the prompt raises `NameError` — always use `{{N}}` for literal braces inside Python f-strings in marina_agent.py prompt sections; (2) `create_soft_hold` using raw `sqlite3.connect()` bypasses `_get_conn()`'s table creation — always route through `_get_conn()` for schema guarantees, then set `isolation_level = None` if manual transaction control is needed. Brief reviewer caught both before execution; test suite cleanly validated all 8 scenarios including concurrent race.
