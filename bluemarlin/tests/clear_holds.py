import os, sqlite3
db = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src", "state_registry.db")
print(f"DB path: {db}")
c = sqlite3.connect(db)
rows = c.execute("SELECT id, trip_key, date, departure_time, guests, status FROM trip_bookings WHERE status IN ('soft_hold','confirmed')").fetchall()
print(f"Active holds before: {len(rows)}")
for r in rows:
    print(f"  {r}")
c.execute("UPDATE trip_bookings SET status='cancelled' WHERE status IN ('soft_hold','confirmed')")
c.commit()
print("All holds cancelled.")
