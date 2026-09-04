"""Catalog calendar and recorded-state replies; the model only selects a route."""
from __future__ import annotations

import hashlib
import json
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from shared import config_loader, mermaid_catalog, state_registry

WEEKDAYS = ('monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday')
CALENDAR_REQUESTS = {'this_week', 'next_week', 'weekend', 'next_seven_days', 'operating_days'}


def policy() -> dict:
    configured = Path(config_loader._CONFIG_PATH).with_name('response_policy.json')
    bundled = Path(__file__).with_suffix('.json')
    source = Path(__file__).resolve().parents[3] / 'clients/mermaid/config/response_policy.json'
    path = next((p for p in (configured, bundled, source) if p.is_file()), configured)
    return json.loads(path.read_text(encoding='utf-8'))


def copy(key: str, locale: str) -> str:
    copies = policy()['copies']
    return copies.get(locale, copies['en'])[key]


def local_today(now: datetime | None = None) -> date:
    return (now or datetime.now(ZoneInfo('America/Curacao'))).astimezone(ZoneInfo('America/Curacao')).date()


def calendar_dates(request: str, *, today: date | None = None, catalog: dict | None = None) -> list[date]:
    today = today or local_today()
    monday = today - timedelta(days=today.weekday())
    if request == 'this_week':
        start, end = today, monday + timedelta(days=7)
    elif request == 'next_week':
        start, end = monday + timedelta(days=7), monday + timedelta(days=14)
    elif request == 'weekend':
        start, end = max(today, monday + timedelta(days=5)), monday + timedelta(days=7)
    elif request == 'next_seven_days':
        start, end = today, today + timedelta(days=7)
    else:
        return []
    days = (catalog or mermaid_catalog.get_catalog())['service']['operating_weekdays']
    return [start + timedelta(days=i) for i in range((end - start).days)
            if WEEKDAYS[(start + timedelta(days=i)).weekday()] in days]


def date_label(value: str | date, locale: str) -> str:
    day = date.fromisoformat(value) if isinstance(value, str) else value
    names = policy()['weekdays']
    return f"{names.get(locale, names['en'])[day.weekday()]} {day.isoformat()}"


def calendar_reply(request: str, locale: str, *, today: date | None = None) -> str:
    catalog = mermaid_catalog.get_catalog()
    if request == 'operating_days':
        names = policy()['weekdays']
        localized = names.get(locale, names['en'])
        days = ', '.join(localized[i] for i, day in enumerate(WEEKDAYS)
                         if day in catalog['service']['operating_weekdays'])
        return copy('operating_days', locale).format(days=days)
    dates = calendar_dates(request, today=today, catalog=catalog)
    if not dates:
        return copy('no_dates', locale)
    return copy('calendar', locale).format(dates='; '.join(date_label(day, locale) for day in dates))


def state_context(conversation: str, reservation: dict | None) -> dict:
    """A payment record proves payment; a hard takeover proves active handling."""
    mode = state_registry.get_active_escalation_mode(conversation)
    active = bool(state_registry.get_human_takeover_at(conversation))
    review = 'active' if active else 'queued' if mode in {'soft', 'hard'} or (reservation or {}).get('human_takeover') else 'none'
    result = {'review': review, 'payment': 'none', 'delivery': 'none', 'delivery_channel': 'whatsapp', 'email_delivery': 'not_established'}
    if not reservation:
        return result
    from agents.social import mermaid_reservation_store as store, mermaid_documents as documents
    db = store._conn()
    try:
        paid = db.execute("SELECT 1 FROM mermaid_demo_payments WHERE tenant_slug='mermaid' AND reservation_public_id=? AND status='simulated_success'", (reservation['public_id'],)).fetchone()
        result['payment'] = 'paid' if paid else 'unpaid'
    finally:
        db.close()
    db = documents._conn()
    try:
        row = db.execute("SELECT status FROM mermaid_delivery_jobs WHERE tenant_slug='mermaid' AND reservation_public_id=? ORDER BY created_at DESC, rowid DESC LIMIT 1", (reservation['public_id'],)).fetchone()
        if row:
            result['delivery'] = row['status'] if row['status'] in {'delivered', 'failed'} else 'waiting'
    finally:
        db.close()
    return result


def status_reply(request: str, locale: str, context: dict) -> str:
    group = 'review' if request == 'handover' else request
    if group not in {'review', 'payment', 'delivery'}:
        return ''
    return copy(group + '_' + context.get(group, 'none'), locale)


def wildlife_guarantee_reply(locale: str, context: dict) -> str:
    response = copy('wildlife_guarantee', locale)
    if context.get('review') in {'queued', 'active'}:
        response += '\n\n' + status_reply('handover', locale, context)
    return response


def pickup_coverage_reply(locale: str) -> str:
    journey = mermaid_catalog.get_catalog()['pricing'].get('pickup_journey', 'unconfirmed')
    return copy('pickup_round_trip' if journey == 'round_trip' else 'pickup_unknown', locale)


def record_security_event(conversation: str, message_id: str, event: str, *, now: float | None = None) -> bool:
    """Log classifications, never supplied secrets/text. Return durable review need.

    Two distinct blocked attempts within 24 hours, or one actionable incident,
    merit a staff task. Replayed event IDs do not increase the count.
    """
    if event not in {'blocked_override', 'actionable_incident'}:
        return False
    if not message_id:
        # No stable provider identity means this attempt cannot safely be counted twice.
        return event == 'actionable_incident'
    now = time.time() if now is None else now
    settings = policy()['security']
    db = state_registry._get_conn()
    try:
        db.execute('CREATE TABLE IF NOT EXISTS mermaid_security_events (conversation_id TEXT NOT NULL, event_id TEXT NOT NULL, classification TEXT NOT NULL, created_at REAL NOT NULL, PRIMARY KEY(conversation_id,event_id))')
        db.execute('CREATE INDEX IF NOT EXISTS mermaid_security_recent ON mermaid_security_events(conversation_id,created_at)')
        db.commit()
        db.execute('BEGIN IMMEDIATE')
        event_id = hashlib.sha256(message_id.encode()).hexdigest()
        db.execute('INSERT OR IGNORE INTO mermaid_security_events VALUES (?,?,?,?)', (conversation, event_id, event, now))
        rows = db.execute('SELECT classification FROM mermaid_security_events WHERE conversation_id=? AND created_at>=?', (conversation, now-settings['window_seconds'])).fetchall()
        needs_review = any(row[0] == 'actionable_incident' for row in rows) or len(rows) >= settings['distinct_attempt_threshold']
        db.commit()
        return needs_review
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
