# BRIEF 126 — Escalation Detail Polish + Smart Compose Pre-fill
**Status:** Draft | **Depends on:** Brief 125 (complete) | **Blocks:** —

**Files:**
- `~/Projects/wetakeyourjob-dashboard/artifacts/dashboard/src/pages/Escalations.tsx`

## Context
The escalation detail view shows raw data — the subject is "[ESCALATION] NO-REF - Calvin Adamus (WhatsApp: 59996881585) - complaint" and the body is a raw text dump with `=== CUSTOMER ===` and `=== CHAT LOG ===` sections. When clicking Compose email for full escalations, the To/Subject fields are empty — they should be pre-filled with the customer's email (from the body) and a clean subject.

## Why This Approach
Frontend-only. Parse the escalation body text to extract customer email and chat log. Show them in clean sections. Pre-fill compose modal with extracted data. No backend changes.

## Source Material

**Escalation body format (from backend):**
```
=== CUSTOMER ===
WhatsApp: 59996881585
Name: Calvin Adamus
Email: benson_agent@icloud.com

=== CHAT LOG ===
[USER | 2026-03-24T02:00:28...]
I want a refund, the trip was terrible...
---
[ASSISTANT | 2026-03-24T02:00:33...]
Calvin, I'm really sorry to hear that...
```

**Escalation subject format:**
`[ESCALATION] NO-REF - Calvin Adamus (WhatsApp: 59996881585) - complaint`

### Edit 1 — Add parser helper function (before the export default)

Add after the `isSemi` function (around line 112):

```tsx
function parseEscalationBody(body: string) {
  const emailMatch = body.match(/Email:\s*(\S+@\S+)/i);
  const phoneMatch = body.match(/WhatsApp:\s*(\d+)/);
  const chatLogStart = body.indexOf("=== CHAT LOG ===");
  const chatLog = chatLogStart >= 0 ? body.slice(chatLogStart + 16).trim() : "";
  return {
    email: emailMatch?.[1] || "",
    phone: phoneMatch?.[1] || "",
    chatLog,
  };
}

function cleanSubject(subject: string): string {
  // "[ESCALATION] NO-REF - Calvin Adamus (WhatsApp: 59996881585) - complaint"
  // → "complaint" or the intent part
  const parts = subject.split(" - ");
  const intent = parts[parts.length - 1]?.trim() || subject;
  return intent.charAt(0).toUpperCase() + intent.slice(1);
}
```

### Edit 2 — Rewrite detail view (lines 474-488)

Replace the raw detail sections:
```tsx
          <div className="space-y-4 flex-1 overflow-y-auto min-h-0">
            <div>
              <h3 className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-2">Customer</h3>
              <p className="text-sm text-foreground">{selected.customer_name} — {selected.customer_id}</p>
            </div>
            <div>
              <h3 className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-2">Subject</h3>
              <p className="text-sm text-foreground/90 font-medium">{selected.subject}</p>
            </div>
            <div>
              <h3 className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-2">Details</h3>
              <pre className="text-sm text-foreground/80 whitespace-pre-wrap leading-relaxed bg-muted/30 border border-border rounded-xl p-4 max-h-96 overflow-y-auto font-sans">
                {selected.body}
              </pre>
            </div>
          </div>
```

With:
```tsx
          <div className="space-y-4 flex-1 overflow-y-auto min-h-0">
            {(() => {
              const parsed = parseEscalationBody(selected.body);
              return (
                <>
                  <div className="flex flex-wrap gap-3">
                    <div className="flex-1 min-w-[200px] p-3 rounded-lg bg-muted/30 border border-border">
                      <p className="text-[10px] font-semibold text-muted-foreground uppercase tracking-wider mb-1">Customer</p>
                      <p className="text-sm font-medium text-foreground">{selected.customer_name}</p>
                    </div>
                    {parsed.email && (
                      <div className="flex-1 min-w-[200px] p-3 rounded-lg bg-muted/30 border border-border">
                        <p className="text-[10px] font-semibold text-muted-foreground uppercase tracking-wider mb-1">Email</p>
                        <p className="text-sm text-foreground">{parsed.email}</p>
                      </div>
                    )}
                    <div className="flex-1 min-w-[200px] p-3 rounded-lg bg-muted/30 border border-border">
                      <p className="text-[10px] font-semibold text-muted-foreground uppercase tracking-wider mb-1">Phone</p>
                      <p className="text-sm font-mono text-foreground">{parsed.phone || selected.customer_id}</p>
                    </div>
                    <div className="flex-1 min-w-[200px] p-3 rounded-lg bg-muted/30 border border-border">
                      <p className="text-[10px] font-semibold text-muted-foreground uppercase tracking-wider mb-1">Reason</p>
                      <p className="text-sm font-medium text-foreground">{cleanSubject(selected.subject)}</p>
                    </div>
                  </div>
                  {parsed.chatLog && (
                    <div>
                      <h3 className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-2">Conversation</h3>
                      <pre className="text-sm text-foreground/80 whitespace-pre-wrap leading-relaxed bg-muted/30 border border-border rounded-xl p-4 max-h-96 overflow-y-auto font-sans">
                        {parsed.chatLog}
                      </pre>
                    </div>
                  )}
                </>
              );
            })()}
          </div>
```

### Edit 3 — Smart compose pre-fill for full escalations (line 456-462)

Replace the `setCompose` call in the detail view button:
```tsx
              {selected && (
                <button
                  onClick={() => setCompose({
                    to: "",
                    subject: "",
                    body: "",
                  })}
```

With:
```tsx
              {selected && (
                <button
                  onClick={() => {
                    const parsed = parseEscalationBody(selected.body);
                    setCompose({
                      to: isSemi(selected.notification_type) ? "" : parsed.email,
                      subject: isSemi(selected.notification_type) ? "" : `Re: ${cleanSubject(selected.subject)}`,
                      body: "",
                    });
                  }}
```

### Edit 4 — Same for openDetail compose (line 95-99)

Replace:
```tsx
        setCompose({
          to: "",
          subject: "",
          body: "",
        });
```

With:
```tsx
        const parsed = parseEscalationBody(esc.body);
        setCompose({
          to: isSemi(esc.notification_type) ? "" : parsed.email,
          subject: isSemi(esc.notification_type) ? "" : `Re: ${cleanSubject(esc.subject)}`,
          body: "",
        });
```

## Tests
1. `parseEscalationBody` extracts email from "Email: foo@bar.com" in body text
2. `parseEscalationBody` extracts phone from "WhatsApp: 59996881585"
3. `parseEscalationBody` extracts chat log after "=== CHAT LOG ==="
4. `cleanSubject` turns "[ESCALATION] NO-REF - Name (WhatsApp: ...) - complaint" into "Complaint"
5. Detail view shows Customer, Email, Phone, Reason cards (not raw dump)
6. Full escalation compose pre-fills To with customer email and Subject with "Re: Complaint"
7. Semi escalation compose still opens empty (no To/Subject)
8. Body is always empty on compose open

## Success Condition
Escalation detail shows clean info cards. Full escalation compose opens with customer email in To, clean subject in Subject, empty body. Semi escalation compose still just shows textarea.

## Rollback
Revert Escalations.tsx.
