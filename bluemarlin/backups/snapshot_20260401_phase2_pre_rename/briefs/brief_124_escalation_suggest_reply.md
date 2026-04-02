# BRIEF 124 — Suggest Reply on Escalations + Remove Email from Messages
**Status:** Draft | **Depends on:** Brief 123 (revert), Brief 119 (backend) | **Blocks:** —

**Files:**
- `~/Projects/wetakeyourjob-dashboard/artifacts/dashboard/src/pages/Messages.tsx`
- `~/Projects/wetakeyourjob-dashboard/artifacts/dashboard/src/pages/Escalations.tsx`

## Context
Email compose belongs on Escalations, not Messages. Messages is read-only (WhatsApp thread viewer). Brief 123 wrongly re-added email compose to Messages. SR was right to remove it.

Escalations page already has an email compose modal (SR built it) but:
1. The "Email customer" button in detail view (line 398) calls `openEmailCompose` directly — bypasses the compose modal, goes straight to Gmail
2. The compose modal has no Suggest Reply button

Fix: Remove email compose from Messages, fix the Escalations detail button to open the modal, add Suggest Reply to the Escalations compose modal.

## Why This Approach
Messages = view only. Escalations = action center. The suggest-reply backend endpoint (Brief 119) works with any phone number. The Escalations page has the customer phone in the escalation data — we extract it and pass it to `suggestReply.mutateAsync(phone)`.

## Source Material

### Messages.tsx — Revert Brief 123 additions

Remove from imports:
- `useSuggestReply` from hooks import
- `useEmailSettings, openEmailCompose` import line
- `Mail, X, Send, Wand2` from lucide imports

Remove `"Escalated"` from FILTERS array (back to `["All", "Active"]`).

Remove `ComposeState` interface.

Remove from `ConversationRowProps`: `emailEnabled`, `onMailClick`.
Remove from `ConversationRow` destructure: `emailEnabled`, `onMailClick`.

Remove the mail icon button from ConversationRow (the `{emailEnabled && (` block).

Remove from component body: `suggestReply` hook, `compose` state, `emailSettings`, `handleMailClick`, `sendCompose`, Escalated tabCount/filter logic.

Remove the entire floating compose modal JSX.

Remove "Compose email" button from detail view header.

Remove `emailEnabled` and `onMailClick` props from both `<ConversationRow` calls.

### Escalations.tsx — Fix detail button + add Suggest Reply

**Edit 1 — Add `useSuggestReply` import (line 3):**
Change: `import { useEscalations, useEscalationMutations } from "@/hooks/use-bluemarlin";`
To: `import { useEscalations, useEscalationMutations, useSuggestReply } from "@/hooks/use-bluemarlin";`

**Edit 2 — Add `Wand2` to lucide import (line 11):**
Change: `X, Send,`
To: `X, Send, Wand2,`

**Edit 3 — Add suggestReply hook (after line 61):**
After `const { settings: emailSettings } = useEmailSettings();` add:
```tsx
const suggestReply = useSuggestReply();
```

**Edit 4 — Fix "Email customer" button in detail view (lines 398-409):**
Replace `openEmailCompose(...)` call with `setCompose({...})`:

Current (line 398-409):
```tsx
{emailSettings.enabled && selected && (
  <button
    onClick={() => openEmailCompose(
      emailSettings,
      "",
      `Blue Marlin Tours — Re: ${selected.subject}`,
      `Hi ${selected.customer_name},\n\nThank you for reaching out...`
    )}
    className="..."
  >
    <Mail className="w-3.5 h-3.5" /> Email customer
  </button>
)}
```

Replace with:
```tsx
{emailSettings.enabled && selected && (
  <button
    onClick={() => setCompose({
      to: "",
      subject: `Blue Marlin Tours — Re: ${selected.subject}`,
      body: `Hi ${selected.customer_name},\n\nThank you for reaching out. We're looking into your request regarding "${selected.subject}" and will get back to you shortly.\n\nBest regards,\nBlue Marlin Tours Curaçao\n`,
    })}
    className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium text-foreground/60 hover:text-foreground bg-muted/40 hover:bg-muted border border-border transition-colors"
  >
    <Mail className="w-3.5 h-3.5" /> Compose email
  </button>
)}
```

**Edit 5 — Add Suggest Reply to compose modal (line 233):**
Replace the `<div className="flex justify-end pt-1">` block (lines 233-238) with:
```tsx
<div className="flex justify-between items-center pt-1">
  <button
    onClick={async () => {
      if (!selected?.customer_id) return;
      try {
        const result = await suggestReply.mutateAsync(selected.customer_id);
        setCompose(prev => prev ? { ...prev, subject: result.subject, body: result.body } : prev);
      } catch {}
    }}
    disabled={suggestReply.isPending || !selected?.customer_id}
    className="flex items-center gap-1.5 px-3 py-2 rounded-lg text-xs font-semibold border border-dashed border-primary/40 text-primary hover:bg-primary/10 hover:border-primary/60 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
  >
    <Wand2 className="w-3.5 h-3.5" />
    {suggestReply.isPending ? "Thinking…" : "Suggest Reply"}
  </button>
  <button onClick={sendCompose} disabled={!compose.to} className="flex items-center gap-2 px-4 py-2 rounded-lg bg-sky-600 hover:bg-sky-500 disabled:opacity-40 disabled:cursor-not-allowed text-white text-sm font-semibold transition-colors">
    <Send className="w-3.5 h-3.5" />
    Open in {emailSettings.client === "gmail" ? "Gmail" : "Mail App"}
  </button>
</div>
```

Note: The phone number for Suggest Reply comes from `selected.customer_id` which is the WhatsApp phone number (verified: escalation records have `customer_id` = phone, e.g. "59996881585"). The `useSuggestReply` hook already has `onError: toast.error(...)` so API failures show a toast. The `catch {}` only covers the async wrapper — the hook's error handler fires for API errors. The button is disabled when `customer_id` is missing.

## Tests
1. Messages.tsx has no `useSuggestReply`, no `useEmailSettings`, no `ComposeState`, no `Mail` import, no `Wand2`
2. Messages FILTERS is `["All", "Active"]` only
3. Escalations.tsx imports `useSuggestReply` and `Wand2`
4. Escalations detail view "Compose email" button calls `setCompose` not `openEmailCompose`
5. Escalations compose modal has Suggest Reply button with `Wand2` icon
6. Escalations compose modal has "Open in Gmail" button

## Success Condition
Messages page is read-only (no email compose). Escalations detail view opens compose modal (not Gmail directly). Compose modal has Suggest Reply + Open in Gmail.

## Rollback
Revert both files.
