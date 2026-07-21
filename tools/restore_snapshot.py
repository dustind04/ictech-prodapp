"""
Restore an /admin/export.json snapshot into the database.

Usage (inside the container, after migrations have run):
    docker exec -i ictech python3 tools/restore_snapshot.py < snapshot.json

Full replace: every operator-entered table is cleared and reloaded with
the snapshot's rows, ids included, so foreign keys inside the snapshot
stay valid. schema_migrations is untouched — the running schema owns it.
The snapshot's schema_migrations list is compared and we refuse to
restore a snapshot taken on a NEWER schema than the target DB.
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys

TABLES = ["slot", "asset", "channel", "person", "position", "wireless_model", "capsule_model"]
# ^ delete order: slot/asset reference the others. Insert happens reversed.
# Snapshots taken before a table existed simply restore it empty.


def main() -> int:
    snap = json.load(sys.stdin)
    db_path = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("ICTECH_DB", "/data/ictech.db")

    db = sqlite3.connect(db_path)
    db.row_factory = sqlite3.Row

    applied = {r["filename"] for r in db.execute("SELECT filename FROM schema_migrations")}
    snap_migrations = {m["filename"] for m in snap.get("schema_migrations", [])}
    ahead = snap_migrations - applied
    if ahead:
        print(f"REFUSED: snapshot is from a newer schema (has {sorted(ahead)}). "
              f"Update the app first.", file=sys.stderr)
        return 1

    try:
        db.execute("PRAGMA foreign_keys = OFF")
        for table in TABLES:
            db.execute(f"DELETE FROM {table}")
        for table in reversed(TABLES):
            rows = snap.get(table, [])
            for row in rows:
                cols = ", ".join(row.keys())
                marks = ", ".join(["?"] * len(row))
                db.execute(f"INSERT INTO {table} ({cols}) VALUES ({marks})",
                           list(row.values()))
            print(f"{table}: {len(rows)} rows")
        violations = db.execute("PRAGMA foreign_key_check").fetchall()
        if violations:
            db.rollback()
            print(f"REFUSED: snapshot has {len(violations)} broken references; "
                  f"rolled back.", file=sys.stderr)
            return 1
        db.commit()
    finally:
        db.execute("PRAGMA foreign_keys = ON")
    print(f"Restored snapshot from {snap.get('exported_at', '?')} into {db_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
