# FILE: gws_calendar.py
# CREATED: Brief 032
# LAST MODIFIED: Brief 039
# DEPENDS ON: config/bluemarlin-calendar-key.json
# IMPORTS FROM: config_loader.py (Brief 022), state_registry.py (Brief 004)
# CALLERS: email_poller.py

import json
import os
import subprocess
import sys
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config_loader
import state_registry

_SRC_DIR = os.path.dirname(os.path.abspath(__file__))
_KEY_PATH = os.path.normpath(os.path.join(_SRC_DIR, '..', 'config', 'bluemarlin-calendar-key.json'))

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
