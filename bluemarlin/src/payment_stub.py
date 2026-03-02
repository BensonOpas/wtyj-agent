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


def generate_payment_link(event_id: str, amount_usd: int) -> dict:
    """
    Deterministic payment link generator.
    One event_id -> exactly one payment link.
    """

    state = _load()

    if event_id in state["payments"]:
        return state["payments"][event_id]

    raw = f"{event_id}|{amount_usd}"
    payment_id = hashlib.sha256(raw.encode()).hexdigest()[:12]

    link = f"https://demo.pay/bluemarlin/{payment_id}"

    payment_record = {
        "payment_id": payment_id,
        "event_id": event_id,
        "amount_usd": amount_usd,
        "status": "pending",
        "created_at": datetime.utcnow().isoformat()
    }

    state["payments"][event_id] = payment_record
    _save(state)

    return payment_record


def mark_paid(event_id: str):
    state = _load()
    if event_id in state["payments"]:
        state["payments"][event_id]["status"] = "paid"
        _save(state)
        return True
    return False
