#!/usr/bin/env python3
# FILE: format_sheets.py
# CREATED: Brief 014
# LAST MODIFIED: Brief 015
# DEPENDS ON: sheets_writer.py (KEY_PATH, SPREADSHEET_ID, _get_service)
# RUN ONCE: python3 bluemarlin/src/format_sheets.py
# PURPOSE: Apply BlueMarlin color palette to Operations Dashboard
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sheets_writer import KEY_PATH, SPREADSHEET_ID, _get_service

BOOKINGS_HEADERS = [
    'Timestamp', 'Customer Name', 'Email', 'Experience',
    'Date', 'Guests', 'Phone', 'Special Requests',
    'Hold Status', 'Event Link', 'Payment Link', 'Error',
    'Operator Notes'
]
COMPLAINTS_HEADERS = [
    'Timestamp', 'Email', 'Subject', 'Message Preview',
    'Status', 'Operator Notes'
]
ALL_EVENTS_HEADERS = [
    'Timestamp', 'Event Type', 'Email', 'Subject', 'Details'
]

BOOKINGS_WIDTHS =    [180, 150, 200, 180, 110, 80, 130, 250, 110, 200, 200, 200, 250]
COMPLAINTS_WIDTHS =  [180, 200, 200, 300, 110, 250]
ALL_EVENTS_WIDTHS =  [180, 150, 200, 200, 400]

TABS = [
    {'name': 'Bookings',   'headers': BOOKINGS_HEADERS,   'widths': BOOKINGS_WIDTHS},
    {'name': 'Complaints', 'headers': COMPLAINTS_HEADERS, 'widths': COMPLAINTS_WIDTHS},
    {'name': 'All Events', 'headers': ALL_EVENTS_HEADERS, 'widths': ALL_EVENTS_WIDTHS},
]


def hex_to_rgb(hex_str):
    h = hex_str.lstrip('#')
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return {"red": r / 255, "green": g / 255, "blue": b / 255}


def _build_requests(sheet_id, tab_name, col_widths,
                    banded_range_ids=None, column_count=None):
    """Build all formatting requests for a single tab.
    col_widths: list of pixel sizes, one per column.
    banded_range_ids: list of existing bandedRangeId values to delete first.
    column_count: current column count from metadata; used for deleteDimension guard.
    """
    n = len(col_widths)
    requests = []

    # Request 1 — full sheet background: #1a2030
    requests.append({
        "repeatCell": {
            "range": {
                "sheetId": sheet_id,
                "startRowIndex": 0,
                "endRowIndex": 1001,
                "startColumnIndex": 0,
                "endColumnIndex": n
            },
            "cell": {
                "userEnteredFormat": {
                    "backgroundColor": hex_to_rgb("#1a2030")
                }
            },
            "fields": "userEnteredFormat.backgroundColor"
        }
    })

    # Request 2 — header row: #2a3545 bg, white bold 11pt, centered, CLIP wrap
    requests.append({
        "repeatCell": {
            "range": {
                "sheetId": sheet_id,
                "startRowIndex": 0,
                "endRowIndex": 1,
                "startColumnIndex": 0,
                "endColumnIndex": n
            },
            "cell": {
                "userEnteredFormat": {
                    "backgroundColor": hex_to_rgb("#2a3545"),
                    "textFormat": {
                        "foregroundColor": hex_to_rgb("#ffffff"),
                        "bold": True,
                        "fontSize": 11
                    },
                    "verticalAlignment": "MIDDLE",
                    "horizontalAlignment": "CENTER",
                    "wrapStrategy": "CLIP"
                }
            },
            "fields": "userEnteredFormat(backgroundColor,textFormat,verticalAlignment,horizontalAlignment,wrapStrategy)"
        }
    })

    # Request 3 — freeze header row
    requests.append({
        "updateSheetProperties": {
            "properties": {
                "sheetId": sheet_id,
                "gridProperties": {
                    "frozenRowCount": 1
                }
            },
            "fields": "gridProperties.frozenRowCount"
        }
    })

    # Request 4 — individual column widths
    for i, width in enumerate(col_widths):
        requests.append({
            "updateDimensionProperties": {
                "range": {
                    "sheetId": sheet_id,
                    "dimension": "COLUMNS",
                    "startIndex": i,
                    "endIndex": i + 1
                },
                "properties": {"pixelSize": width},
                "fields": "pixelSize"
            }
        })

    # Request 5 — row height 40px for all rows
    requests.append({
        "updateDimensionProperties": {
            "range": {
                "sheetId": sheet_id,
                "dimension": "ROWS",
                "startIndex": 0,
                "endIndex": 1001
            },
            "properties": {"pixelSize": 40},
            "fields": "pixelSize"
        }
    })

    # Request 6 — body text: #e8edf5, 10pt, MIDDLE, WRAP
    requests.append({
        "repeatCell": {
            "range": {
                "sheetId": sheet_id,
                "startRowIndex": 1,
                "endRowIndex": 1001,
                "startColumnIndex": 0,
                "endColumnIndex": n
            },
            "cell": {
                "userEnteredFormat": {
                    "backgroundColor": hex_to_rgb("#1e2530"),
                    "textFormat": {
                        "foregroundColor": hex_to_rgb("#e8edf5"),
                        "fontSize": 10
                    },
                    "verticalAlignment": "MIDDLE",
                    "wrapStrategy": "WRAP"
                }
            },
            "fields": "userEnteredFormat(backgroundColor,textFormat,verticalAlignment,wrapStrategy)"
        }
    })

    # Request 7 — alternating row banding
    # Delete existing banding first for idempotency
    for banded_id in (banded_range_ids or []):
        requests.append({"deleteBanding": {"bandedRangeId": banded_id}})

    requests.append({
        "addBanding": {
            "bandedRange": {
                "range": {
                    "sheetId": sheet_id,
                    "startRowIndex": 1,
                    "endRowIndex": 1001,
                    "startColumnIndex": 0,
                    "endColumnIndex": n
                },
                "rowProperties": {
                    "headerColor": hex_to_rgb("#2a3545"),
                    "firstBandColor": hex_to_rgb("#1e2530"),
                    "secondBandColor": hex_to_rgb("#242f3d")
                }
            }
        }
    })

    # Request 8 — header bottom border: SOLID_MEDIUM #3d8eb9
    requests.append({
        "updateBorders": {
            "range": {
                "sheetId": sheet_id,
                "startRowIndex": 0,
                "endRowIndex": 1,
                "startColumnIndex": 0,
                "endColumnIndex": n
            },
            "bottom": {
                "style": "SOLID_MEDIUM",
                "color": hex_to_rgb("#3d8eb9")
            }
        }
    })

    # Request 9 — delete extra columns beyond data range (guard: only if excess exists)
    if column_count is not None and column_count > n:
        requests.append({
            "deleteDimension": {
                "range": {
                    "sheetId": sheet_id,
                    "dimension": "COLUMNS",
                    "startIndex": n,
                    "endIndex": column_count
                }
            }
        })

    return requests


