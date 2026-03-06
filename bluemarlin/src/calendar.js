// FILE: calendar.js
// CREATED: Before Brief 001 (original codebase)
// LAST MODIFIED: Brief 031
// DEPENDS ON: bluemarlin-calendar-key.json (config)
// CALLED BY: email_poller.py via subprocess
const { google } = require('googleapis');
const path = require('path');
const KEY_PATH = path.join(__dirname, '..', 'config', 'bluemarlin-calendar-key.json');

const CALENDARS = {
  klein_curacao:    "ed9e5c8b2357d2e21b99af2617c58836204443ed7e8d7352661426cca41cf4cb@group.calendar.google.com",
  snorkeling_3in1:  "649576fb0d0eb17fc895981db2f5e2339ac045edf3a4292d40eff57786fa06db@group.calendar.google.com",
  west_coast_beach: "a85ac414af5903971715705bb8f0975a0be07ca637017c1184f1ba7cd4ab1c00@group.calendar.google.com",
  sunset_cruise:    "a3df969d58e35c9603fe6ae6672446ec2f430ed3304f9c5aaf2178391e67defe@group.calendar.google.com",
  jet_ski:          "903f29c1161ed6d1378b7d4b1f7ef0597ce6707e2648fd98b82b081542919f08@group.calendar.google.com"
};

const DURATIONS_HOURS = {
  klein_curacao:    8,
  snorkeling_3in1:  4,
  west_coast_beach: 6,
  sunset_cruise:    2.5,
  jet_ski:          1
};

async function createHold({ package_key, date, start_time, guests_pax, customer_name, contact, price_usd }) {
  const auth = new google.auth.GoogleAuth({
    keyFile: KEY_PATH,
    scopes: ['https://www.googleapis.com/auth/calendar']
  });

  const calendar = google.calendar({ version: 'v3', auth });
  const calendarId = CALENDARS[package_key];
  if (!calendarId || !calendarId.endsWith("@group.calendar.google.com")) {
    throw new Error(`Calendar ID not yet configured for: ${package_key}`);
  }

  const [year, month, day] = date.split('-').map(Number);
  const [hour, minute] = start_time.split(':').map(Number);

  // Construct time in America/Curacao (always UTC-4, no DST)
  const CURACAO_OFFSET_MS = -4 * 60 * 60 * 1000;
  const utcMs = Date.UTC(year, month - 1, day, hour, minute) - CURACAO_OFFSET_MS;
  const startDateTime = new Date(utcMs);
  const endDateTime = new Date(utcMs);
  const dur = DURATIONS_HOURS[package_key] || 4;
  endDateTime.setTime(endDateTime.getTime() + dur * 60 * 60 * 1000);

  // Availability check: list events overlapping the requested slot
  const timeMin = startDateTime.toISOString();
  const timeMax = endDateTime.toISOString();

  const existing = await calendar.events.list({
    calendarId,
    timeMin,
    timeMax,
    singleEvents: true,
    orderBy: 'startTime',
    maxResults: 5
  });

  if ((existing.data.items || []).length > 0) {
    const first = existing.data.items[0];
    throw new Error(`UNAVAILABLE: Slot already booked/held (${first.summary || 'event'})`);
  }

  const event = {
    summary: `HOLD — ${package_key.replace(/_/g, ' ').toUpperCase()} — ${customer_name}`,
    description: `Guests: ${guests_pax}\nContact: ${contact}\nPrice: $${price_usd} USD\nStatus: PENDING_PAYMENT`,
    start: { dateTime: timeMin, timeZone: 'America/Curacao' },
    end: { dateTime: timeMax, timeZone: 'America/Curacao' }
  };

  const response = await calendar.events.insert({ calendarId, requestBody: event });
  return { eventId: response.data.id, htmlLink: response.data.htmlLink };
}

async function checkAvailability({ package_key, date, start_time }) {
  const auth = new google.auth.GoogleAuth({
    keyFile: KEY_PATH,
    scopes: ['https://www.googleapis.com/auth/calendar']
  });

  const calendar = google.calendar({ version: 'v3', auth });
  const calendarId = CALENDARS[package_key];
  if (!calendarId || !calendarId.endsWith("@group.calendar.google.com")) {
    return { available: false, error: `Calendar ID not yet configured for: ${package_key}` };
  }

  const [year, month, day] = date.split('-').map(Number);
  const [hour, minute] = start_time.split(':').map(Number);

  const CURACAO_OFFSET_MS = -4 * 60 * 60 * 1000;
  const utcMs = Date.UTC(year, month - 1, day, hour, minute) - CURACAO_OFFSET_MS;
  const startDateTime = new Date(utcMs);
  const endDateTime = new Date(utcMs);
  const dur = DURATIONS_HOURS[package_key] || 4;
  endDateTime.setTime(endDateTime.getTime() + dur * 60 * 60 * 1000);

  const timeMin = startDateTime.toISOString();
  const timeMax = endDateTime.toISOString();

  try {
    const existing = await calendar.events.list({
      calendarId,
      timeMin,
      timeMax,
      singleEvents: true,
      orderBy: 'startTime',
      maxResults: 5
    });
    const items = existing.data.items || [];
    if (items.length > 0) {
      return { available: false, reason: `Slot already booked (${items[0].summary || 'event'})` };
    }
    return { available: true };
  } catch (err) {
    return { available: false, error: err.message };
  }
}

const input = JSON.parse(process.argv[2]);
const command = input.command || 'createHold';

if (command === 'checkAvailability') {
  checkAvailability(input)
    .then(result => console.log(JSON.stringify(result)))
    .catch(err => { console.error(err.message); process.exit(1); });
} else {
  createHold(input)
    .then(result => console.log(JSON.stringify(result)))
    .catch(err => { console.error(err.message); process.exit(1); });
}
