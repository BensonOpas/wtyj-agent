# bluemarlin/agents/marina/payment_stub.py
# Last modified: Brief 066
# Purpose: Payment stub — demo.pay links only
import hashlib
import json
import os
from datetime import datetime

PAYMENT_STATE_FILE = "payment_state.json"


def _load():
    if not os.path.exists(PAYMENT_STATE_FILE):
        return {"payments": {}}
    with open(PAYMENT_STATE_FILE, "r") as f:
        return json.load(f)


def _save(data):
    with open(PAYMENT_STATE_FILE, "w") as f:
        json.dump(data, f, indent=2)


def generate_payment_link(booking_ref: str, amount_usd: int) -> dict:
    """
    Deterministic payment link generator.
    One booking_ref -> exactly one payment link.
    """

    state = _load()

    if booking_ref in state["payments"]:
        return state["payments"][booking_ref]

    raw = f"{booking_ref}|{amount_usd}"
    payment_id = hashlib.sha256(raw.encode()).hexdigest()[:12]

    link = f"https://demo.pay/bluemarlin/{payment_id}"

    payment_record = {
        "payment_id": payment_id,
        "booking_ref": booking_ref,
        "amount_usd": amount_usd,
        "status": "pending",
        "created_at": datetime.utcnow().isoformat()
    }

    state["payments"][booking_ref] = payment_record
    _save(state)

    return payment_record


def mark_paid(booking_ref: str):
    state = _load()
    if booking_ref in state["payments"]:
        state["payments"][booking_ref]["status"] = "paid"
        _save(state)
        return True
    return False
