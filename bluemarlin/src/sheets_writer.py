# FILE: sheets_writer.py
# CREATED: Brief 013
# LAST MODIFIED: Brief 028
# DEPENDS ON: bluemarlin-calendar-key.json (config)
# IMPORTS FROM: nothing
# CALLERS: email_poller.py
import os
import json
from datetime import datetime, timezone
from googleapiclient.discovery import build
from google.oauth2.service_account import Credentials

_SRC_DIR = os.path.dirname(os.path.abspath(__file__))
KEY_PATH = os.path.normpath(os.path.join(_SRC_DIR, '..', 'config', 'bluemarlin-calendar-key.json'))
SPREADSHEET_ID = '1soG3zVnx-Y0WYWGJdgakXqpNeI6GAe6AD8DycOwwifE'
SCOPES = ['https://www.googleapis.com/auth/spreadsheets']


def _get_service():
    try:
        creds = Credentials.from_service_account_file(KEY_PATH, scopes=SCOPES)
        return build('sheets', 'v4', credentials=creds)
    except Exception as e:
        print(f"sheets_writer: _get_service error: {e}")
        return None


def _append(service, tab_name, row):
    try:
        return service.spreadsheets().values().append(
            spreadsheetId=SPREADSHEET_ID,
            range=f"{tab_name}!A:A",
            valueInputOption="USER_ENTERED",
            insertDataOption="INSERT_ROWS",
            body={"values": [row]}
        ).execute()
    except Exception as e:
        print(f"sheets_writer: _append error ({tab_name}): {e}")
        return None


def _now():
    return datetime.now(timezone.utc).isoformat()


def log_hold_created(data: dict):
    try:
        service = _get_service()
        if service is None:
            return None
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
        _append(service, 'Bookings', row_bookings)
        return _append(service, 'All Events', row_all)
    except Exception as e:
        print(f"sheets_writer: log_hold_created error: {e}")
        return None


def log_hold_failed(data: dict):
    try:
        service = _get_service()
        if service is None:
            return None
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
        _append(service, 'Bookings', row_bookings)
        return _append(service, 'All Events', row_all)
    except Exception as e:
        print(f"sheets_writer: log_hold_failed error: {e}")
        return None


def log_escalation(data: dict):
    try:
        service = _get_service()
        if service is None:
            return None
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
        _append(service, 'Escalations', row_escalations)
        return _append(service, 'All Events', row_all)
    except Exception as e:
        print(f"sheets_writer: log_escalation error: {e}")
        return None


def log_event(event_type: str, data: dict):
    try:
        service = _get_service()
        if service is None:
            return None
        row_all = [
            _now(),
            event_type,
            data.get('email', ''),
            data.get('subject', ''),
            json.dumps(data),
        ]
        return _append(service, 'All Events', row_all)
    except Exception as e:
        print(f"sheets_writer: log_event error: {e}")
        return None
