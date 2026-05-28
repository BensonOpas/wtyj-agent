"""Auto-block moderation rules for tenant runtimes.

This is deliberately conservative: severe abuse can trigger an immediate
block, while ordinary profanity only counts toward a repeated threshold.
Every block creates an escalation for operator review.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from typing import Any

from shared import bm_logger, state_registry


ZERO_TOLERANCE_CATEGORIES = {
    "hate_speech": "racial slur / hate speech",
    "severe_insult": "severe insult / personal abuse",
    "threat": "threat / intimidation",
    "sexual_harassment": "sexual harassment",
    "fraud_scam": "fraud/scam behavior",
    "severe_abuse": "other severe abusive behavior",
}

DEFAULT_SETTINGS: dict[str, Any] = {
    "enabled": True,
    "zero_tolerance": {
        "hate_speech": True,
        "severe_insult": True,
        "threat": True,
        "sexual_harassment": True,
        "fraud_scam": True,
        "severe_abuse": True,
    },
    "repeated_profanity": {
        "enabled": True,
        "threshold": 3,
        "warn_before_block": True,
        "warning_message": (
            "Please keep the conversation respectful. If abusive messages "
            "continue, this number may be blocked."
        ),
        "window_hours": 24,
    },
    "final_block_notice_enabled": False,
    "admin_override": False,
}

_PROFANITY_RE = re.compile(r"\b(fuck|fucking|shit|bitch|asshole|dickhead)\b", re.I)
_PATTERNS: list[tuple[str, re.Pattern[str], str]] = [
    ("threat", re.compile(r"\b(i will|i'm going to|im going to)\s+(kill|hurt|destroy|beat)\b", re.I), "direct threat"),
    ("threat", re.compile(r"\byou(?:'re| are)?\s+dead\b", re.I), "direct intimidation"),
    ("sexual_harassment", re.compile(r"\b(send|show).{0,20}\b(nudes|naked|boobs|dick|sex)\b", re.I), "sexual harassment"),
    ("sexual_harassment", re.compile(r"\b(i want to|let me)\s+(fuck|touch)\s+you\b", re.I), "sexual harassment"),
    ("fraud_scam", re.compile(r"\b(send|give).{0,30}\b(password|otp|one[- ]time code|credit card|bank login)\b", re.I), "credential or payment scam"),
    ("fraud_scam", re.compile(r"\bcrypto investment|wire transfer|gift card code\b", re.I), "scam pattern"),
    ("hate_speech", re.compile(r"\b(go back to your country|dirty immigrant|all\s+\w+\s+should die)\b", re.I), "hate speech"),
    ("severe_insult", re.compile(r"\b(you are|you're|u are)\s+(worthless|disgusting|subhuman|a parasite)\b", re.I), "severe personal abuse"),
    ("severe_abuse", re.compile(r"\b(i hope you die|kill yourself)\b", re.I), "severe abusive behavior"),
]


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _connect():
    conn = state_registry._get_conn()
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS auto_block_settings (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            settings_json TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS auto_block_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL,
            channel TEXT NOT NULL,
            user_identifier TEXT NOT NULL,
            category TEXT NOT NULL,
            rule_type TEXT NOT NULL,
            severity TEXT NOT NULL,
            confidence REAL NOT NULL,
            action_taken TEXT NOT NULL,
            reason TEXT NOT NULL,
            evidence_text TEXT NOT NULL,
            evidence_json TEXT NOT NULL
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_auto_block_events_lookup "
        "ON auto_block_events(user_identifier, category, created_at)"
    )
    conn.commit()
    return conn


def _deep_merge(base: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    result = json.loads(json.dumps(base))
    for key, value in (incoming or {}).items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def _sanitize_settings(raw: dict[str, Any] | None) -> dict[str, Any]:
    settings = _deep_merge(DEFAULT_SETTINGS, raw or {})
    settings["enabled"] = bool(settings.get("enabled"))
    zt = settings.setdefault("zero_tolerance", {})
    for key in ZERO_TOLERANCE_CATEGORIES:
        zt[key] = bool(zt.get(key, True))
    rp = settings.setdefault("repeated_profanity", {})
    rp["enabled"] = bool(rp.get("enabled", True))
    try:
        rp["threshold"] = int(rp.get("threshold", 3))
    except (TypeError, ValueError):
        rp["threshold"] = 3
    if rp["threshold"] not in (2, 3, 5):
        rp["threshold"] = 3
    rp["warn_before_block"] = bool(rp.get("warn_before_block", True))
    rp["warning_message"] = str(
        rp.get("warning_message") or DEFAULT_SETTINGS["repeated_profanity"]["warning_message"]
    )[:500]
    try:
        rp["window_hours"] = int(rp.get("window_hours", 24))
    except (TypeError, ValueError):
        rp["window_hours"] = 24
    rp["window_hours"] = max(1, min(168, rp["window_hours"]))
    settings["final_block_notice_enabled"] = bool(settings.get("final_block_notice_enabled", False))
    settings["admin_override"] = bool(settings.get("admin_override", False))
    return settings


def get_settings() -> dict[str, Any]:
    with _connect() as conn:
        row = conn.execute("SELECT settings_json FROM auto_block_settings WHERE id = 1").fetchone()
    if not row:
        return _sanitize_settings(None)
    try:
        raw = json.loads(row[0] or "{}")
    except json.JSONDecodeError:
        raw = {}
    return _sanitize_settings(raw)


def save_settings(settings: dict[str, Any], *, admin_override: bool | None = None) -> dict[str, Any]:
    sanitized = _sanitize_settings(settings)
    if admin_override is not None:
        sanitized["admin_override"] = bool(admin_override)
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO auto_block_settings (id, settings_json, updated_at)
            VALUES (1, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                settings_json = excluded.settings_json,
                updated_at = excluded.updated_at
            """,
            (json.dumps(sanitized, sort_keys=True), _now()),
        )
        conn.commit()
    bm_logger.log("auto_block_settings_changed", admin_override=sanitized["admin_override"])
    return sanitized


