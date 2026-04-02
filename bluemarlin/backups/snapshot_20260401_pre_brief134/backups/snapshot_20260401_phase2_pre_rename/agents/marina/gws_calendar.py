# bluemarlin/agents/marina/gws_calendar.py
# Last modified: Brief 066
# Purpose: Calendar hold + availability via gws CLI

import json
import os
import subprocess
from datetime import datetime, timezone, timedelta

from shared import config_loader
from shared import state_registry

_MODULE_DIR = os.path.dirname(os.path.abspath(__file__))
_KEY_PATH = os.path.normpath(os.path.join(_MODULE_DIR, '..', '..', 'config', 'bluemarlin-calendar-key.json'))

_CURACAO_TZ = timezone(timedelta(hours=-4))


def _curacao_to_iso(date_str: str, time_str: str) -> str:
    """Convert YYYY-MM-DD HH:MM in Curaçao time (UTC-4, no DST) to UTC ISO 8601 string."""
    year, month, day = map(int, date_str.split('-'))
    hour, minute = map(int, time_str.split(':'))
    dt = datetime(year, month, day, hour, minute, tzinfo=_CURACAO_TZ)
    return dt.astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def _run_gws(args: list) -> dict:
    """Run gws CLI with given args. Returns parsed JSON dict or {'error': str}."""
    env = os.environ.copy()
    env['GOOGLE_WORKSPACE_CLI_CREDENTIALS_FILE'] = _KEY_PATH
    try:
        r = subprocess.run(
            ['gws'] + args,
            capture_output=True, text=True, timeout=30,
            env=env
        )
        if r.returncode != 0:
            return {'error': (r.stderr or r.stdout or 'gws failed').strip()[:500]}
        out = (r.stdout or '').strip()
        return json.loads(out)
    except Exception as e:
        return {'error': str(e)[:500]}


def _build_manifest_body(trip_key: str, date: str, departure_time: str,
                         calendar_id: str, price_usd: int, capacity: int,
                         dur: float) -> dict:
    """Build a manifest-style Google Calendar event body for a departure slot.
    Queries state_registry for all active passengers on this slot."""
    passengers = state_registry.get_slot_passengers(trip_key, date, departure_time)
    total_guests = sum(p["guests"] for p in passengers)
    total_revenue = sum(p["guests"] * price_usd for p in passengers)

    lines = []
    lines.append(f"Total: {total_guests} guests | Revenue: ${total_revenue:,} USD")
    lines.append("")
    for i, p in enumerate(passengers, 1):
        name = p["customer_name"] or "\u2014"
        pax = p["guests"]
        cost = pax * price_usd
        status = p["status"].upper()
        ref = p["booking_ref"] or "pending"
        lines.append(f"{i}. {name} \u2014 {pax} pax \u2014 ${cost} \u2014 {status} \u2014 {ref}")

    display_name = trip_key.replace('_', ' ').upper()
    summary = f"{display_name} \u2014 {date} {departure_time} \u2014 {total_guests}/{capacity} pax"
    description = "\n".join(lines)

    try:
        time_min = _curacao_to_iso(date, departure_time)
        year, month, day = map(int, date.split('-'))
        hour, minute = map(int, departure_time.split(':'))
        dt_start = datetime(year, month, day, hour, minute, tzinfo=_CURACAO_TZ)
        dt_end = dt_start + timedelta(hours=dur)
        time_max = dt_end.astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    except Exception:
        time_min = ""
        time_max = ""

    return {
        'summary': summary,
        'description': description,
        'start': {'dateTime': time_min, 'timeZone': 'America/Curacao'},
        'end': {'dateTime': time_max, 'timeZone': 'America/Curacao'},
        '_total_guests': total_guests,
    }


