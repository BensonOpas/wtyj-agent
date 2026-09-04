# Tracy introduction on a new chat
**Status:** Deployed and verified | **Files:** mermaid_understanding.py | **Depends on:** flat pickup release 8053f5d | **Blocks:** welcoming first reply

## Context
The user's screenshot shows a new booking enquiry receiving a greeting and date question without Tracy introducing herself. The user requested a short introduction before the date question.

## Why This Approach
Add a narrowly scoped first-reply instruction to the existing single-model prompt. Reject an unconditional text prefix, which would repeat introductions and could ask for a date already provided. Preserve natural translation and question-first behavior.

## Instructions
Welcome new guests to Mermaid and introduce Tracy briefly. Ask for the trip date only when missing; otherwise ask the next missing detail. Answer an initial guest question after the introduction. Do not repeat the introduction in an ongoing conversation or reservation.

## Tests
Isolated real-model replay of the screenshot's enquiry, a continuation giving a date, and a fresh enquiry that already includes a date. Provider sends remain disabled.

## Success Condition
The first booking reply introduces Tracy once and asks only for information still missing.

## Rollback
Restore the previous Mermaid understanding prompt while preserving all live configuration, chat data and concurrent status-control changes.

## Verification
Isolated real-model replay passed three turns with zero provider sends. The screenshot enquiry returned: "Hi, welcome to Mermaid! I'm Tracy. What date are you thinking of for the trip?" The continuation asked party size without repeating the introduction. A fresh enquiry already including a date introduced Tracy and asked party size instead of the date. Source commit `6e3cee8`; prompt SHA256 `44f95f6f7fffa9ea63e156036e1a530b54fd9895dbebe151987e3d9e948ba4e8`. Deployment is coordinated with the parallel Mermaid status-control repair so neither change replaces the other.

## Live verification
Deployed with the coordinated status repair in `wtyj-agent:tracy-status-9adae23`, image digest `sha256:1a3d68277f41c3badb621fde940616d8861e9513d00ae31d2f1b58e56feaa5b1`. Independently verified the exact introduction prompt SHA256 in the live container, public health OK, and maintenance marker removed. The isolated replay required no customer messages.
