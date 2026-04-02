# BRIEF 040 — Escalation system: semi + full
**Status:** Draft | **Files:** `config/client.json`, `src/marina_agent.py`, `src/email_poller.py`, `src/sheets_writer.py`, `src/format_sheets.py` | **Depends on:** Brief 039 | **Blocks:** Brief 042

## Context
The system has no structured handoff when Marina can't handle something. Two gaps:
1. **Semi-escalation** — customer asks a specific question not in the FAQ (e.g. equipment policy, dietary needs). Marina has no way to relay it to a human and deliver the answer later.
2. **Full escalation** — complaint, refund, cancellation. Marina replies, but the human team gets no alert and has no chat log to act on. Thread keeps processing messages normally even after escalation.

Neither chat history nor thread context flows to the human team today.

## Why This Approach
Semi-escalation uses email relay (butlerbensonagent replies → Marina reformulates) rather than a webhook or third-party ticketing system, because the entire stack is email-native and demo-mode simplicity is required. Full escalation marks `fully_escalated: true` on the thread so Marina continues with holding replies (one Claude call per message, per Rule 1) rather than a static bypass. Chat log accumulation (`th["messages"]`) is the minimal structure needed by both escalation paths and Brief 042 (cross-thread memory). format_sheets.py has a pre-existing broken import (`from sheets_writer import SPREADSHEET_ID, _get_service`) since Brief 032 removed googleapis — this brief updates only the data structures in that file, not the broken import.

## Source Material

### ROADMAP confirmed values
- Demo support/relay email: `butlerbensonagent@gmail.com`
- Production support email: `info@bluefinncharters.com`
- Marina's inbox (Reply-To on relay alerts): `hello@wetakeyourjob.com`

### Relay alert format
```
To: butlerbensonagent@gmail.com
Reply-To: hello@wetakeyourjob.com
Subject: [RELAY] {booking_ref or "NO-REF"} — {customer_name}

Customer: {customer_name} <{from_email}>
Their question: {relay_question}

Booking context:
  Trip: {trip_key} | Date: {date} | Guests: {guests}
  Ref: {booking_ref or "none yet"}

INSTRUCTIONS: Reply to this email with your answer.
Marina will relay it to the customer in her own words.
```

### Full escalation alert format
```
Subject: [ESCALATION] {booking_ref} — {customer_name} — {intents_str}

=== CHAT LOG ===
[CUSTOMER | 2026-03-08T10:00:00Z]
I want a refund.
---
[MARINA | 2026-03-08T10:00:05Z]
I've passed this along to our customer care team...
---

=== BOOKING FIELDS ===
{json.dumps(th["fields"], indent=2)}

=== MARINA'S INTERNAL NOTE ===
{internal_note}
```

### Current email_poller.py imports (line 19)
```python
import imaplib, email, urllib.request, urllib.parse, json, time, os, re, hashlib
```
`datetime` is NOT currently imported. Must be added.

### Current smtp_send signature (line 110)
```python
def smtp_send(to_addr: str, subject: str, body: str, in_reply_to=None, references=None):
```

### Current thread default (line 234–239)
```python
th = threads.get(thread_key, {
    "fields": {},
    "flags": {},
    "last_customer_hash": "",
    "reply_times": []
})
```

### Current Step 4 (lines 342–360)
```python
                # Step 4: requires_human check
                if result.get("requires_human"):
                    smtp_send(from_email, "Re: " + subj, result["reply"],
                              in_reply_to=msg.get("Message-ID"), references=msg.get("References"))
                    bm_logger.log("human_required", email=from_email, subject=subj,
                                  internal_note=result.get("internal_note", ""))
                    sheets_writer.log_escalation({
                        "email": from_email,
                        "subject": subj,
                        "customer_name": th["fields"].get("customer_name", ""),
                        "intent": (result.get("intents") or ["unknown"])[0],
                        "fields_collected": th["fields"],
                        "internal_note": result.get("internal_note", ""),
                    })
                    im.uid("store", uid, "+FLAGS", r"(\Seen)")
                    th["reply_times"].append(now)
                    th["last_customer_hash"] = customer_hash
                    threads[thread_key] = th
                    save_json(THREAD_STATE_PATH, state)
                    continue
```

### Current Step 3b bottom (lines 338–339)
```python
                    else:
                        log(f"Slot unavailable for {from_email}: "
                            f"{avail.get('spots_remaining', 0)}/{avail.get('capacity', 0)} spots remaining")
```

