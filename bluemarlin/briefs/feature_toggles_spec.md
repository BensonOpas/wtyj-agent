# BlueMarlin — Feature Toggles

What can be turned on or off per client. We control these, not the client.
Changing them requires zero code changes — just update the client config.

This describes the ideas. Not the code structure. If the implementation
changes, these ideas still hold.

---

## Booking flow

The big one. Determines whether the system handles bookings automatically
or just qualifies the lead and hands off to a human.

When ON: full booking loop. Collect details, validate, check availability,
hold a slot, confirm, generate a reference, create calendar event, log
to Sheets. This is what charters and tours use.

When OFF: the AI still answers questions, still uses the FAQ, still has
conversations. But when the customer wants to book, the AI collects
relevant info first (what they want, when, how many people, any
specifics) and THEN creates an escalation with all that context so a
human can take over with everything they need. The AI qualifies the
lead — the human closes it.

Calendar events and Sheets logging always happen when booking is on.
No separate toggles for those — they come with the booking flow.

---

## Payment

Some businesses charge upfront. Some take a deposit. Some collect at
the location. Some don't involve money at all.

The system adapts based on what's configured. If the business charges
upfront, a payment link is generated. If there's no payment involved,
the confirmation just says you're confirmed — no link, no money talk.

Already built.

---

## Availability model

When booking is on, the system needs to know how to check if there's
space. Different businesses work differently:

Fixed time slots with capacity — set times, max people per slot.
Charters, restaurants, tours, fitness classes. Built today.

Open schedule blocked by duration — operating hours, each appointment
takes a set time, one person per resource. Salons, clinics. Future.

Date range with inventory — X units available, customer picks start
and end dates. Car rentals, vacation rentals. Future.

No check — just book it without verifying. Simple businesses. Future.

We build each model when a client needs it. Not before.

---

## Channels

Which communication channels are active for each client. Not every
client uses every channel.

Options: email, WhatsApp, Instagram DMs, Facebook DMs.

A restaurant might only want WhatsApp. A real estate agency might want
email plus WhatsApp plus Instagram DMs. A charter might use everything.

Each channel is either on or off per client. If it's off, the system
doesn't process messages from that channel for that client.

This also connects to which channels can handle bookings vs which are
Q&A only. Email and WhatsApp can run the full booking flow. DMs are
Q&A plus escalation. The booking channels and Q&A channels might be
different per client.

---

## Content and social media

Some clients want AI-generated social media content (captions, graphics,
scheduled posts). Others don't care about social media at all.

Simple on or off per client. When on, the content pipeline generates
drafts, the operator approves them, and they get published to whatever
platforms the client has connected. When off, the whole content pipeline
is inactive for that client.

Which platforms they publish to is determined by which accounts they've
connected in Zernio, not by a toggle.

---

## Escalation routing

When something needs a human, where does it go? Different clients have
different setups.

Options might include: email to the owner, WhatsApp message to the
owner, dashboard notification only, or some combination.

A one-person operation might want everything on their WhatsApp. A
bigger business might want escalations to go to a specific email
address and also show up in the dashboard.

This is about where the notification lands when the AI says "I need
a human for this."

---

## Terminology

Every business calls things differently. The AI needs to use the right
words in conversations.

A charter has trips and guests and departures. A restaurant has
reservations and diners and seatings. A salon has appointments and
clients and time slots. A real estate agency has viewings and
prospects and properties.

The client config tells the system what vocabulary to use. The AI reads
these labels and uses them naturally in conversation. Change the config
and the AI immediately starts saying "reservation" instead of "booking."

---

## Language

Which languages the AI supports for each client. A charter in Curacao
needs English, Dutch, German, Spanish. A local barbershop might only
need English and Papiamentu. The AI responds in whatever language the
customer writes in, but only from the supported list.

---

## What's built vs what needs building

Built:
- Payment toggle
- Fixed time slot availability
- Escalation system
- Q&A without booking (DM agent)
- Multi-language support

Needs building:
- Booking flow toggle (on/off, with qualify-then-escalate when off)
- Terminology system
- Channel toggle (which channels active per client)
- Content toggle (on/off per client)
- Escalation routing (where notifications go)
- Random booking reference (remove charter-specific prefix)
- Generic booking summary
- Open schedule availability model (when a salon client arrives)
- Date range availability model (when a rental client arrives)
