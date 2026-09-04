"""Mermaid-only durable recovery; no provider sends or business mutations."""

import hashlib
import json
import os
import re
import sqlite3
import time
import unicodedata
from datetime import datetime, timezone

from shared import state_registry


MAX_ATTEMPTS = 3
TRANSIENT_DELAY_SECONDS = 5
OPERATOR_COOLDOWN_SECONDS = 900
GENERATION_LEASE_SECONDS = 90
LOCALES = ("en", "nl", "de", "es", "pap", "pt")

# Accepted outage-copy exception. Papiamentu remains subject to native review.
FAILURE_COPY = {
    "en": "I couldn't answer that just now. Your details are saved. Please try again shortly, or ask to speak to a person.",
    "nl": "Ik kon je net niet antwoorden. Je gegevens zijn opgeslagen. Probeer het zo nog eens of vraag om een medewerker.",
    "de": "Ich konnte gerade nicht antworten. Ihre Angaben sind gespeichert. Versuchen Sie es gleich noch einmal oder bitten Sie um einen Mitarbeiter.",
    "es": "No pude responderte en este momento. Tus datos están guardados. Inténtalo de nuevo en un momento o pide hablar con una persona.",
    "pap": "Mi no a logra kontestá bo aworaki. Bo datonan ta wardá. Purba atrobe den un ratu òf pidi pa papia ku un hende di e tim.",
    "pt": "Não consegui responder agora. Seus dados estão salvos. Tente novamente em instantes ou peça para falar com uma pessoa.",
}
HUMAN_COPY = {
    "en": "Your request is queued for Mermaid's team. Your details are saved, and I can still help with general trip questions.",
    "nl": "Je verzoek staat klaar voor het team van Mermaid. Je gegevens zijn opgeslagen en ik kan algemene vragen over de trip blijven beantwoorden.",
    "de": "Ihre Anfrage wartet auf die Prüfung durch das Mermaid-Team. Ihre Angaben sind gespeichert und ich kann weiterhin allgemeine Fragen zum Ausflug beantworten.",
    "es": "Tu solicitud está en espera de revisión por el equipo de Mermaid. Tus datos están guardados y puedo seguir respondiendo preguntas generales sobre la excursión.",
    "pap": "Bo petishon ta warda pa e tim di Mermaid revisá. Bo datonan ta wardá i mi por sigui yuda ku preguntanan general tokante e biahe.",
    "pt": "Seu pedido está aguardando análise da equipe da Mermaid. Seus dados estão salvos e posso continuar respondendo a perguntas gerais sobre o passeio.",
}

# Issue #342 explicitly authorizes this narrow offline human-request route.
# Whole-message requests only; ordinary mentions of people do not match.
_HUMAN_REQUESTS = {
    "en": r"(?:please )?(?:(?:i (?:want|need|would like) to|can i|could i) (?:speak|talk|chat) (?:to|with) (?:a |the )?(?:real person|human|person|staff member|team)|i (?:want|need|would like) (?:a |the )?(?:human|real person|staff member)|(?:speak|talk) (?:to|with) (?:a |the )?(?:human|real person|team))(?: please)?",
    "nl": r"(?:ik wil|ik wil graag|mag ik|kan ik) (?:met )?(?:een |de )?(?:echte )?(?:medewerker|persoon|mens|iemand van het team) (?:spreken|praten)(?: alstublieft| alsjeblieft)?",
    "de": r"(?:ich mochte|ich will|kann ich|ich wurde gern) (?:mit )?(?:einem |einer |dem )?(?:echten )?(?:mitarbeiter|menschen|person|team) (?:sprechen|reden)(?: bitte)?",
    "es": r"(?:quiero|quisiera|puedo) (?:hablar|conversar) con (?:una |un |el )?(?:persona(?: de verdad| real)?|humano|agente|equipo)(?: por favor)?",
    "pap": r"(?:mi ke|mi kier|mi ta desea|mi por) (?:papia|habla) ku (?:un |e )?(?:hende(?: di e tim| di e team| berdadero| real)?|persona|tim)(?: por fabor)?",
    "pt": r"(?:quero|gostaria de|posso) (?:falar|conversar) com (?:uma |um |a )?(?:pessoa(?: de verdade| real)?|humano|atendente|equipe)(?: por favor)?",
}


def explicit_human_request(text: str) -> str | None:
    normalized = "".join(c for c in unicodedata.normalize("NFKD", str(text).casefold()) if not unicodedata.combining(c))
    normalized = " ".join(re.sub(r"[^\w\s]", " ", normalized).split())
    return next((locale for locale, pattern in _HUMAN_REQUESTS.items() if re.fullmatch(pattern, normalized)), None)


