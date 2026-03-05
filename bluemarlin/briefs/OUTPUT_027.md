# OUTPUT_027 — marina_agent.py — departure_time field + date format enforcement

## Files modified
- `bluemarlin/src/marina_agent.py`
- `bluemarlin/src/email_poller.py`

## Files created
- `bluemarlin/briefs/OUTPUT_027.md` (this file)

---

## Changes made

### marina_agent.py — fields description in _build_prompt()

Updated the `fields` instruction in the prompt from a single line to a structured
multi-line block. Key additions:
- `date`: must be YYYY-MM-DD. Claude converts natural language before returning.
  If unresolvable, omits field and adds to `clarifications_needed`.
- `departure_time`: new field — HH:MM format, only when customer explicitly chooses one.

File header: LAST MODIFIED Brief 024 → Brief 027

### email_poller.py — create_calendar_hold() start_time logic

Single-line change:

Before:
```python
start_time = departures[0].get("time", "09:00") if departures else "09:00"
```

After:
```python
start_time = (
    fields_now.get("departure_time")
    or (departures[0].get("time", "09:00") if departures else "09:00")
)
```

Customer's chosen `departure_time` takes priority; config first-departure is the fallback.

File header: LAST MODIFIED Brief 025 → Brief 027

---

## Test results

| # | Test | Result |
|---|------|--------|
| 1 | "YYYY-MM-DD" appears ≥2 times in marina_agent.py | PASS (3 times) |
| 2 | "departure_time" present in marina_agent.py | PASS |
| 3 | "April 20 2026" → fields.date == "2026-04-20" | PASS |
| 4 | "08:30 works for us" with klein_curacao context → departure_time == "08:30" | PASS |
| 5 | "Klein Curacao on April 20 for 2" → departure_time not in fields | PASS |
| 6 | create_calendar_hold with departure_time "08:30" → payload start_time "08:30" | PASS |
| 7 | create_calendar_hold sunset_cruise no departure_time → payload start_time "17:30" | PASS |
| 8 | Both files import cleanly | PASS |

---

## Bugs fixed

- **Bug 1 (date format):** Claude was returning dates as "April 5", "April 20" etc.
  calendar.js requires YYYY-MM-DD. Now Claude converts before returning; unresolvable
  dates are omitted and added to clarifications_needed.

- **Bug 2 (departure_time):** Multi-departure trips (e.g. klein_curacao: 08:00 and 08:30)
  always used departures[0] regardless of customer choice. Now marina_agent extracts
  departure_time when explicitly chosen; create_calendar_hold uses it when present.

---

## Regression check block
```
source ~/.zshrc && python3 -c "
import sys; sys.path.insert(0, 'bluemarlin/src')
import marina_agent, email_poller, json, subprocess as _sp

# date format
r = marina_agent.process_message('g@e.com','','Sunset cruise April 20 2026 2 guests',{},{})
assert r.get('fields',{}).get('date') == '2026-04-20', f'date={r.get(\"fields\",{}).get(\"date\")}'

# departure_time capture
r2 = marina_agent.process_message('g@e.com','','08:30 works',
    {'trip_key':'klein_curacao','date':'2026-04-20','guests':2},{})
assert r2.get('fields',{}).get('departure_time') == '08:30'

# create_calendar_hold priority
cap = {}
orig = _sp.run
def mock(cmd,**kw):
    cap['p'] = json.loads(cmd[2])
    class R:
        returncode=0; stdout=json.dumps({'eventId':'x','htmlLink':'y'}); stderr=''
    return R()
_sp.run = mock
email_poller.create_calendar_hold({'trip_key':'klein_curacao','date':'2026-04-20','guests':2,'departure_time':'08:30'})
assert cap['p']['start_time'] == '08:30'
_sp.run = orig

print('Brief 027 regression OK')
"
```
