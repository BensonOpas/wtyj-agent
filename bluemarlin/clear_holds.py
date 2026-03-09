import sqlite3
c = sqlite3.connect("/root/bluemarlin/src/state_registry.db")
c.execute("UPDATE trip_bookings SET status='cancelled'")
c.commit()
print("cleared")
