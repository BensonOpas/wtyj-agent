# FILE: gws_calendar.py
# CREATED: Brief 032
# LAST MODIFIED: Brief 032
# DEPENDS ON: config/bluemarlin-calendar-key.json
# IMPORTS FROM: config_loader.py (Brief 022)
# CALLERS: email_poller.py

import json
import os
import subprocess
import sys
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config_loader

_SRC_DIR = os.path.dirname(os.path.abspath(__file__))
_KEY_PATH = os.path.normpath(os.path.join(_SRC_DIR, '..', 'config', 'bluemarlin-calendar-key.json'))

_CURACAO_TZ = timezone(timedelta(hours=-4))

# Copied verbatim from calendar.js (Brief 031)
CALENDARS = {
    "klein_curacao":    "ed9e5c8b2357d2e21b99af2617c58836204443ed7e8d7352661426cca41cf4cb@group.calendar.google.com",
    "snorkeling_3in1":  "649576fb0d0eb17fc895981db2f5e2339ac045edf3a4292d40eff57786fa06db@group.calendar.google.com",
    "west_coast_beach": "a85ac414af5903971715705bb8f0975a0be07ca637017c1184f1ba7cd4ab1c00@group.calendar.google.com",
    "sunset_cruise":    "a3df969d58e35c9603fe6ae6672446ec2f430ed3304f9c5aaf2178391e67defe@group.calendar.google.com",
    "jet_ski":          "903f29c1161ed6d1378b7d4b1f7ef0597ce6707e2648fd98b82b081542919f08@group.calendar.google.com",
}

DURATIONS_HOURS = {
    "klein_curacao":    8,
    "snorkeling_3in1":  4,
    "west_coast_beach": 6,
    "sunset_cruise":    2.5,
    "jet_ski":          1,
}


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


def check_availability(trip_key: str, date: str, start_time: str) -> dict:
    """
    Check calendar availability for the given slot without creating a hold.
    Returns {available: bool, reason?: str, error?: str}
    """
    calendar_id = CALENDARS.get(trip_key, '')
    if not calendar_id or not calendar_id.endswith('@group.calendar.google.com'):
        return {'available': False, 'error': f'Calendar ID not yet configured for: {trip_key}'}

    dur = DURATIONS_HOURS.get(trip_key, 4)
    try:
        time_min = _curacao_to_iso(date, start_time)
        year, month, day = map(int, date.split('-'))
        hour, minute = map(int, start_time.split(':'))
        dt_start = datetime(year, month, day, hour, minute, tzinfo=_CURACAO_TZ)
        dt_end = dt_start + timedelta(hours=dur)
        time_max = dt_end.astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    except Exception as e:
        return {'available': False, 'error': f'Date/time parse error: {e}'}

    params = json.dumps({
        'calendarId': calendar_id,
        'timeMin': time_min,
        'timeMax': time_max,
        'singleEvents': True,
        'orderBy': 'startTime',
        'maxResults': 5,
    })

    result = _run_gws(['calendar', 'events', 'list', '--params', params])
    if 'error' in result:
        return {'available': False, 'error': result['error']}

    items = result.get('items', [])
    if items:
        first = items[0]
        return {'available': False, 'reason': f"Slot already booked ({first.get('summary', 'event')})"}
    return {'available': True}


def create_hold(fields_now: dict) -> dict:
    """
    Create a calendar hold event for the given booking fields.
    Returns {ok: bool, eventId?: str, htmlLink?: str, error?: str}
    """
    trip_key = fields_now.get('trip_key', '')
    if not trip_key:
        return {'ok': False, 'error': 'No trip_key in fields — cannot create hold.'}

    calendar_id = CALENDARS.get(trip_key, '')
    if not calendar_id or not calendar_id.endswith('@group.calendar.google.com'):
        return {'ok': False, 'error': f'Calendar ID not yet configured for: {trip_key}'}

    trip = config_loader.get_trip(trip_key)
    departures = trip.get('departures', [])
    start_time = (
        fields_now.get('departure_time')
        or (departures[0].get('time', '09:00') if departures else '09:00')
    )
    price_usd = trip.get('price_adult_usd', 0)
    dur = DURATIONS_HOURS.get(trip_key, 4)
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
