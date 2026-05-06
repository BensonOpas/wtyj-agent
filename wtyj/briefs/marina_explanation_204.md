# EXPLANATION 204 — Add Gmail app-password auth path to email_adapter.py (IMAP + SMTP)

## In one sentence
The email reader and sender now know how to talk to Gmail mailboxes too, so the unboks tenant can finally read and reply to emails sent to hello@unboks.org once the operator drops the password onto the server.

## What's changing and why

Before this change, the part of the system that reads incoming email and sends replies only knew one way to log in: the corporate Microsoft Outlook handshake used by BlueMarlin and Adamus. That handshake doesn't work for Gmail-style mailboxes, so the unboks mailbox (which lives on Google Workspace) was unreachable. Calvin, the unboks AI agent, had no way to actually receive prospect emails or write back.

After this change, the same code can speak either dialect. Which one it uses is decided automatically per tenant by a single signal: whether an "email password" value has been set in that tenant's environment file. If a password is set, the system treats the mailbox as Gmail and logs in with the simple username-and-password method that Google calls an "app password." If no password is set, nothing changes — the system uses the existing Microsoft Outlook login the way it always has. BlueMarlin and Adamus do not set this password, so their behaviour is identical to before. Once the operator pastes the unboks password onto the server and restarts the unboks container, Calvin starts polling hello@unboks.org and can reply from it.

## Step by step — what the code does now

READING EMAIL (the inbox connection)

When the system opens a connection to a mailbox to look for new mail, it now first checks whether an email password has been configured for this tenant. If a password is present, the system removes any spaces from it (Google displays app passwords in four groups of four characters separated by spaces, and the operator might paste it in either form), connects to Google's inbox server using a secure connection on the standard inbox port, and logs in with the mailbox address and the cleaned password. The connection is then handed back to the rest of the system, which reads incoming mail exactly as it did before.

If no password has been configured, the system falls through to the existing path: it asks Microsoft for an access token, connects to the Outlook inbox server, and logs in with the special token-based handshake. This is the unchanged BlueMarlin and Adamus path.

SENDING EMAIL (composing and dispatching a reply)

When the system needs to send a reply, it first builds the outgoing message — sender name, recipient, subject, message ID, threading headers if this is part of an existing conversation, and the reply body. That message-building step is identical to before and runs regardless of which mailbox provider is being used.

Once the message is ready, the system again checks for the email password. If one is present, it strips the spaces, opens a connection to Google's outbound mail server on the standard outbound port, performs the standard secure-channel handshake, logs in with the mailbox address and password, hands off the message, and closes the connection.

If no password is present, the system uses the existing path: ask Microsoft for an outbound access token, open a connection to the Outlook outbound server, perform the secure-channel handshake, send the special token-based authentication command, hand off the message, and close the connection. This path is byte-for-byte the same as before — just relocated below the new Gmail branch.

THE SWITCH

There is no separate "which provider?" setting. The presence of the password value is the switch. This works because Microsoft's enterprise mailboxes never use static passwords for these protocols — they always use the token handshake — so a password being set can only mean one thing: this mailbox is a Gmail mailbox.

OPERATOR STEP AFTER DEPLOY

The code change alone does nothing visible until the operator manually adds two lines to the unboks tenant's environment file on the server (the mailbox address and the 16-character password) and restarts the unboks container. Once that's done, Calvin starts polling the Gmail inbox and can send replies from it.

## Edge cases

- If the operator pastes the password with spaces (the way Google displays it), the system removes them automatically. Both formats work.
- If the operator sets the email password on a tenant that should be using Microsoft (a typo in the wrong env file), that tenant's mailbox connection will try Gmail and fail with an authentication error. No data corruption — the tenant just won't process email until the wrong value is removed.
- If Google's workspace administrator has disabled app passwords entirely (a centrally-controlled policy), the login will fail with an "invalid credentials" error within 30 seconds of container startup. The fix at that point is either to re-enable app passwords for that user or to add a more involved Google login path in a future change. The brief calls this out as a known pivot path, not a current problem.
- The "From" line on outgoing email still reads "Marina <mailbox-address>" regardless of which tenant is sending. That means Calvin's emails from hello@unboks.org will be displayed as coming from "Marina." This is a known cosmetic mismatch that the brief explicitly defers to a follow-up — the immediate goal is just "Calvin can send any reply at all." Recipients see the right email address; only the display name is wrong.
- If the email password is set but the mailbox address is not, the Google login will fail. The existing graceful-exit guard from a much earlier brief catches this and the email subsystem shuts down cleanly without crashing the container.
- The two ports used (the standard inbox port and the standard outbound port with secure-channel upgrade) happen to be the same for both Google and Microsoft, so no separate port settings were needed.

## What did NOT change

Marina's prompt, the booking flow, customer data handling, the message-building logic for outgoing email (sender name, threading headers, subject, body assembly), and the BlueMarlin and Adamus email paths are all untouched. The Microsoft Outlook login path was relocated within the sender function but its behaviour is identical line-for-line. No other file in the system was modified — only the email adapter and a new test file. The unboks tenant gains a new capability; the existing tenants behave exactly as they did yesterday.