### Current booking reply send (lines 470–472)
```python
                    # Send Claude's reply for all booking sub-cases
                    smtp_send(from_email, "Re: " + subj, reply_text,
                              in_reply_to=msg.get("Message-ID"), references=msg.get("References"))
```

### Current Step 6 send (lines 475–477)
```python
                else:
                    smtp_send(from_email, "Re: " + subj, result["reply"],
                              in_reply_to=msg.get("Message-ID"), references=msg.get("References"))
```

### Current log_escalation in sheets_writer.py (lines 126–145)
```python
def log_escalation(data: dict):
    try:
        row_escalations = [
            _now(),
            data.get('customer_name', ''),
            data.get('email', ''),
            data.get('intent', ''),
            json.dumps(data.get('fields_collected', {})),
            data.get('internal_note', ''),
        ]
```

### Current marina_agent.py ESCALATION BEHAVIOUR (lines 152–161)
```python
ESCALATION BEHAVIOUR:
When the intent is complaint or cancellation, set requires_human
to true. Your reply must:
- Acknowledge what the customer said warmly and with genuine empathy
- Tell them: "I've passed this to our Crew who will be in touch
  with you shortly."
- Do NOT ask for booking details, reference numbers, dates, or
  any other information. The Crew will handle that.
- Do NOT attempt to resolve the issue or make promises about
  outcomes.
- Sign off warmly.
```

### Current marina_agent.py flags JSON spec (lines 220)
```python
  "flags": {{\"awaiting_booking_confirmation\": <true when you are sending a booking summary asking the customer to confirm — omit or false otherwise>, \"booking_confirmed\": <true only when the customer has just confirmed in this message — omit or false otherwise>}},
```

## Instructions

### Step 1 — client.json: add support emails to business section

In `config/client.json`, inside the `"business"` object, after `"spreadsheet_id": "1t1gy6qILNbJNwMBhvixT5yNspulT6-Mkr4-2dMo384I"`, add:

```json
    "support_email": "info@bluefinncharters.com",
    "demo_support_email": "butlerbensonagent@gmail.com"
```

Exact edit — find:
```json
    "spreadsheet_id": "1t1gy6qILNbJNwMBhvixT5yNspulT6-Mkr4-2dMo384I"
  },
```
Replace with:
```json
    "spreadsheet_id": "1t1gy6qILNbJNwMBhvixT5yNspulT6-Mkr4-2dMo384I",
    "support_email": "info@bluefinncharters.com",
    "demo_support_email": "butlerbensonagent@gmail.com"
  },
```

### Step 2 — marina_agent.py: five changes

**2a. Add relay mode and fully_escalated conditional sections to `_build_prompt()`**

After the line `signature = config_loader.get_agent_signature()` (line 61), add:

```python
    relay_mode_section = ""
    if thread_flags.get("awaiting_relay"):
        relay_mode_section = (
            "\nRELAY MODE: A human team member has answered the customer's pending question. "
            "Their answer is in the INBOUND MESSAGE body below. "
            "Reformulate it in Marina's warm voice, using the same language the customer used. "
            "Do not add information the human did not provide. Do not make promises beyond what was stated. "
            "Set intents to [\"inquiry\"]. Do not set any booking or escalation flags.\n"
        )

    fully_escalated_section = ""
    if thread_flags.get("fully_escalated"):
        fully_escalated_section = (
            "\nFULLY ESCALATED THREAD: This conversation has already been passed to the human team. "
            "Send a warm, brief holding message only. Acknowledge the customer warmly. "
            "Remind them the team will be in touch soon. Do not restart the booking process. "
            "Do not ask for information. Do not set any booking or escalation flags.\n"
        )
```

**2b. Inject the two new sections into the f-string return**

Find the start of the return f-string (line 66):
```python
    return f"""You are {business.get('agent_name', 'Marina')}, the booking agent for {business.get('name', 'BlueFinn Charters Curaçao')}.

PERSONA: {csk.get('marina_persona', '')}
```

Replace with:
```python
    return f"""You are {business.get('agent_name', 'Marina')}, the booking agent for {business.get('name', 'BlueFinn Charters Curaçao')}.
{relay_mode_section}{fully_escalated_section}
PERSONA: {csk.get('marina_persona', '')}
```

**2c. Replace the ESCALATION BEHAVIOUR section**

