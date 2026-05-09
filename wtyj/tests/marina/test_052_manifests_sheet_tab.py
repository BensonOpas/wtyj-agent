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


# ── format_sheets.py ──

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


def test_manifests_first_column_timestamp():
    """T14: MANIFESTS_HEADERS first column is 'Timestamp'."""
    assert format_sheets.MANIFESTS_HEADERS[0] == "Timestamp"


def test_manifests_contains_revenue():
    """T15: MANIFESTS_HEADERS contains 'Revenue'."""
    assert "Revenue" in format_sheets.MANIFESTS_HEADERS


def test_manifests_contains_calendar_link():
    """T16: MANIFESTS_HEADERS contains 'Calendar Link'."""
    assert "Calendar Link" in format_sheets.MANIFESTS_HEADERS


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
            "service_key": "klein_curacao",
            "date": "2026-04-01",
            "slot_time": "08:00",
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

    # T27: service_key is second column
    assert _row[1] == "klein_curacao"

    # T28: capacity as string '30' in column 5
    assert _row[5] == "30"
