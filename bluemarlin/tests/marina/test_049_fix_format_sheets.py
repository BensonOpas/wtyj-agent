"""Tests for Brief 049 — Fix format_sheets.py."""
import os

from agents.marina import format_sheets


def test_format_sheets_imports():
    """T1: format_sheets imports without error."""
    assert format_sheets is not None


def test_spreadsheet_id():
    """T2: _get_spreadsheet_id returns the new sheet ID."""
    sid = format_sheets._get_spreadsheet_id()
    assert sid == "1t1gy6qILNbJNwMBhvixT5yNspulT6-Mkr4-2dMo384I"


def test_old_sheet_id_removed():
    """T3: Old banned sheet ID not in source."""
    with open(os.path.join(os.path.dirname(__file__), "..", "..", "agents", "marina", "format_sheets.py")) as f:
        source = f.read()
    assert "1soG3zVnx" not in source


def test_bookings_headers_count():
    """T4: BOOKINGS_HEADERS has 15 columns."""
    assert len(format_sheets.BOOKINGS_HEADERS) == 15


def test_bookings_widths_count():
    """T5: BOOKINGS_WIDTHS has 15 values."""
    assert len(format_sheets.BOOKINGS_WIDTHS) == 15


def test_header_col0_timestamp():
    """T6: col 0 is Timestamp."""
    assert format_sheets.BOOKINGS_HEADERS[0] == "Timestamp"


def test_header_col1_booking_ref():
    """T7: col 1 is Booking Ref."""
    assert format_sheets.BOOKINGS_HEADERS[1] == "Booking Ref"


def test_header_col5_service_key():
    """T8: col 5 is Trip Key."""
    assert format_sheets.BOOKINGS_HEADERS[5] == "Trip Key"


def test_header_col8_slot_time():
    """T9: col 8 is Departure Time."""
    assert format_sheets.BOOKINGS_HEADERS[8] == "Departure Time"


def test_header_col11_total_price():
    """T10: col 11 is Total Price."""
    assert format_sheets.BOOKINGS_HEADERS[11] == "Total Price"


def test_header_col14_payment_link():
    """T11: col 14 is Payment Link."""
    assert format_sheets.BOOKINGS_HEADERS[14] == "Payment Link"


def test_complaints_headers_count():
    """T12: COMPLAINTS_HEADERS has 6 columns."""
    assert len(format_sheets.COMPLAINTS_HEADERS) == 6


def test_escalations_headers_count():
    """T13: ESCALATIONS_HEADERS has 7 columns."""
    assert len(format_sheets.ESCALATIONS_HEADERS) == 7


def test_all_events_headers_count():
    """T14: ALL_EVENTS_HEADERS has 5 columns."""
    assert len(format_sheets.ALL_EVENTS_HEADERS) == 5


def test_get_service_callable():
    """T15: _get_service is callable."""
    assert callable(getattr(format_sheets, '_get_service', None))


def test_get_spreadsheet_id_callable():
    """T16: _get_spreadsheet_id is callable."""
    assert callable(getattr(format_sheets, '_get_spreadsheet_id', None))


def test_no_sheets_writer_import():
    """T17: No reference to sheets_writer in imports."""
    with open(os.path.join(os.path.dirname(__file__), "..", "..", "agents", "marina", "format_sheets.py")) as f:
        source = f.read()
    assert "from sheets_writer" not in source and "import sheets_writer" not in source


def test_file_header():
    """T18: File header says Brief."""
    with open(os.path.join(os.path.dirname(__file__), "..", "..", "agents", "marina", "format_sheets.py")) as f:
        source = f.read()
    assert "Last modified: Brief" in source


def test_key_path_defined():
    """T19: KEY_PATH defined locally."""
    assert hasattr(format_sheets, 'KEY_PATH')


def test_build_requests_returns_list():
    """T20: _build_requests returns list of requests."""
    reqs = format_sheets._build_requests(0, 'Bookings', format_sheets.BOOKINGS_WIDTHS)
    assert isinstance(reqs, list) and len(reqs) > 5