def create_or_update_manifest(fields_now: dict) -> dict:
    """Create or update a manifest calendar event for this departure slot.
    Reads passenger list (incl. booking_refs) from state_registry — caller must
    call set_booking_ref() before this if the ref should appear in the manifest.
    Returns {ok: bool, eventId?: str, htmlLink?: str, error?: str}."""
    trip_key = fields_now.get('trip_key', '')
    if not trip_key:
        return {'ok': False, 'error': 'No trip_key in fields.'}

    trip = config_loader.get_trip(trip_key)
    departures = trip.get('departures', [])
    start_time = (
        fields_now.get('departure_time')
        or (departures[0].get('time', '09:00') if departures else '09:00')
    )
    matching_dep = next(
        (d for d in departures if d.get('time') == start_time),
        departures[0] if departures else {}
    )
    calendar_id = matching_dep.get('calendar_id', '')
    if not calendar_id or not calendar_id.endswith('@group.calendar.google.com'):
        return {'ok': False, 'error': f'Calendar ID not configured for: {trip_key} at {start_time}'}

    price_usd = trip.get('price_adult_usd', 0)
    dur = trip.get('duration_hours', 4)
    date = fields_now.get('date', '')
    capacity = trip.get('capacity', 20)

    body = _build_manifest_body(trip_key, date, start_time, calendar_id, price_usd, capacity, dur)
    body.pop('_total_guests', None)

    existing = state_registry.get_manifest_event(trip_key, date, start_time)

    if existing:
        # Update existing manifest event (patch summary + description only)
        patch_body = {'summary': body['summary'], 'description': body['description']}
        params = json.dumps({'calendarId': existing['calendar_id'], 'eventId': existing['event_id']})
        result = _run_gws(['calendar', 'events', 'patch', '--params', params, '--json', json.dumps(patch_body)])
        if 'error' in result:
            return {'ok': False, 'error': result['error']}
        return {'ok': True, 'eventId': existing['event_id'], 'htmlLink': existing['html_link']}
    else:
        # Create new manifest event
        params = json.dumps({'calendarId': calendar_id})
        result = _run_gws(['calendar', 'events', 'insert', '--params', params, '--json', json.dumps(body)])
        if 'error' in result:
            return {'ok': False, 'error': result['error']}
        event_id = result.get('id')
        if not event_id:
            return {'ok': False, 'error': f'gws returned no event id: {str(result)[:200]}'}
        html_link = result.get('htmlLink', '')
        state_registry.save_manifest_event(trip_key, date, start_time, calendar_id, event_id, html_link)
        return {'ok': True, 'eventId': event_id, 'htmlLink': html_link}


def update_manifest(trip_key: str, date: str, departure_time: str) -> dict:
    """Refresh an existing manifest event's summary and description.
    Returns {ok: bool, error?: str}."""
    existing = state_registry.get_manifest_event(trip_key, date, departure_time)
    if not existing:
        return {'ok': False, 'error': 'No manifest event for this slot.'}

    trip = config_loader.get_trip(trip_key)
    price_usd = trip.get('price_adult_usd', 0)
    capacity = trip.get('capacity', 20)
    dur = trip.get('duration_hours', 4)

    body = _build_manifest_body(trip_key, date, departure_time, existing['calendar_id'],
                                price_usd, capacity, dur)
    patch_body = {'summary': body['summary'], 'description': body['description']}
    params = json.dumps({'calendarId': existing['calendar_id'], 'eventId': existing['event_id']})
    result = _run_gws(['calendar', 'events', 'patch', '--params', params, '--json', json.dumps(patch_body)])
    if 'error' in result:
        return {'ok': False, 'error': result['error']}
    return {'ok': True}


