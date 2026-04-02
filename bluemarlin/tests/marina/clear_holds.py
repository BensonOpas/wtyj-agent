import os, sqlite3
db = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "..", "data", "state_registry.db")
print(f"DB path: {db}")
c = sqlite3.connect(db)
rows = c.execute("SELECT id, service_key, date, slot_time, guests, status FROM service_bookings WHERE status IN ('soft_hold','confirmed')").fetchall()
print(f"Active holds before: {len(rows)}")
for r in rows:
    print(f"  {r}")
c.execute("UPDATE service_bookings SET status='cancelled' WHERE status IN ('soft_hold','confirmed')")
c.commit()
print("All holds cancelled.")
