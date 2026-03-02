import hashlib
import json
import os

STATE_FILE = "state.json"


def _load_state():
    if not os.path.exists(STATE_FILE):
        return {"processed_hashes": []}

    with open(STATE_FILE, "r") as f:
        return json.load(f)


def _save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def generate_content_hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def has_been_processed(content: str) -> bool:
    state = _load_state()
    content_hash = generate_content_hash(content)
    return content_hash in state["processed_hashes"]


def mark_as_processed(content: str):
    state = _load_state()
    content_hash = generate_content_hash(content)

    if content_hash not in state["processed_hashes"]:
        state["processed_hashes"].append(content_hash)
        _save_state(state)
