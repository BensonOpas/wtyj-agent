"""Tests for Brief 052 — Manifests sheet tab."""
import os
import inspect

from agents.marina import sheets_writer, format_sheets


# ── sheets_writer.py ──

def test_log_manifest_update_exists():
    """T1: log_manifest_update function exists."""
    assert hasattr(sheets_writer, "log_manifest_update")


def test_log_manifest_update_callable():
    """T2: log_manifest_update is callable."""
    assert callable(getattr(sheets_writer, "log_manifest_update", None))


def test_log_manifest_update_param():
    """T3: log_manifest_update accepts data dict."""
    sig = inspect.signature(sheets_writer.log_manifest_update)
    params = list(sig.parameters.keys())
    assert params == ["data"]


def test_sheets_writer_header():
    """T4: sheets_writer header says Brief."""
    with open(os.path.join(os.path.dirname(__file__), "..", "..", "agents", "marina", "sheets_writer.py")) as f:
        sw_src = f.read()
    assert "Last modified: Brief" in sw_src


def test_manifests_tab_in_source():
    """T5: log_manifest_update appends to 'Manifests' tab."""
    with open(os.path.join(os.path.dirname(__file__), "..", "..", "agents", "marina", "sheets_writer.py")) as f:
        sw_src = f.read()
    assert "'Manifests'" in sw_src


# ── format_sheets.py ──

def test_manifests_headers_defined():
    """T6: MANIFESTS_HEADERS defined."""
    with open(os.path.join(os.path.dirname(__file__), "..", "..", "agents", "marina", "format_sheets.py")) as f:
        fs_src = f.read()
    assert "MANIFESTS_HEADERS" in fs_src


def test_manifests_widths_defined():
    """T7: MANIFESTS_WIDTHS defined."""
    with open(os.path.join(os.path.dirname(__file__), "..", "..", "agents", "marina", "format_sheets.py")) as f:
        fs_src = f.read()
    assert "MANIFESTS_WIDTHS" in fs_src


def test_manifests_headers_count():
    """T8: MANIFESTS_HEADERS has 11 columns."""
    assert len(format_sheets.MANIFESTS_HEADERS) == 11


def test_manifests_widths_count():
    """T9: MANIFESTS_WIDTHS has 11 values."""
    assert len(format_sheets.MANIFESTS_WIDTHS) == 11


def test_manifests_in_tabs_list():
    """T10: 'Manifests' in TABS list."""
    tab_names = [t["name"] for t in format_sheets.TABS]
    assert "Manifests" in tab_names


def test_manifests_tab_headers_match():
    """T11: Manifests tab headers match MANIFESTS_HEADERS."""
    manifests_tab = next(t for t in format_sheets.TABS if t["name"] == "Manifests")
    assert manifests_tab["headers"] is format_sheets.MANIFESTS_HEADERS


def test_manifests_tab_widths_match():
    """T12: Manifests tab widths match MANIFESTS_WIDTHS."""
    manifests_tab = next(t for t in format_sheets.TABS if t["name"] == "Manifests")
    assert manifests_tab["widths"] is format_sheets.MANIFESTS_WIDTHS


def test_format_sheets_header():
    """T13: format_sheets header says Brief."""
    with open(os.path.join(os.path.dirname(__file__), "..", "..", "agents", "marina", "format_sheets.py")) as f:
        fs_src = f.read()
    assert "Last modified: Brief" in fs_src


def test_manifests_first_column_timestamp():
    """T14: MANIFESTS_HEADERS first column is 'Timestamp'."""
    assert format_sheets.MANIFESTS_HEADERS[0] == "Timestamp"


def test_manifests_contains_revenue():
    """T15: MANIFESTS_HEADERS contains 'Revenue'."""
    assert "Revenue" in format_sheets.MANIFESTS_HEADERS


def test_manifests_contains_calendar_link():
    """T16: MANIFESTS_HEADERS contains 'Calendar Link'."""
    assert "Calendar Link" in format_sheets.MANIFESTS_HEADERS


# ── email_poller.py ──

def _read_email_poller():
    with open(os.path.join(os.path.dirname(__file__), "..", "..", "agents", "marina", "email_poller.py")) as f:
        return f.read()


def test_log_manifest_update_in_email_poller():
    """T17: log_manifest_update called in email_poller."""
    ep_src = _read_email_poller()
    assert "sheets_writer.log_manifest_update(" in ep_src


def test_get_slot_passengers_in_email_poller():
    """T18: get_slot_passengers called in email_poller Step 5."""
    ep_src = _read_email_poller()
    assert "state_registry.get_slot_passengers(" in ep_src


def test_log_manifest_after_log_hold():
    """T19: log_manifest_update called after log_hold_created."""
    ep_src = _read_email_poller()
    pos_hold = ep_src.find("sheets_writer.log_hold_created(")
    pos_manifest = ep_src.find("sheets_writer.log_manifest_update(")
    assert 0 < pos_hold < pos_manifest


def test_email_poller_header():
    """T20: email_poller header says Brief."""
    ep_src = _read_email_poller()
    assert "Last modified: Brief" in ep_src


def test_capacity_in_manifest_log():
    """T21: manifest log includes capacity."""
    ep_src = _read_email_poller()
    pos_manifest = ep_src.find("sheets_writer.log_manifest_update(")
    section = ep_src[pos_manifest:pos_manifest+600]
    assert '"capacity":' in section or "'capacity':" in section


def test_total_revenue_in_manifest_log():
    """T22: manifest log includes total_revenue."""
    ep_src = _read_email_poller()
    pos_manifest = ep_src.find("sheets_writer.log_manifest_update(")
    section = ep_src[pos_manifest:pos_manifest+600]
    assert '"total_revenue":' in section or "'total_revenue':" in section


# ── Behavioral tests: call log_manifest_update with known data ──

def test_log_manifest_update_calls_append():
    """T23-T28: log_manifest_update produces correct row."""
    _captured_rows = []
    _orig_append = sheets_writer._append

    def _mock_append(tab_name, row):
        _captured_rows.append((tab_name, row))

    sheets_writer._append = _mock_append
    try:
        sheets_writer.log_manifest_update({
            "trip_key": "klein_curacao",
            "date": "2026-04-01",
            "departure_time": "08:00",
            "total_guests": 12,
            "capacity": 30,
            "confirmed_count": 2,
            "pending_count": 1,
            "total_revenue": 1440,
            "calendar_link": "https://calendar.google.com/event?eid=abc123",
            "booking_ref": "BF-2026-50123",
        })
    finally:
        sheets_writer._append = _orig_append

    # T23: _append was called with 'Manifests' tab
    assert len(_captured_rows) == 1 and _captured_rows[0][0] == "Manifests"

    _row = _captured_rows[0][1]

    # T24: row has 11 columns
    assert len(_row) == 11

    # T25: revenue formatted as "$1,440 USD"
    assert _row[8] == "$1,440 USD"

    # T26: booking_ref is last column
    assert _row[10] == "BF-2026-50123"

    # T27: trip_key is second column
    assert _row[1] == "klein_curacao"

    # T28: capacity as string '30' in column 5
    assert _row[5] == "30"