def error_metadata(exc: Exception | None = None) -> dict:
    status = getattr(exc, "status_code", None)
    body = getattr(exc, "body", None)
    error = body.get("error", body) if isinstance(body, dict) else {}
    kind = str(error.get("type") or "") if isinstance(error, dict) else ""
    message = str(error.get("message") or "").casefold() if isinstance(error, dict) else ""
    if kind in {"billing_error", "insufficient_quota"} or any(value in message for value in ("credit balance", "billing", "insufficient quota", "quota exhausted")):
        return {"kind": "billing", "retryable": False}
    if status in {401, 403} or kind in {"authentication_error", "permission_error"}:
        return {"kind": "credentials", "retryable": False}
    if isinstance(status, int) and 400 <= status < 500 and status not in {408, 409, 429}:
        return {"kind": "request_rejected", "retryable": False}
    return {"kind": "transient" if exc is not None else "invalid_response", "retryable": True}


def _conn():
    conn = state_registry._get_conn()
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS mermaid_model_events (
            conversation_id TEXT NOT NULL, message_id TEXT NOT NULL,
            status TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0,
            error_kind TEXT NOT NULL DEFAULT '', retryable INTEGER NOT NULL DEFAULT 1,
            retry_at REAL NOT NULL DEFAULT 0, notice_sent INTEGER NOT NULL DEFAULT 0,
            response_json TEXT NOT NULL DEFAULT '{}', created_at REAL NOT NULL,
            PRIMARY KEY (conversation_id, message_id)
        );
        CREATE TABLE IF NOT EXISTS mermaid_model_circuit (
            singleton INTEGER PRIMARY KEY CHECK(singleton=1),
            blocked_until REAL NOT NULL, error_kind TEXT NOT NULL,
            credential_hash TEXT NOT NULL, probe_id TEXT NOT NULL DEFAULT '',
            failed_at REAL NOT NULL
        );
    """)
    return conn


def _metadata(row, *, retry_at=None, kind=None, retryable=None) -> dict:
    return {
        "conversation_id": row["conversation_id"], "message_id": row["message_id"],
        "kind": kind or row["error_kind"],
        "retryable": bool(row["retryable"]) if retryable is None else retryable,
        "retry_at": row["retry_at"] if retry_at is None else retry_at,
        "send_notice": not row["notice_sent"] and row["status"] not in {"generating", "superseded"},
        "superseded": row["status"] == "superseded",
    }


def _failure(locale, metadata):
    return {
        "generation_failed": True, "generation_failure": metadata,
        "language": locale,
        "reply": FAILURE_COPY[locale] if metadata["send_notice"] else "",
    }


def _valid_schema_value(value, schema, *, allow_metadata=False):
    """Validate supplied contract values; legacy omitted fields stay optional."""
    value_type = schema.get("type")
    if value_type == "object":
        if not isinstance(value, dict):
            return False
        properties = schema.get("properties", {})
        for key, item in value.items():
            if key in properties:
                if not _valid_schema_value(item, properties[key]):
                    return False
            elif schema.get("additionalProperties") is False and not allow_metadata:
                return False
    elif value_type == "string":
        if not isinstance(value, str):
            return False
    elif value_type == "boolean":
        if type(value) is not bool:
            return False
    elif value_type == "integer":
        if type(value) is not int:
            return False
        if "minimum" in schema and value < schema["minimum"]:
            return False
        if "maximum" in schema and value > schema["maximum"]:
            return False
    else:
        return False
    return "enum" not in schema or value in schema["enum"]


def _valid_result(result, guest_text=""):
    from agents.social.mermaid_understanding import MERMAID_TOOL, has_server_owned_reply

    return (
        isinstance(result, dict) and not result.get("generation_failed")
        and isinstance(result.get("reply"), str)
        and isinstance(result.get("mermaid_action"), str)
        # Marina appends compatibility metadata outside the Mermaid tool schema.
        # Only that top-level metadata is tolerated; declared/nested values
        # always use the model's single authoritative schema.
        and _valid_schema_value(result, MERMAID_TOOL["input_schema"], allow_metadata=True)
        and (bool(result["reply"].strip()) or has_server_owned_reply(result, guest_text))
    )


def _alert(conn, kind, now):
    timestamp = datetime.fromtimestamp(now, timezone.utc).isoformat()
    existing = conn.execute("SELECT id FROM pending_notifications WHERE notification_type='technical' AND customer_id='mermaid:model-provider' AND status IN ('pending','sent') ORDER BY id DESC LIMIT 1").fetchone()
    body = "TRACY could not complete model generation. Cause: " + kind + ". Saved guest details are preserved. Explicit human requests remain available."
    if existing:
        conn.execute("UPDATE pending_notifications SET body=? WHERE id=?", (body, existing[0]))
    else:
        conn.execute("INSERT INTO pending_notifications (notification_type,channel,customer_id,customer_name,subject,body,status,created_at) VALUES ('technical','system','mermaid:model-provider','TRACY','TRACY model service needs attention',?,'pending',?)", (body, timestamp))


def generate(message: dict, locale: str, call_model) -> dict:
    """One bounded attempt per invocation; the existing durable worker retries."""
    locale = locale if locale in LOCALES else "en"
    explicit = explicit_human_request(message.get("text", ""))
    if explicit:
        return {"language": explicit, "understanding_source": "explicit_human_request", "mermaid_action": "request_human", "requires_human": True, "has_open_question": False, "fields": {}, "reply": HUMAN_COPY[explicit]}
    conversation = str(message.get("from") or "")
    message_id = str(message.get("message_id") or "")
    # Every production inbound has an ID. A direct caller without one receives
    # a request-local key rather than sharing another message's retry budget.
    if not message_id:
        message_id = "direct-" + os.urandom(12).hex()
    now = time.time()
    credential_hash = hashlib.sha256(os.environ.get("ANTHROPIC_API_KEY", "").encode()).hexdigest()
    conn = _conn()
    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("INSERT OR IGNORE INTO mermaid_model_events (conversation_id,message_id,status,created_at) VALUES (?,?,'new',?)", (conversation, message_id, now))
        row = conn.execute("SELECT * FROM mermaid_model_events WHERE conversation_id=? AND message_id=?", (conversation, message_id)).fetchone()
        if row["status"] == "generated":
            conn.commit()
            return json.loads(row["response_json"])
        if row["status"] == "superseded" or row["attempts"] >= MAX_ATTEMPTS:
            conn.commit()
            return _failure(locale, _metadata(row, retryable=False))
        circuit = conn.execute("SELECT * FROM mermaid_model_circuit WHERE singleton=1").fetchone()
        if circuit and circuit["credential_hash"] != credential_hash:
            conn.execute("DELETE FROM mermaid_model_circuit")
            circuit = None
            if row["error_kind"] in {"credentials", "billing", "request_rejected"}:
                conn.execute("UPDATE mermaid_model_events SET retry_at=0 WHERE conversation_id=? AND message_id=?", (conversation, message_id))
                row = conn.execute("SELECT * FROM mermaid_model_events WHERE conversation_id=? AND message_id=?", (conversation, message_id)).fetchone()
        if row["retry_at"] > now or (circuit and circuit["blocked_until"] > now):
            retry_at = max(row["retry_at"], circuit["blocked_until"] if circuit else 0)
            kind = circuit["error_kind"] if circuit else row["error_kind"]
            retryable = kind not in {"billing", "credentials", "request_rejected"}
            conn.commit()
            return _failure(locale, _metadata(row, retry_at=retry_at, kind=kind, retryable=retryable))
        conn.execute("UPDATE mermaid_model_events SET status='generating',attempts=attempts+1,retry_at=? WHERE conversation_id=? AND message_id=?", (now + GENERATION_LEASE_SECONDS, conversation, message_id))
        attempt = row["attempts"] + 1
        probe_id = hashlib.sha256(f"{conversation}:{message_id}:{attempt}".encode()).hexdigest()
        if circuit:
            # During an outage allow one probe across concurrent conversations.
            conn.execute("UPDATE mermaid_model_circuit SET blocked_until=?,probe_id=? WHERE singleton=1", (now + GENERATION_LEASE_SECONDS, probe_id))
        conn.commit()
    finally:
        conn.close()
    try:
        result = call_model()
        if not _valid_result(result, str(message.get("text") or "")):
            failure = (result or {}).get("model_error") if isinstance(result, dict) else None
            failure = failure if isinstance(failure, dict) else error_metadata()
        else:
            failure = None
    except Exception as exc:
        failure = error_metadata(exc)
        result = {}
    conn = _conn()
    try:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("SELECT * FROM mermaid_model_events WHERE conversation_id=? AND message_id=?", (conversation, message_id)).fetchone()
        if row["status"] != "generating" or row["attempts"] != attempt:
            # A worker that outlived its lease cannot replace a newer result.
            metadata = _metadata(row, retryable=False)
            metadata.update(send_notice=False, superseded=True)
            conn.commit()
            return _failure(locale, metadata)
        if failure is None:
            conn.execute("UPDATE mermaid_model_events SET status='generated',response_json=?,retry_at=0 WHERE conversation_id=? AND message_id=?", (json.dumps(result, ensure_ascii=False), conversation, message_id))
            conn.execute("UPDATE mermaid_model_events SET status='superseded' WHERE conversation_id=? AND status IN ('failed','new') AND created_at<?", (conversation, row["created_at"]))
            conn.execute("DELETE FROM mermaid_model_circuit WHERE failed_at<=?", (now,))
            if not conn.execute("SELECT 1 FROM mermaid_model_circuit").fetchone():
                conn.execute("UPDATE pending_notifications SET status='resolved' WHERE notification_type='technical' AND customer_id='mermaid:model-provider' AND status IN ('pending','sent')")
            conn.commit()
            return result
        retryable = bool(failure.get("retryable")) and row["attempts"] < MAX_ATTEMPTS
        kind = str(failure.get("kind") or "transient")
        delay = TRANSIENT_DELAY_SECONDS * row["attempts"] if failure.get("retryable") else OPERATOR_COOLDOWN_SECONDS
        retry_at = time.time() + delay
        conn.execute("UPDATE mermaid_model_events SET status='failed',error_kind=?,retryable=?,retry_at=? WHERE conversation_id=? AND message_id=?", (kind, retryable, retry_at, conversation, message_id))
        if kind == "invalid_response":
            # The provider answered, but this event's structured output was
            # invalid. Keep its retry local so healthy guests can still reply.
            # A probe may clear only its own older outage, never a concurrent
            # newer provider failure or another worker's lease.
            cleared = conn.execute("DELETE FROM mermaid_model_circuit WHERE probe_id=? AND failed_at<=?", (probe_id, now)).rowcount
            if cleared and not conn.execute("SELECT 1 FROM mermaid_model_circuit").fetchone():
                conn.execute("UPDATE pending_notifications SET status='resolved' WHERE notification_type='technical' AND customer_id='mermaid:model-provider' AND status IN ('pending','sent')")
            updated = conn.execute("SELECT * FROM mermaid_model_events WHERE conversation_id=? AND message_id=?", (conversation, message_id)).fetchone()
            conn.commit()
            return _failure(locale, _metadata(updated))
        circuit = conn.execute("SELECT * FROM mermaid_model_circuit WHERE singleton=1").fetchone()
        if circuit and circuit["probe_id"] != probe_id and circuit["blocked_until"] > time.time():
            retry_at = max(retry_at, circuit["blocked_until"])
            if circuit["error_kind"] in {"billing", "credentials", "request_rejected"}:
                kind = circuit["error_kind"]
        conn.execute("INSERT INTO mermaid_model_circuit (singleton,blocked_until,error_kind,credential_hash,probe_id,failed_at) VALUES (1,?,?,?,'',?) ON CONFLICT(singleton) DO UPDATE SET blocked_until=excluded.blocked_until,error_kind=excluded.error_kind,credential_hash=excluded.credential_hash,probe_id='',failed_at=excluded.failed_at", (retry_at, kind, credential_hash, time.time()))
        _alert(conn, kind, time.time())
        updated = conn.execute("SELECT * FROM mermaid_model_events WHERE conversation_id=? AND message_id=?", (conversation, message_id)).fetchone()
        conn.commit()
        return _failure(locale, _metadata(updated))
    finally:
        conn.close()


def notice_sent(metadata):
    conn = _conn()
    try:
        conn.execute("UPDATE mermaid_model_events SET notice_sent=1 WHERE conversation_id=? AND message_id=?", (metadata["conversation_id"], metadata["message_id"]))
        conn.commit()
    finally:
        conn.close()


def defer_inbound(message_ids, processing_token, metadata):
    """CAS-release one complete batch with a future retry lease or honest failure."""
    ids = list(dict.fromkeys(message_ids))
    if not ids or not processing_token:
        return False
    retryable = metadata["retryable"] and not metadata.get("superseded")
    status = "recovering" if retryable else "ignored" if metadata.get("superseded") else "processing_failed"
    reason = "mermaid_model_superseded" if metadata.get("superseded") else "mermaid_model_" + metadata["kind"]
    lease = datetime.fromtimestamp(metadata["retry_at"], timezone.utc).isoformat() if retryable else ""
    conn = state_registry._get_conn()
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("BEGIN IMMEDIATE")
        placeholders = ",".join("?" for _ in ids)
        rows = conn.execute(f"SELECT message_id,status,processing_token FROM inbound_processing_events WHERE message_id IN ({placeholders})", ids).fetchall()
        if len(rows) != len(ids) or any(row["status"] != "processing" or row["processing_token"] != processing_token for row in rows):
            conn.rollback()
            return False
        conn.executemany("UPDATE inbound_processing_events SET status=?,reason=?,lease_expires_at=?,processing_token='',updated_at=? WHERE message_id=? AND processing_token=?", [(status, reason, lease, datetime.now(timezone.utc).isoformat(), mid, processing_token) for mid in ids])
        conn.commit()
        return True
    finally:
        conn.close()
