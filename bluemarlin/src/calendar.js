const { google } = require('googleapis');

const KEY_PATH = '/root/.openclaw/bluemarlin-calendar-key.json';

const CALENDARS = {
  half_day_private_charter: '011f3fe421fe405fc7cd93b0271c25b385c5ece811d9a8afed89ed68ee0ecd1e@group.calendar.google.com',
  sunset_signature_cruise: '00da89b0e81eb3bb8267f8e850049402d8cc22f072738ca111f5dda38f723af5@group.calendar.google.com',
  full_day_west_coast_escape: '6539a4ca65a6911ea45f35a1a80ff92f9e9e2b2cdbd2841a7fef9248bfb77e7d@group.calendar.google.com'
};

const DURATIONS_HOURS = {
  half_day_private_charter: 4,
  sunset_signature_cruise: 2.5,
  full_day_west_coast_escape: 8
};

async function createHold({ package_key, date, start_time, guests_pax, customer_name, contact, price_usd }) {
  const auth = new google.auth.GoogleAuth({
    keyFile: KEY_PATH,
    scopes: ['https://www.googleapis.com/auth/calendar']
  });

  const calendar = google.calendar({ version: 'v3', auth });
  const calendarId = CALENDARS[package_key];
  if (!calendarId) throw new Error(`Unknown package_key: ${package_key}`);

  const [year, month, day] = date.split('-').map(Number);
  const [hour, minute] = start_time.split(':').map(Number);

  const startDateTime = new Date(year, month - 1, day, hour, minute);
  const endDateTime = new Date(startDateTime);
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

const args = JSON.parse(process.argv[2]);
createHold(args)
  .then(result => console.log(JSON.stringify(result)))
  .catch(err => { console.error(err.message); process.exit(1); });