def main():
    try:
        service = _get_service()
        if service is None:
            print("format_sheets: could not get Sheets service — check credentials")
            return

        # Step 1 — get sheet metadata: sheetId, column count, banded ranges per tab
        meta = service.spreadsheets().get(spreadsheetId=SPREADSHEET_ID).execute()
        sheet_meta = {
            s['properties']['title']: s
            for s in meta['sheets']
        }

        for tab in TABS:
            tab_name = tab['name']
            headers = tab['headers']
            col_widths = tab['widths']

            if tab_name not in sheet_meta:
                print(f"format_sheets: tab '{tab_name}' not found — skipping")
                continue

            sheet_props = sheet_meta[tab_name]
            sheet_id = sheet_props['properties']['sheetId']
            column_count = sheet_props['properties']['gridProperties'].get('columnCount', 0)
            banded_range_ids = [
                br['bandedRangeId']
                for br in sheet_props.get('bandedRanges', [])
            ]

            # Write header row
            try:
                service.spreadsheets().values().update(
                    spreadsheetId=SPREADSHEET_ID,
                    range=f"'{tab_name}'!A1",
                    valueInputOption="RAW",
                    body={"values": [headers]}
                ).execute()
            except Exception as e:
                print(f"format_sheets: header write error ({tab_name}): {e}")

            # Main formatting batchUpdate (Requests 1-9)
            try:
                requests = _build_requests(
                    sheet_id, tab_name, col_widths,
                    banded_range_ids=banded_range_ids,
                    column_count=column_count
                )
                service.spreadsheets().batchUpdate(
                    spreadsheetId=SPREADSHEET_ID,
                    body={"requests": requests}
                ).execute()
            except Exception as e:
                print(f"format_sheets: batchUpdate error ({tab_name}): {e}")

            # Second batchUpdate — cap data row height at 80px max
            try:
                service.spreadsheets().batchUpdate(
                    spreadsheetId=SPREADSHEET_ID,
                    body={"requests": [{
                        "updateDimensionProperties": {
                            "range": {
                                "sheetId": sheet_id,
                                "dimension": "ROWS",
                                "startIndex": 1,
                                "endIndex": 1001
                            },
                            "properties": {"pixelSize": 80},
                            "fields": "pixelSize"
                        }
                    }]}
                ).execute()
            except Exception as e:
                print(f"format_sheets: max row height error ({tab_name}): {e}")

            print(f"Formatted: {tab_name}")

        print("Done.")

    except Exception as e:
        print(f"format_sheets: main error: {e}")


if __name__ == "__main__":
    main()