def remove_from_manifest(trip_key: str, date: str, departure_time: str) -> dict:
    """Update manifest after a cancellation. Deletes event if zero active passengers remain.
    Returns {ok: bool, deleted?: bool, error?: str}."""
    existing = state_registry.get_manifest_event(trip_key, date, departure_time)
    if not existing:
        return {'ok': True, 'deleted': False}

    trip = config_loader.get_trip(trip_key)
    price_usd = trip.get('price_adult_usd', 0)
    capacity = trip.get('capacity', 20)
    dur = trip.get('duration_hours', 4)

    body = _build_manifest_body(trip_key, date, departure_time, existing['calendar_id'],
                                price_usd, capacity, dur)
    total_guests = body.pop('_total_guests', 0)

    if total_guests == 0:
        # No passengers left — delete the calendar event
        params = json.dumps({'calendarId': existing['calendar_id'], 'eventId': existing['event_id']})
        _run_gws(['calendar', 'events', 'delete', '--params', params])
        state_registry.delete_manifest_event(trip_key, date, departure_time)
        return {'ok': True, 'deleted': True}
    else:
        # Update manifest with remaining passengers
        patch_body = {'summary': body['summary'], 'description': body['description']}
        params = json.dumps({'calendarId': existing['calendar_id'], 'eventId': existing['event_id']})
        result = _run_gws(['calendar', 'events', 'patch', '--params', params, '--json', json.dumps(patch_body)])
        if 'error' in result:
            return {'ok': False, 'error': result['error']}
        return {'ok': True, 'deleted': False}


def check_availability(trip_key: str, date: str, start_time: str, new_guests: int = 1) -> dict:
    """
    Check SQLite capacity for this slot. No gws CLI call.
    Returns {available: bool, spots_remaining: int, capacity: int}.
    """
    state_registry.expire_stale_holds()
    capacity = config_loader.get_trip(trip_key).get("capacity", 20)
    spots = state_registry.get_spots_remaining(trip_key, date, start_time, capacity)
    return {
        "available": spots >= new_guests,
        "spots_remaining": spots,
        "capacity": capacity,
    }


def create_hold(fields_now: dict) -> dict:
    """
    Create a calendar hold event for the given booking fields.
    Returns {ok: bool, eventId?: str, htmlLink?: str, error?: str}
    """
    trip_key = fields_now.get('trip_key', '')
    if not trip_key:
        return {'ok': False, 'error': 'No trip_key in fields — cannot create hold.'}

    trip = config_loader.get_trip(trip_key)
    departures = trip.get('departures', [])
    start_time = (
        fields_now.get('departure_time')
        or (departures[0].get('time', '09:00') if departures else '09:00')
    )
    matching_dep = next(
        (d for d in departures if d.get('time') == start_time),
        departures[0] if departures else {}
    )
    calendar_id = matching_dep.get('calendar_id', '')
    if not calendar_id or not calendar_id.endswith('@group.calendar.google.com'):
        return {'ok': False, 'error': f'Calendar ID not configured for: {trip_key} at {start_time}'}
    price_usd = trip.get('price_adult_usd', 0)
    dur = trip.get('duration_hours', 4)
    date = fields_now.get('date', '')
    customer_name = fields_now.get('customer_name') or '\u2014'
    contact = (fields_now.get('phone') or '').strip() or '\u2014'
    guests_pax = int(fields_now.get('guests') or 0)

    try:
        time_min = _curacao_to_iso(date, start_time)
        year, month, day = map(int, date.split('-'))
        hour, minute = map(int, start_time.split(':'))
        dt_start = datetime(year, month, day, hour, minute, tzinfo=_CURACAO_TZ)
        dt_end = dt_start + timedelta(hours=dur)
        time_max = dt_end.astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    except Exception as e:
        return {'ok': False, 'error': f'Date/time parse error: {e}'}

    event = {
        'summary': f"HOLD \u2014 {trip_key.replace('_', ' ').upper()} \u2014 {customer_name}",
        'description': f"Guests: {guests_pax}\nContact: {contact}\nPrice: ${price_usd} USD\nStatus: PENDING_PAYMENT",
        'start': {'dateTime': time_min, 'timeZone': 'America/Curacao'},
        'end': {'dateTime': time_max, 'timeZone': 'America/Curacao'},
    }

    params = json.dumps({'calendarId': calendar_id})
    result = _run_gws(['calendar', 'events', 'insert', '--params', params, '--json', json.dumps(event)])

    if 'error' in result:
        return {'ok': False, 'error': result['error']}

    event_id = result.get('id')
    if not event_id:
        return {'ok': False, 'error': f'gws returned no event id: {str(result)[:200]}'}
    return {'ok': True, 'eventId': event_id, 'htmlLink': result.get('htmlLink', '')}
