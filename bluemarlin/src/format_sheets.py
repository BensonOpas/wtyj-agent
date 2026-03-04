#!/usr/bin/env python3
# FILE: format_sheets.py
# CREATED: Brief 014
# LAST MODIFIED: Brief 014
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
TABS = [
    {'name': 'Bookings',   'headers': BOOKINGS_HEADERS},
    {'name': 'Complaints', 'headers': COMPLAINTS_HEADERS},
    {'name': 'All Events', 'headers': ALL_EVENTS_HEADERS},
]


def hex_to_rgb(hex_str):
    h = hex_str.lstrip('#')
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return {"red": r / 255, "green": g / 255, "blue": b / 255}


def _build_requests(sheet_id, tab_name, n):
    """Build all formatting requests for a single tab. n = number of columns."""
    requests = []

    # 2a — entire sheet background: deep navy #1a2744
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
                    "backgroundColor": hex_to_rgb("#1a2744")
                }
            },
            "fields": "userEnteredFormat.backgroundColor"
        }
    })

    # 2c — header row: dark background, white bold text, centered
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
                    "backgroundColor": hex_to_rgb("#243460"),
                    "textFormat": {
                        "foregroundColor": hex_to_rgb("#ffffff"),
                        "bold": True,
                        "fontSize": 11
                    },
                    "verticalAlignment": "MIDDLE",
                    "horizontalAlignment": "CENTER"
                }
            },
            "fields": "userEnteredFormat(backgroundColor,textFormat,verticalAlignment,horizontalAlignment)"
        }
    })

    # 2d — freeze header row
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

    # 2e — column widths (tab-specific)
    if tab_name == 'Bookings':
        requests.append({
            "updateDimensionProperties": {
                "range": {
                    "sheetId": sheet_id,
                    "dimension": "COLUMNS",
                    "startIndex": 0,
                    "endIndex": 13
                },
                "properties": {"pixelSize": 160},
                "fields": "pixelSize"
            }
        })
    elif tab_name == 'Complaints':
        requests.append({
            "updateDimensionProperties": {
                "range": {
                    "sheetId": sheet_id,
                    "dimension": "COLUMNS",
                    "startIndex": 0,
                    "endIndex": 6
                },
                "properties": {"pixelSize": 200},
                "fields": "pixelSize"
            }
        })
    elif tab_name == 'All Events':
        requests.append({
            "updateDimensionProperties": {
                "range": {
                    "sheetId": sheet_id,
                    "dimension": "COLUMNS",
                    "startIndex": 0,
                    "endIndex": 4
                },
                "properties": {"pixelSize": 160},
                "fields": "pixelSize"
            }
        })
        requests.append({
            "updateDimensionProperties": {
                "range": {
                    "sheetId": sheet_id,
                    "dimension": "COLUMNS",
                    "startIndex": 4,
                    "endIndex": 5
                },
                "properties": {"pixelSize": 400},
                "fields": "pixelSize"
            }
        })

    # 2f — row height: 32px for all rows
    requests.append({
        "updateDimensionProperties": {
            "range": {
                "sheetId": sheet_id,
                "dimension": "ROWS",
                "startIndex": 0,
                "endIndex": 1001
            },
            "properties": {"pixelSize": 32},
            "fields": "pixelSize"
        }
    })

    # 2g — body text color and size for rows 1-1000
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
                    "textFormat": {
                        "foregroundColor": hex_to_rgb("#e8edf5"),
                        "fontSize": 10
                    },
                    "verticalAlignment": "MIDDLE"
                }
            },
            "fields": "userEnteredFormat(textFormat,verticalAlignment)"
        }
    })

    # 2h — bottom border on header row
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
                "color": hex_to_rgb("#2e7d9e")
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

        # Step 1 — get sheet metadata: map tab name -> sheetId
        meta = service.spreadsheets().get(spreadsheetId=SPREADSHEET_ID).execute()
        sheet_ids = {
            s['properties']['title']: s['properties']['sheetId']
            for s in meta['sheets']
        }

        for tab in TABS:
            tab_name = tab['name']
            headers = tab['headers']

            if tab_name not in sheet_ids:
                print(f"format_sheets: tab '{tab_name}' not found — skipping")
                continue

            sheet_id = sheet_ids[tab_name]

            # Step 2b — write header row
            try:
                service.spreadsheets().values().update(
                    spreadsheetId=SPREADSHEET_ID,
                    range=f"'{tab_name}'!A1",
                    valueInputOption="RAW",
                    body={"values": [headers]}
                ).execute()
            except Exception as e:
                print(f"format_sheets: header write error ({tab_name}): {e}")

            # Steps 2a, 2c-2h — batch all formatting requests
            try:
                requests = _build_requests(sheet_id, tab_name, len(headers))
                service.spreadsheets().batchUpdate(
                    spreadsheetId=SPREADSHEET_ID,
                    body={"requests": requests}
                ).execute()
            except Exception as e:
                print(f"format_sheets: batchUpdate error ({tab_name}): {e}")

            print(f"Formatted: {tab_name}")

        print("Done.")

    except Exception as e:
        print(f"format_sheets: main error: {e}")


if __name__ == "__main__":
    main()
