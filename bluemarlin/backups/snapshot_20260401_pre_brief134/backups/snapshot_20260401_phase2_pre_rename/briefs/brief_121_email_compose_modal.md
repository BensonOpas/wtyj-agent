# BRIEF 121 — Email Client Button Opens Compose Modal
**Status:** Draft | **Depends on:** Brief 119 (complete) | **Blocks:** —

**Files:**
- `~/Projects/wetakeyourjob-dashboard/artifacts/dashboard/src/pages/Messages.tsx`

## Context
The "Email client" button in the conversation detail view (line 437) calls `openEmailCompose()` which opens Gmail directly, bypassing the floating compose modal that has the Suggest Reply button. The compose modal is only triggered from the list view hover icon (`handleMailClick`). This means the Suggest Reply feature (Brief 119) is unreachable from the detail view.

## Why This Approach
One-line fix. Change the detail view button to set compose state (opens the modal) instead of opening Gmail directly. The modal already has "Open in Gmail" as its send action, so the flow becomes: click Email client → compose modal opens → optionally click Suggest Reply → edit → Open in Gmail. Same end result, but with the suggest step available.

## Source Material

**Replace line 435-438 in Messages.tsx:**

Current:
```tsx
onClick={() => {
    const customerName = (detail?.booking_state?.fields?.customer_name as string) || selectedPhone;
    openEmailCompose(emailSettings, "", `Blue Marlin Tours — ${customerName}`, `Hi ${customerName},\n\nThank you for contacting Blue Marlin Tours Curaçao.\n\n`);
  }}
```

Replace with:
```tsx
onClick={() => {
    const customerName = (detail?.booking_state?.fields?.customer_name as string) || selectedPhone;
    setCompose({
      to: "",
      subject: `Blue Marlin Tours — ${customerName}`,
      body: `Hi ${customerName},\n\nThank you for contacting Blue Marlin Tours Curaçao.\n\n`,
    });
  }}
```

Also change the button label (line 441):
Current: `<Mail className="w-3.5 h-3.5" /> Email client`
Replace with: `<Mail className="w-3.5 h-3.5" /> Compose email`

## Tests
1. No `openEmailCompose` call inside the detail view email button (line 435-438)
2. `setCompose` is called instead with `to`, `subject`, `body` keys
3. Button text is "Compose email" not "Email client"

## Success Condition
Clicking the email button in conversation detail view opens the floating compose modal with Suggest Reply button, instead of going straight to Gmail.

## Rollback
Revert Messages.tsx.