def classify_message(text: str) -> dict[str, Any] | None:
    body = text or ""
    for category, pattern, reason in _PATTERNS:
        if pattern.search(body):
            return {
                "category": category,
                "label": ZERO_TOLERANCE_CATEGORIES[category],
                "rule_type": "zero_tolerance",
                "severity": "high",
                "confidence": 0.92,
                "reason": reason,
            }
    if _PROFANITY_RE.search(body):
        return {
            "category": "profanity",
            "label": "repeated profanity",
            "rule_type": "repeated_threshold",
            "severity": "medium",
            "confidence": 0.78,
            "reason": "profanity / bad words",
        }
    return None


def _record_event(
    *,
    channel: str,
    user_identifier: str,
    category: str,
    rule_type: str,
    severity: str,
    confidence: float,
    action_taken: str,
    reason: str,
    evidence_text: str,
    evidence: dict[str, Any] | None = None,
) -> int:
    with _connect() as conn:
        cur = conn.execute(
            """
            INSERT INTO auto_block_events (
                created_at, channel, user_identifier, category, rule_type,
                severity, confidence, action_taken, reason, evidence_text,
                evidence_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                _now(),
                channel,
                user_identifier,
                category,
                rule_type,
                severity,
                float(confidence),
                action_taken,
                reason,
                evidence_text[:1000],
                json.dumps(evidence or {}, ensure_ascii=False, sort_keys=True),
            ),
        )
        conn.commit()
        return int(cur.lastrowid)


def _recent_category_count(user_identifier: str, category: str, window_hours: int) -> int:
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=window_hours)).replace(microsecond=0).isoformat()
    with _connect() as conn:
        row = conn.execute(
            """
            SELECT COUNT(*) FROM auto_block_events
            WHERE user_identifier = ?
              AND category = ?
              AND created_at >= ?
              AND action_taken IN ('observed', 'warned', 'blocked')
            """,
            (user_identifier, category, cutoff),
        ).fetchone()
    return int(row[0] if row else 0)


def _warning_already_sent(user_identifier: str, category: str, window_hours: int) -> bool:
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=window_hours)).replace(microsecond=0).isoformat()
    with _connect() as conn:
        row = conn.execute(
            """
            SELECT 1 FROM auto_block_events
            WHERE user_identifier = ?
              AND category = ?
              AND created_at >= ?
              AND action_taken = 'warned'
            LIMIT 1
            """,
            (user_identifier, category, cutoff),
        ).fetchone()
    return row is not None


def _create_auto_block_escalation(
    *,
    channel: str,
    user_identifier: str,
    customer_name: str,
    category_label: str,
    trigger: str,
    rule_type: str,
    evidence_text: str,
) -> int:
    mode_label = (
        "zero-tolerance immediate block"
        if rule_type == "zero_tolerance"
        else "repeated profanity threshold block"
        if rule_type == "repeated_threshold"
        else "manual block"
    )
    subject = f"[AUTO-BLOCK REVIEW] {category_label} - {customer_name or user_identifier}"
    body = (
        "Customer was automatically blocked and escalated for review.\n\n"
        f"Reason: {category_label}\n"
        f"Trigger: {trigger}\n"
        f"Channel: {channel}\n"
        f"Customer: {user_identifier}\n"
        f"Block type: {mode_label}\n"
        "Action taken: Marina stopped replying and customer is now blocked.\n\n"
        f"Evidence:\n{evidence_text[:2000]}\n\n"
        "Operator actions: review the blocked customer, unblock if this was "
        "a false positive, keep blocked if correct, add an internal note, "
        "and resolve this escalation."
    )
    return state_registry.create_pending_notification(
        "escalation",
        channel,
        user_identifier,
        customer_name or user_identifier,
        subject,
        body,
        mode="hard",
    )


def block_user(
    *,
    channel: str,
    user_identifier: str,
    customer_name: str = "",
    category: str = "manual",
    category_label: str = "manual block",
    trigger: str = "Manual block",
    rule_type: str = "manual",
    severity: str = "high",
    confidence: float = 1.0,
    evidence_text: str = "",
    actor: str = "system",
) -> dict[str, Any]:
    if not user_identifier:
        return {"action": "none", "reason": "missing_user_identifier"}
    state_registry.set_blocked(
        user_identifier,
        True,
        channel,
        reason=category,
        blocked_by=actor,
    )
    event_id = _record_event(
        channel=channel,
        user_identifier=user_identifier,
        category=category,
        rule_type=rule_type,
        severity=severity,
        confidence=confidence,
        action_taken="blocked",
        reason=trigger,
        evidence_text=evidence_text,
        evidence={"actor": actor, "category_label": category_label},
    )
    escalation_id = _create_auto_block_escalation(
        channel=channel,
        user_identifier=user_identifier,
        customer_name=customer_name,
        category_label=category_label,
        trigger=trigger,
        rule_type=rule_type,
        evidence_text=evidence_text,
    )
    bm_logger.log(
        "auto_block_triggered",
        channel=channel,
        category=category,
        rule_type=rule_type,
        user_identifier=user_identifier[:50],
        escalation_id=escalation_id,
    )
    return {"action": "blocked", "event_id": event_id, "escalation_id": escalation_id}


def unblock_user(user_identifier: str, *, actor: str = "operator") -> None:
    state_registry.set_blocked(user_identifier, False)
    _record_event(
        channel="unknown",
        user_identifier=user_identifier,
        category="unblock",
        rule_type="manual",
        severity="info",
        confidence=1.0,
        action_taken="unblocked",
        reason=f"Unblocked by {actor}",
        evidence_text="",
        evidence={"actor": actor},
    )
    bm_logger.log("auto_block_unblocked", user_identifier=user_identifier[:50], actor=actor)


def evaluate_inbound(
    *,
    channel: str,
    user_identifier: str,
    text: str,
    customer_name: str = "",
) -> dict[str, Any]:
    settings = get_settings()
    if not settings.get("enabled", True):
        return {"action": "none"}
    classification = classify_message(text)
    if not classification:
        return {"action": "none"}

    category = classification["category"]
    evidence_text = text or ""
    if classification["rule_type"] == "zero_tolerance":
        if not settings.get("zero_tolerance", {}).get(category, True):
            _record_event(
                channel=channel,
                user_identifier=user_identifier,
                category=category,
                rule_type="zero_tolerance",
                severity=classification["severity"],
                confidence=classification["confidence"],
                action_taken="observed",
                reason=f"{classification['reason']} detected but disabled",
                evidence_text=evidence_text,
            )
            return {"action": "none"}
        result = block_user(
            channel=channel,
            user_identifier=user_identifier,
            customer_name=customer_name,
            category=category,
            category_label=classification["label"],
            trigger=classification["reason"],
            rule_type="zero_tolerance",
            severity=classification["severity"],
            confidence=classification["confidence"],
            evidence_text=evidence_text,
            actor="auto-block",
        )
        return {**result, **classification}

    repeated = settings.get("repeated_profanity", {})
    if not repeated.get("enabled", True):
        return {"action": "none"}
    _record_event(
        channel=channel,
        user_identifier=user_identifier,
        category="profanity",
        rule_type="repeated_threshold",
        severity=classification["severity"],
        confidence=classification["confidence"],
        action_taken="observed",
        reason=classification["reason"],
        evidence_text=evidence_text,
    )
    threshold = int(repeated.get("threshold", 3))
    window_hours = int(repeated.get("window_hours", 24))
    count = _recent_category_count(user_identifier, "profanity", window_hours)
    if count >= threshold:
        result = block_user(
            channel=channel,
            user_identifier=user_identifier,
            customer_name=customer_name,
            category="profanity",
            category_label="repeated profanity",
            trigger=f"Repeated profanity threshold reached: {count}/{threshold}",
            rule_type="repeated_threshold",
            severity=classification["severity"],
            confidence=classification["confidence"],
            evidence_text=evidence_text,
            actor="auto-block",
        )
        return {**result, **classification, "count": count, "threshold": threshold}
    if (
        repeated.get("warn_before_block", True)
        and count >= max(1, threshold - 1)
        and not _warning_already_sent(user_identifier, "profanity", window_hours)
    ):
        warning = repeated.get("warning_message") or DEFAULT_SETTINGS["repeated_profanity"]["warning_message"]
        _record_event(
            channel=channel,
            user_identifier=user_identifier,
            category="profanity",
            rule_type="repeated_threshold",
            severity="medium",
            confidence=classification["confidence"],
            action_taken="warned",
            reason="Warning sent before repeated profanity block",
            evidence_text=evidence_text,
        )
        bm_logger.log("auto_block_warning_sent", channel=channel, user_identifier=user_identifier[:50])
        return {
            "action": "warn",
            "reply": warning,
            "category": "profanity",
            "count": count,
            "threshold": threshold,
        }
    return {"action": "none", "category": "profanity", "count": count, "threshold": threshold}


def list_events(limit: int = 100) -> list[dict[str, Any]]:
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT id, created_at, channel, user_identifier, category,
                   rule_type, severity, confidence, action_taken, reason,
                   evidence_text, evidence_json
            FROM auto_block_events
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (max(1, min(int(limit), 500)),),
        ).fetchall()
    out = []
    for row in rows:
        try:
            evidence = json.loads(row[11] or "{}")
        except json.JSONDecodeError:
            evidence = {}
        out.append({
            "id": row[0],
            "createdAt": row[1],
            "channel": row[2],
            "userIdentifier": row[3],
            "category": row[4],
            "ruleType": row[5],
            "severity": row[6],
            "confidence": row[7],
            "actionTaken": row[8],
            "reason": row[9],
            "evidenceText": row[10],
            "evidence": evidence,
        })
    return out