Find (exact block, lines 152–161 of the f-string):
```
ESCALATION BEHAVIOUR:
When the intent is complaint or cancellation, set requires_human
to true. Your reply must:
- Acknowledge what the customer said warmly and with genuine empathy
- Tell them: "I've passed this to our Crew who will be in touch
  with you shortly."
- Do NOT ask for booking details, reference numbers, dates, or
  any other information. The Crew will handle that.
- Do NOT attempt to resolve the issue or make promises about
  outcomes.
- Sign off warmly.
```

Replace with:
```
ESCALATION BEHAVIOUR:
When the intent is complaint, refund request, or cancellation, set requires_human
to true. Your reply MUST:
- Acknowledge what the customer said warmly and with genuine empathy
- Tell them exactly: "I've passed this along to our customer care team.
  You can expect an email from info@bluefinncharters.com shortly —
  they'll take great care of you."
- Do NOT ask for booking details, reference numbers, dates, or
  any other information. The crew will handle that.
- Do NOT attempt to resolve the issue or make promises about outcomes.
- Sign off warmly.

SEMI-ESCALATION:
When the customer asks a specific question you cannot answer from available
context — NOT a complaint, refund, or cancellation (those use requires_human) —
set semi_escalation to true in your JSON response and populate relay_question
with the exact question to forward to the team. Examples: equipment policies
not in the FAQ, specific dietary or accessibility questions, private charter
pricing details. Your reply to the customer should be warm and brief:
tell them you are checking with the team and will get back to them shortly.
Do not set any booking confirmation flags.
```

**2d. Add semi_escalation and relay_question to the JSON schema**

`semi_escalation` and `relay_question` are TOP-LEVEL fields in the JSON response (siblings of `flags`, `reply`, `internal_note`, etc.).

Find the exact block at the end of the f-string JSON spec:
```
  \"flags\": {{\"awaiting_booking_confirmation\": <true when you are sending a booking summary asking the customer to confirm — omit or false otherwise>, \"booking_confirmed\": <true only when the customer has just confirmed in this message — omit or false otherwise>}},
  \"internal_note\": \"<one sentence for the operator log — never shown to the customer>\"
}}"""
```

Replace with:
```
  \"flags\": {{\"awaiting_booking_confirmation\": <true when you are sending a booking summary asking the customer to confirm — omit or false otherwise>, \"booking_confirmed\": <true only when the customer has just confirmed in this message — omit or false otherwise>}},
  \"semi_escalation\": <true only when the customer asks a specific unanswerable question — NOT for complaints or cancellations — omit or false otherwise>,
  \"relay_question\": \"<exact question to relay to the human team — only present when semi_escalation is true — omit otherwise>\",
  \"internal_note\": \"<one sentence for the operator log — never shown to the customer>\"
}}"""
```

**2e. Update file header**

Change:
```python
# LAST MODIFIED: Brief 039
```
To:
```python
# LAST MODIFIED: Brief 040
```

### Step 3 — email_poller.py: eight changes

**3a. Add datetime import**

Find:
```python
import imaplib, email, urllib.request, urllib.parse, json, time, os, re, hashlib
```
Replace with:
```python
import imaplib, email, urllib.request, urllib.parse, json, time, os, re, hashlib
from datetime import datetime, timezone
```

**3b. Add reply_to parameter to smtp_send**

Find:
```python
def smtp_send(to_addr: str, subject: str, body: str, in_reply_to=None, references=None):
```
Replace with:
```python
def smtp_send(to_addr: str, subject: str, body: str, in_reply_to=None, references=None, reply_to=None):
```

Find (inside smtp_send, after the `references` header block):
```python
    if references:
        msg["References"] = references
    msg.attach(MIMEText(body, "plain", "utf-8"))
```
Replace with:
```python
    if references:
        msg["References"] = references
    if reply_to:
        msg["Reply-To"] = reply_to
    msg.attach(MIMEText(body, "plain", "utf-8"))
```

**3c. Add `messages: []` to thread default**

Find:
```python
                th = threads.get(thread_key, {
                    "fields": {},
                    "flags": {},
                    "last_customer_hash": "",
                    "reply_times": []
                })
```
Replace with:
```python
                th = threads.get(thread_key, {
                    "fields": {},
                    "flags": {},
                    "last_customer_hash": "",
                    "reply_times": [],
                    "messages": []
                })
```

**3d. Load demo_support_email at top of main()**

