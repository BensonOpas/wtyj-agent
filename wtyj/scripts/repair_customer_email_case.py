#!/usr/bin/env python3
"""Brief 178: repair existing case-variant email identifiers in customer_identifiers.

Safe to run multiple times. For each email identifier with mixed case:
  - If the lowercased form has no collision: UPDATE in place.
  - If the lowercased form collides with another customer row: DELETE the
    mixed-case row and re-add via customer_add_identifier on the lowercased
    form, which triggers the Brief 166/178 merge path.

Run via:
    docker exec wtyj-bluemarlin python3 /app/scripts/repair_customer_email_case.py
"""

import sqlite3
import sys

sys.path.insert(0, "/app")

from shared import state_registry


DB_PATH = "/app/data/state_registry.db"


def main():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT id, customer_id, value FROM customer_identifiers "
        "WHERE type='email' ORDER BY id"
    ).fetchall()
    conn.close()

    print(f"Inspecting {len(rows)} email identifiers")
    lowercased = 0
    merged = 0
    skipped = 0
    for r in rows:
        original = r["value"]
        normalized = original.strip().lower()
        if original == normalized:
            skipped += 1
            continue

        conn = sqlite3.connect(DB_PATH)
        other = conn.execute(
            "SELECT customer_id FROM customer_identifiers "
            "WHERE type='email' AND value = ?",
            (normalized,)
        ).fetchone()
        conn.close()

        if other is None:
            conn = sqlite3.connect(DB_PATH)
            conn.execute(
                "UPDATE customer_identifiers SET value = ? WHERE id = ?",
                (normalized, r["id"])
            )
            conn.commit()
            conn.close()
            lowercased += 1
            print(f"  row.id={r['id']} customer_id={r['customer_id']} "
                  f"lowercased in place: {original} -> {normalized}")
        else:
            conn = sqlite3.connect(DB_PATH)
            conn.execute(
                "DELETE FROM customer_identifiers WHERE id = ?", (r["id"],)
            )
            conn.commit()
            conn.close()
            result = state_registry.customer_add_identifier(
                r["customer_id"], "email", normalized
            )
            action = result.get("action", "?")
            if action == "merged":
                merged += 1
                print(f"  row.id={r['id']} customer_id={r['customer_id']} "
                      f"MERGED via {normalized}: surviving_id={result.get('customer_id')}")
            else:
                print(f"  row.id={r['id']} customer_id={r['customer_id']} "
                      f"re-added {normalized}: action={action}")

    print(f"\nDone. lowercased_in_place={lowercased} merged={merged} "
          f"already_normalized={skipped}")


if __name__ == "__main__":
    main()
