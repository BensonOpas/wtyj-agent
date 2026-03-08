# FILE: sheets_writer.py
# CREATED: Brief 013
# LAST MODIFIED: Brief 032
# DEPENDS ON: config/bluemarlin-calendar-key.json
# IMPORTS FROM: config_loader.py (Brief 022)
# CALLERS: email_poller.py
import os
import json
import subprocess
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config_loader

_SRC_DIR = os.path.dirname(os.path.abspath(__file__))
KEY_PATH = os.path.normpath(os.path.join(_SRC_DIR, '..', 'config', 'bluemarlin-calendar-key.json'))


def _get_spreadsheet_id() -> str:
    try:
        sid = config_loader.get_business().get('spreadsheet_id', '')
        if sid:
            return sid
    except Exception:
        pass
    sid = os.environ.get('SPREADSHEET_ID', '')
    if sid:
        return sid
    return '1t1gy6qILNbJNwMBhvixT5yNspulT6-Mkr4-2dMo384I'


def _append(tab_name: str, row: list) -> None:
    spreadsheet_id = _get_spreadsheet_id()
    params = json.dumps({
        'spreadsheetId': spreadsheet_id,
        'range': f'{tab_name}!A:A',
        'valueInputOption': 'USER_ENTERED',
        'insertDataOption': 'INSERT_ROWS',
    })
    body = json.dumps({'values': [row]})
    env = os.environ.copy()
    env['GOOGLE_WORKSPACE_CLI_CREDENTIALS_FILE'] = KEY_PATH
    try:
        r = subprocess.run(
            ['gws', 'sheets', 'spreadsheets', 'values', 'append',
             '--params', params, '--json', body],
            capture_output=True, text=True, timeout=30,
            env=env
        )
        if r.returncode != 0:
            print(f"sheets_writer: _append error ({tab_name}): {(r.stderr or r.stdout or 'gws failed').strip()[:200]}")
    except Exception as e:
        print(f"sheets_writer: _append error ({tab_name}): {e}")


def _now():
    return datetime.now(timezone.utc).isoformat()


def log_hold_created(data: dict):
    try:
        row_bookings = [
            _now(),
            data.get('booking_ref', ''),
            data.get('customer_name', ''),
            data.get('email', ''),
            data.get('experience', ''),
            data.get('trip_key', ''),
            data.get('date', ''),
            str(data.get('guests', '')),
            data.get('departure_time', ''),
            data.get('phone', ''),
            data.get('special_requests', ''),
            str(data.get('total_price', '')),
            data.get('payment_status', ''),
            data.get('html_link', ''),
            data.get('payment_link', ''),
        ]
        row_all = [
            _now(),
            'hold_created',
            data.get('email', ''),
            data.get('subject', ''),
            json.dumps(data),
        ]
        _append('Bookings', row_bookings)
        _append('All Events', row_all)
    except Exception as e:
        print(f"sheets_writer: log_hold_created error: {e}")


def log_hold_failed(data: dict):
    try:
        row_bookings = [
            _now(),
            '',
            data.get('customer_name', ''),
            data.get('email', ''),
            data.get('experience', ''),
            data.get('trip_key', ''),
            data.get('date', ''),
            str(data.get('guests', '')),
            '',
            '',
            '',
            '',
            'FAILED',
            '',
            data.get('error', ''),
        ]
        row_all = [
            _now(),
            'hold_failed',
            data.get('email', ''),
            data.get('subject', ''),
            json.dumps(data),
        ]
        _append('Bookings', row_bookings)
        _append('All Events', row_all)
    except Exception as e:
        print(f"sheets_writer: log_hold_failed error: {e}")


def log_escalation(data: dict):
    try:
        row_escalations = [
            _now(),
            data.get('customer_name', ''),
            data.get('email', ''),
            data.get('intent', ''),
            json.dumps(data.get('fields_collected', {})),
            data.get('internal_note', ''),
        ]
        row_all = [
            _now(),
            'escalation',
            data.get('email', ''),
            data.get('subject', ''),
            json.dumps(data),
        ]
        _append('Escalations', row_escalations)
        _append('All Events', row_all)
    except Exception as e:
        print(f"sheets_writer: log_escalation error: {e}")


def log_event(event_type: str, data: dict):
    try:
        row_all = [
            _now(),
            event_type,
            data.get('email', ''),
            data.get('subject', ''),
            json.dumps(data),
        ]
        _append('All Events', row_all)
    except Exception as e:
        print(f"sheets_writer: log_event error: {e}")
