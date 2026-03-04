# FILE: sheets_writer.py
# CREATED: Brief 013
# LAST MODIFIED: Brief 013
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
            data.get('customer_name', ''),
            data.get('email', ''),
            data.get('experience', ''),
            data.get('date', ''),
            str(data.get('guests', '')),
            data.get('phone', ''),
            data.get('special_requests', ''),
            'CREATED',
            data.get('html_link', ''),
            data.get('payment_link', ''),
            '',
            '',
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
            data.get('customer_name', ''),
            data.get('email', ''),
            data.get('experience', ''),
            data.get('date', ''),
            str(data.get('guests', '')),
            '',
            '',
            'FAILED',
            '',
            '',
            data.get('error', ''),
            '',
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


def log_complaint(data: dict):
    try:
        service = _get_service()
        if service is None:
            return None
        row_complaints = [
            _now(),
            data.get('email', ''),
            data.get('subject', ''),
            data.get('body_snippet', ''),
            'NEW',
            '',
        ]
        row_all = [
            _now(),
            'complaint_received',
            data.get('email', ''),
            data.get('subject', ''),
            json.dumps(data),
        ]
        _append(service, 'Complaints', row_complaints)
        return _append(service, 'All Events', row_all)
    except Exception as e:
        print(f"sheets_writer: log_complaint error: {e}")
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
