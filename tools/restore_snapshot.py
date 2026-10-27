"""
Restore an /admin/export.json snapshot into the database.

Usage (inside the container, after migrations have run):
    docker exec -i ictech python3 tools/restore_snapshot.py < snapshot.json

Every table IN the snapshot is cleared and reloaded with its rows, ids
included, so foreign keys inside the snapshot stay valid. Tables the
snapshot leaves out are left alone — the git-committed inventory
snapshots (seeds/) omit person and slot on purpose (public repo), so
restoring one keeps the box's people; slot links to channels or
positions that no longer exist are cleared rather than left dangling.
Gear catalogs merge instead of replace. schema_migrations is untouched — the running schema owns it.
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
CATALOGS = {"wireless_model", "capsule_model"}   # seeded by migrations: merged
# Dangling references to clear when the referencing table wasn't restored.
REFS = [("slot", "mic_channel_id", "channel"), ("slot", "iem_channel_id", "channel"),
        ("slot", "position_id", "position"), ("slot", "person_id", "person"),
        ("asset", "channel_id", "channel")]


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
        present = [t for t in TABLES if t in snap]
        for table in TABLES:
            if table not in present:
                print(f"{table}: not in snapshot — kept as is")
        for table in present:
            if table not in CATALOGS:
                db.execute(f"DELETE FROM {table}")
        for table in reversed(present):
            rows = snap[table]
            # Catalogs merge instead of replace: a snapshot from an older
            # schema must not erase gear a newer migration seeded.
            verb = "INSERT OR REPLACE" if table in CATALOGS else "INSERT"
            for row in rows:
                cols = ", ".join(row.keys())
                marks = ", ".join(["?"] * len(row))
                db.execute(f"{verb} INTO {table} ({cols}) VALUES ({marks})",
                           list(row.values()))
            print(f"{table}: {len(rows)} rows")
        for table, col, target in REFS:
            if table not in present:
                n = db.execute(
                    f"UPDATE {table} SET {col}=NULL WHERE {col} IS NOT NULL "
                    f"AND {col} NOT IN (SELECT id FROM {target})").rowcount
                if n:
                    print(f"{table}.{col}: {n} link(s) to missing {target} cleared")
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