Find (first line of main(), line 186):
```python
    log("Email poller started. UNSEEN-based AUTO-REPLY mode (marina_agent unified call).")
```
Replace with:
```python
    log("Email poller started. UNSEEN-based AUTO-REPLY mode (marina_agent unified call).")
    demo_support_email = config_loader.get_business().get("demo_support_email", "butlerbensonagent@gmail.com")
```

**3e. Add relay detection, messages log, and fully_escalated guard — after anti-loop guard, before Step 1**

Find (the anti-loop guard's final lines and the Step 1 comment):
```python
                    save_json(THREAD_STATE_PATH, state)
                    continue

                # Step 1: Call marina_agent (single Claude call per message)
```

Replace with:
```python
                    save_json(THREAD_STATE_PATH, state)
                    continue

                # [RELAY] inbound from human team — reformulate and forward to original customer
                if from_email.lower() == demo_support_email.lower() and "[RELAY]" in subj:
                    ref_match = re.search(r'BF-\d{4}-\d{5}', subj)
                    relay_ref = ref_match.group() if ref_match else None
                    customer_thread_key = None
                    customer_th = None
                    for tk, t in state["threads"].items():
                        if (t.get("flags", {}).get("awaiting_relay")
                                and (relay_ref is None
                                     or t.get("flags", {}).get("booking_ref") == relay_ref)):
                            customer_thread_key = tk
                            customer_th = t
                            break
                    if customer_th is None:
                        log(f"RELAY: no matching customer thread for ref={relay_ref} — skipping")
                        im.uid("store", uid, "+FLAGS", r"(\Seen)")
                        save_json(THREAD_STATE_PATH, state)
                        continue
                    relay_result = marina_agent.process_message(
                        customer_th["flags"].get("relay_customer_email", ""),
                        customer_th["flags"].get("relay_reply_subject", "Re: " + subj),
                        body,
                        customer_th.get("fields", {}),
                        customer_th.get("flags", {}),
                    )
                    relay_reply = relay_result.get("reply", "")
                    relay_dest = customer_th["flags"].get("relay_customer_email", "")
                    if relay_reply and relay_dest:
                        try:
                            smtp_send(
                                relay_dest,
                                customer_th["flags"].get("relay_reply_subject", "Re: " + subj),
                                relay_reply,
                            )
                            customer_th.setdefault("messages", [])
                            customer_th["messages"].append({
                                "role": "marina",
                                "ts": datetime.now(timezone.utc).isoformat(),
                                "body": relay_reply,
                            })
                            log(f"RELAY: reformulated and sent to {relay_dest}")
                        except Exception as _relay_send_err:
                            log(f"RELAY: send to customer failed: {_relay_send_err}")
                    elif not relay_dest:
                        log(f"RELAY: relay_customer_email missing on thread {customer_thread_key} — skipping send")
                    customer_th["flags"]["awaiting_relay"] = False
                    customer_th["flags"].pop("relay_question", None)
                    state["threads"][customer_thread_key] = customer_th
                    im.uid("store", uid, "+FLAGS", r"(\Seen)")
                    save_json(THREAD_STATE_PATH, state)
                    continue

                # Append inbound message to chat log
                th.setdefault("messages", [])
                th["messages"].append({
                    "role": "customer",
                    "ts": datetime.now(timezone.utc).isoformat(),
                    "body": body,
                })

                # Fully escalated guard — still calls marina_agent (one Claude call), skip booking flow
                if th["flags"].get("fully_escalated"):
                    result = marina_agent.process_message(
                        from_email, subj, body,
                        th.get("fields", {}), th.get("flags", {})
                    )
                    smtp_send(from_email, "Re: " + subj, result["reply"],
                              in_reply_to=msg.get("Message-ID"), references=msg.get("References"))
                    th["messages"].append({
                        "role": "marina",
                        "ts": datetime.now(timezone.utc).isoformat(),
                        "body": result["reply"],
                    })
                    im.uid("store", uid, "+FLAGS", r"(\Seen)")
                    th["reply_times"].append(now)
                    th["last_customer_hash"] = customer_hash
                    threads[thread_key] = th
                    save_json(THREAD_STATE_PATH, state)
                    log(f"Fully escalated: holding reply sent to {from_email}")
                    continue

                # Step 1: Call marina_agent (single Claude call per message)
```

**3f. Replace Step 4 (requires_human) block entirely**

Find the entire Step 4 block:
```python
                # Step 4: requires_human check
                if result.get("requires_human"):
                    smtp_send(from_email, "Re: " + subj, result["reply"],
                              in_reply_to=msg.get("Message-ID"), references=msg.get("References"))
                    bm_logger.log("human_required", email=from_email, subject=subj,
                                  internal_note=result.get("internal_note", ""))
                    sheets_writer.log_escalation({
                        "email": from_email,
                        "subject": subj,
                        "customer_name": th["fields"].get("customer_name", ""),
                        "intent": (result.get("intents") or ["unknown"])[0],
                        "fields_collected": th["fields"],
                        "internal_note": result.get("internal_note", ""),
                    })
                    im.uid("store", uid, "+FLAGS", r"(\Seen)")
                    th["reply_times"].append(now)
                    th["last_customer_hash"] = customer_hash
                    threads[thread_key] = th
                    save_json(THREAD_STATE_PATH, state)
                    continue
```

Replace with:
```python
                # Step 4: requires_human check
                if result.get("requires_human"):
                    smtp_send(from_email, "Re: " + subj, result["reply"],
                              in_reply_to=msg.get("Message-ID"), references=msg.get("References"))
                    th["messages"].append({
                        "role": "marina",
                        "ts": datetime.now(timezone.utc).isoformat(),
                        "body": result["reply"],
                    })
                    th["flags"]["fully_escalated"] = True
                    bm_logger.log("human_required", email=from_email, subject=subj,
                                  internal_note=result.get("internal_note", ""))
                    # Build and send full escalation alert
                    chat_log_lines = []
                    for m in th.get("messages", []):
                        chat_log_lines.append(
                            f"[{m.get('role', '?').upper()} | {m.get('ts', '')}]"
                        )
                        chat_log_lines.append(m.get("body", ""))
                        chat_log_lines.append("---")
                    chat_log = "\n".join(chat_log_lines) or "(no messages logged)"
                    booking_ref_esc = th["flags"].get("booking_ref", "NO-REF")
                    customer_name_esc = th["fields"].get("customer_name", "Unknown")
                    intents_str = ", ".join(result.get("intents") or ["unknown"])
                    escalation_alert = (
                        f"=== CHAT LOG ===\n{chat_log}\n\n"
                        f"=== BOOKING FIELDS ===\n"
                        f"{json.dumps(th['fields'], indent=2, ensure_ascii=False)}\n\n"
                        f"=== MARINA'S INTERNAL NOTE ===\n"
                        f"{result.get('internal_note', '')}"
                    )
                    try:
                        smtp_send(
                            demo_support_email,
                            f"[ESCALATION] {booking_ref_esc} — {customer_name_esc} — {intents_str}",
                            escalation_alert,
                        )
                        log(f"Escalation alert sent to {demo_support_email} for {from_email}")
                    except Exception as _esc_err:
                        log(f"Escalation alert send failed: {_esc_err}")
                    sheets_writer.log_escalation({
                        "email": from_email,
                        "subject": subj,
                        "customer_name": th["fields"].get("customer_name", ""),
                        "intent": (result.get("intents") or ["unknown"])[0],
                        "fields_collected": th["fields"],
                        "internal_note": result.get("internal_note", ""),
                        "messages_json": json.dumps(th.get("messages", []), ensure_ascii=False),
                    })
                    im.uid("store", uid, "+FLAGS", r"(\Seen)")
                    th["reply_times"].append(now)
                    th["last_customer_hash"] = customer_hash
                    threads[thread_key] = th
                    save_json(THREAD_STATE_PATH, state)
                    continue
```

**3g. Add semi-escalation handler after Step 3b**

Find the final lines of Step 3b (the else clause logging):
```python
                    else:
                        log(f"Slot unavailable for {from_email}: "
                            f"{avail.get('spots_remaining', 0)}/{avail.get('capacity', 0)} spots remaining")

                # Step 4: requires_human check
```

Replace with:
```python
                    else:
                        log(f"Slot unavailable for {from_email}: "
                            f"{avail.get('spots_remaining', 0)}/{avail.get('capacity', 0)} spots remaining")

                # Semi-escalation handler: relay question to human team, holding reply to customer
                if result.get("semi_escalation"):
                    relay_question = result.get("relay_question", "(no question captured)")
                    # Cancel any soft hold created during Step 3b — booking is not confirmed
                    if th["flags"].get("hold_id"):
                        state_registry.cancel_hold(th["flags"]["hold_id"])
                        th["flags"].pop("hold_id", None)
                    th["flags"]["slot_checked"] = False
                    th["flags"]["slot_available"] = False
                    th["flags"]["awaiting_relay"] = True
                    th["flags"]["relay_question"] = relay_question
                    th["flags"]["relay_customer_email"] = from_email
                    th["flags"]["relay_reply_subject"] = "Re: " + subj
                    _ref = th["flags"].get("booking_ref", "NO-REF")
                    _cname = th["fields"].get("customer_name", "Unknown")
                    _relay_alert = (
                        f"Customer: {_cname} <{from_email}>\n"
                        f"Their question: {relay_question}\n\n"
                        f"Booking context:\n"
                        f"  Trip: {th['fields'].get('trip_key', '')} | "
                        f"Date: {th['fields'].get('date', '')} | "
                        f"Guests: {th['fields'].get('guests', '')}\n"
                        f"  Ref: {_ref}\n\n"
                        f"INSTRUCTIONS: Reply to this email with your answer.\n"
                        f"Marina will relay it to the customer in her own words."
                    )
                    try:
                        smtp_send(
                            demo_support_email,
                            f"[RELAY] {_ref} — {_cname}",
                            _relay_alert,
                            reply_to=EMAIL_ADDR,
                        )
                        log(f"Semi-escalation: relay alert sent to {demo_support_email} for {from_email}")
                    except Exception as _rel_err:
                        log(f"Semi-escalation: alert send failed: {_rel_err}")
                    smtp_send(from_email, "Re: " + subj, result["reply"],
                              in_reply_to=msg.get("Message-ID"), references=msg.get("References"))
                    th["messages"].append({
                        "role": "marina",
                        "ts": datetime.now(timezone.utc).isoformat(),
                        "body": result["reply"],
                    })
                    bm_logger.log("semi_escalation", email=from_email, subject=subj,
                                  relay_question=relay_question)
                    im.uid("store", uid, "+FLAGS", r"(\Seen)")
                    th["reply_times"].append(now)
                    th["last_customer_hash"] = customer_hash
                    threads[thread_key] = th
                    save_json(THREAD_STATE_PATH, state)
                    continue

                # Step 4: requires_human check
```

**3h. Add outbound message append after each customer-facing smtp_send in Steps 5 and 6**

Find (booking send, Step 5):
```python
                    # Send Claude's reply for all booking sub-cases
                    smtp_send(from_email, "Re: " + subj, reply_text,
                              in_reply_to=msg.get("Message-ID"), references=msg.get("References"))

                # Step 6: All other intents
```

Replace with:
```python
                    # Send Claude's reply for all booking sub-cases
                    smtp_send(from_email, "Re: " + subj, reply_text,
                              in_reply_to=msg.get("Message-ID"), references=msg.get("References"))
                    th["messages"].append({
                        "role": "marina",
                        "ts": datetime.now(timezone.utc).isoformat(),
                        "body": reply_text,
                    })

                # Step 6: All other intents
```

Find (Step 6 send):
```python
                else:
                    smtp_send(from_email, "Re: " + subj, result["reply"],
                              in_reply_to=msg.get("Message-ID"), references=msg.get("References"))
                    primary_intent = (result.get("intents") or ["inquiry"])[0]
```

Replace with:
```python
                else:
                    smtp_send(from_email, "Re: " + subj, result["reply"],
                              in_reply_to=msg.get("Message-ID"), references=msg.get("References"))
                    th["messages"].append({
                        "role": "marina",
                        "ts": datetime.now(timezone.utc).isoformat(),
                        "body": result["reply"],
                    })
                    primary_intent = (result.get("intents") or ["inquiry"])[0]
```

**3i. Update file header**

Change:
```python
# LAST MODIFIED: Brief 039
```
To:
```python
# LAST MODIFIED: Brief 040
```

### Step 4 — sheets_writer.py: add messages_json to log_escalation

Find:
```python
        row_escalations = [
            _now(),
            data.get('customer_name', ''),
            data.get('email', ''),
            data.get('intent', ''),
            json.dumps(data.get('fields_collected', {})),
            data.get('internal_note', ''),
        ]
```

Replace with:
```python
        row_escalations = [
            _now(),
            data.get('customer_name', ''),
            data.get('email', ''),
            data.get('intent', ''),
            json.dumps(data.get('fields_collected', {})),
            data.get('internal_note', ''),
            data.get('messages_json', ''),
        ]
```

Update file header:
```python
# LAST MODIFIED: Brief 032
```
→
```python
# LAST MODIFIED: Brief 040
```

### Step 5 — format_sheets.py: add Escalations tab data structures

After `ALL_EVENTS_WIDTHS =  [180, 150, 200, 200, 400]` (line 29 — note double space before `[`), add:

```python
ESCALATIONS_HEADERS = [
    'Timestamp', 'Customer Name', 'Email', 'Intent',
    'Fields Collected', 'Internal Note', 'Chat Log'
]
ESCALATIONS_WIDTHS = [180, 150, 200, 110, 250, 250, 400]
```

Find `TABS = [` block (lines 31–35):
```python
TABS = [
    {'name': 'Bookings',   'headers': BOOKINGS_HEADERS,   'widths': BOOKINGS_WIDTHS},
    {'name': 'Complaints', 'headers': COMPLAINTS_HEADERS, 'widths': COMPLAINTS_WIDTHS},
    {'name': 'All Events', 'headers': ALL_EVENTS_HEADERS, 'widths': ALL_EVENTS_WIDTHS},
]
```

Replace with:
```python
TABS = [
    {'name': 'Bookings',     'headers': BOOKINGS_HEADERS,     'widths': BOOKINGS_WIDTHS},
    {'name': 'Complaints',   'headers': COMPLAINTS_HEADERS,   'widths': COMPLAINTS_WIDTHS},
    {'name': 'All Events',   'headers': ALL_EVENTS_HEADERS,   'widths': ALL_EVENTS_WIDTHS},
    {'name': 'Escalations',  'headers': ESCALATIONS_HEADERS,  'widths': ESCALATIONS_WIDTHS},
]
```

Update file header:
```python
# LAST MODIFIED: Brief 015
```
→
```python
# LAST MODIFIED: Brief 040
```

Note: The broken import on line 11 (`from sheets_writer import KEY_PATH, SPREADSHEET_ID, _get_service`) is a pre-existing issue since Brief 032 and is NOT touched by this brief. format_sheets.py is a run-once formatting utility; the broken import will be fixed in a future brief.

## Tests

Write `bluemarlin/tests/test_040_escalation_system.py`. Tests call marina_agent directly (Claude API) and mock sheets_writer._append. All assertions must check specific values.

```python
#!/usr/bin/env python3
"""Tests for Brief 040 — Escalation system."""
import sys
import os
import json
import unittest.mock as mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

import marina_agent
import sheets_writer


def test_semi_escalation_flag():
    """T1: Specific accessibility question not in FAQ → semi_escalation: true + relay_question."""
    # Wheelchair accessibility is definitively not in the FAQ — Marina cannot answer it
    result = marina_agent.process_message(
        "john@example.com",
        "Accessibility question",
        "Hi! My father uses a wheelchair. Is the boat accessible for wheelchair users, "
        "and is there a ramp or lift for boarding?",
        {"trip_key": "klein_curacao", "experience": "Klein Curaçao",
         "date": "2026-04-15", "guests": 3},
        {}
    )
    assert result.get("semi_escalation") is True, (
        f"Expected semi_escalation=True, got {result.get('semi_escalation')}. "
        f"Full result: {result}"
    )
    assert result.get("relay_question"), (
        f"Expected relay_question to be non-empty, got: {result.get('relay_question')!r}"
    )
    assert result.get("requires_human") is not True, (
        "semi_escalation must not also set requires_human"
    )
    assert result.get("reply"), "Customer holding reply must be non-empty"
    print(f"  T1 PASS: semi_escalation=True, relay_question={result['relay_question']!r}")


def test_relay_mode_reformulation():
    """T2: Relay mode — Marina reformulates human's answer in her own voice."""
    result = marina_agent.process_message(
        "john@example.com",
        "Re: Klein Curacao trip",
        "Yes, cameras and underwater housings are welcome on board. "
        "We even have a freshwater rinse station on the back deck.",
        {"trip_key": "klein_curacao", "experience": "Klein Curaçao",
         "date": "2026-04-15", "guests": 2},
        {"awaiting_relay": True, "relay_question": "Can I bring my DSLR camera?"}
    )
    assert result.get("reply"), "Relay reply must be non-empty"
    assert result.get("requires_human") is not True, "Relay mode must not set requires_human"
    assert result.get("semi_escalation") is not True, "Relay mode must not set semi_escalation"
    assert result.get("flags", {}).get("booking_confirmed") is not True, \
        "Relay mode must not set booking_confirmed"
    assert result.get("flags", {}).get("awaiting_booking_confirmation") is not True, \
        "Relay mode must not set awaiting_booking_confirmation"
    # Check that the reply incorporates the camera/rinse station content
    reply_lower = result["reply"].lower()
    assert any(word in reply_lower for word in ["camera", "rinse", "welcome", "board"]), (
        f"Reply should incorporate relay answer content. Got: {result['reply'][:200]}"
    )
    print(f"  T2 PASS: relay reformulation reply={result['reply'][:100]!r}...")


def test_full_escalation_requires_human():
    """T3: Refund/complaint → requires_human: true + reply mentions info@bluefinncharters.com."""
    result = marina_agent.process_message(
        "john@example.com",
        "Refund request",
        "I want a full refund for my booking. The crew was rude and the boat was dirty.",
        {"trip_key": "klein_curacao", "date": "2026-04-15", "guests": 2},
        {}
    )
    assert result.get("requires_human") is True, (
        f"Expected requires_human=True, got {result.get('requires_human')}"
    )
    assert "info@bluefinncharters.com" in result.get("reply", ""), (
        f"Reply must mention info@bluefinncharters.com. Got: {result.get('reply', '')[:200]}"
    )
    assert result.get("semi_escalation") is not True, \
        "requires_human path must not also set semi_escalation"
    print(f"  T3 PASS: requires_human=True, reply contains production email")


def test_fully_escalated_thread_holding_reply():
    """T4: fully_escalated=True in thread → Marina sends holding reply, no booking flags."""
    result = marina_agent.process_message(
        "john@example.com",
        "Follow up",
        "Has anyone gotten back to me yet? I'm still waiting.",
        {},
        {"fully_escalated": True}
    )
    assert result.get("reply"), "Fully escalated holding reply must be non-empty"
    assert result.get("flags", {}).get("booking_confirmed") is not True, \
        "Must not set booking_confirmed on fully escalated thread"
    assert result.get("flags", {}).get("awaiting_booking_confirmation") is not True, \
        "Must not set awaiting_booking_confirmation on fully escalated thread"
    assert result.get("requires_human") is not True, \
        "Must not re-escalate an already fully escalated thread"
    print(f"  T4 PASS: holding reply={result['reply'][:100]!r}...")


def test_log_escalation_has_messages_json_column():
    """T5: log_escalation writes 7 columns including messages_json as column 7."""
    captured = {}

    def mock_append(tab_name, row):
        captured[tab_name] = row

    with mock.patch.object(sheets_writer, '_append', side_effect=mock_append):
        sheets_writer.log_escalation({
            "customer_name": "John Test",
            "email": "john@example.com",
            "intent": "complaint",
            "fields_collected": {"trip_key": "klein_curacao"},
            "internal_note": "Customer complained about service",
            "messages_json": json.dumps([
                {"role": "customer", "ts": "2026-03-08T10:00:00Z",
                 "body": "The service was terrible."},
                {"role": "marina", "ts": "2026-03-08T10:00:05Z",
                 "body": "I've passed this along to our customer care team."},
            ]),
        })

    assert "Escalations" in captured, "log_escalation must write to Escalations tab"
    row = captured["Escalations"]
    assert len(row) == 7, f"Escalations row must have 7 columns, got {len(row)}: {row}"
    assert "marina" in row[6], f"Column 7 (Chat Log) must contain messages JSON, got: {row[6][:100]}"
    print(f"  T5 PASS: Escalations row has {len(row)} columns, messages_json in col 7")


if __name__ == "__main__":
    print("Running Brief 040 tests...")
    test_semi_escalation_flag()
    test_relay_mode_reformulation()
    test_full_escalation_requires_human()
    test_fully_escalated_thread_holding_reply()
    test_log_escalation_has_messages_json_column()
    print("\nAll 5 tests passed.")
```

## Success Condition
All 5 tests pass: `python3 bluemarlin/tests/test_040_escalation_system.py`

## Rollback
- `git diff HEAD -- config/client.json src/marina_agent.py src/email_poller.py src/sheets_writer.py src/format_sheets.py` to review changes
- `git checkout HEAD -- <file>` to revert any individual file
- No database schema changes; no data migration needed
