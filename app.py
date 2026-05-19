"""
icTech Services — production tooling for Immanuel Church.

Single Flask app. Three routes:
  GET  /            -> wall display (backstage screen)
  GET  /admin       -> data entry portal
  GET  /api/state   -> JSON snapshot for the wall display to poll

The wall display is the deliverable singers and the backstage manager
share. The admin page is where staff configure people, channels, and
slot assignments. The API is the bridge between the two.

The Shure protocol worker (live mic state from receivers on the
network) will land in a later commit and write into a shared
in-memory state dict; for now /api/state returns slot data only.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from flask import Flask, jsonify, render_template

from db import get_db, init_db


logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("ictech")


def create_app() -> Flask:
    app = Flask(__name__, static_folder="static", template_folder="templates")
    app.config["DATABASE_PATH"] = os.environ.get(
        "ICTECH_DB", str(Path(__file__).parent / "data" / "ictech.db")
    )

    # Apply migrations on every startup. Idempotent.
    init_db(app.config["DATABASE_PATH"])

    register_routes(app)
    register_teardown(app)
    return app


def register_routes(app: Flask) -> None:
    @app.route("/")
    def wall_display():
        """The backstage wall display. Renders the 10-slot grid."""
        return render_template("wall.html")

    @app.route("/admin")
    def admin_index():
        """Data entry portal for people, channels, slot assignments."""
        return render_template("admin.html")

    @app.route("/api/state")
    def api_state():
        """
        Snapshot of current slot assignments plus live receiver state.
        Polled by the wall display every ~2s.
        Schema is intentionally flat & forward-compatible: consumers should
        ignore keys they don't recognize.
        """
        db = get_db(app.config["DATABASE_PATH"])
        slots = db.execute(
            """
            SELECT
              s.id            AS slot_id,
              s.bank_order    AS bank_order,
              s.kind          AS kind,
              p.id            AS person_id,
              p.display_name  AS person_name,
              p.nickname      AS person_nickname,
              p.photo_url     AS photo_url,
              mc.id           AS mic_channel_id,
              mc.label        AS mic_label,
              mc.shure_channel AS mic_shure_channel,
              mc.shure_ip      AS mic_shure_ip,
              mc.shure_type    AS mic_shure_type,
              mc.capsule       AS mic_capsule,
              ic.id           AS iem_channel_id,
              ic.label        AS iem_label,
              ic.shure_channel AS iem_shure_channel,
              ic.shure_ip      AS iem_shure_ip,
              ic.shure_type    AS iem_shure_type
            FROM slot s
            LEFT JOIN person  p  ON p.id = s.person_id
            LEFT JOIN channel mc ON mc.id = s.mic_channel_id
            LEFT JOIN channel ic ON ic.id = s.iem_channel_id
            WHERE s.archived = 0
            ORDER BY s.bank_order
            """
        ).fetchall()

        rows = []
        for row in slots:
            d = dict(row)
            # Live state placeholder. The Shure worker (future commit)
            # will populate `live` keyed by (shure_ip, shure_channel).
            # For now, every slot is in "unknown" state.
            d["mic_live"] = None
            d["iem_live"] = None
            rows.append(d)

        return jsonify({"slots": rows})


def register_teardown(app: Flask) -> None:
    @app.teardown_appcontext
    def close_db(_exc):
        from db import close_db
        close_db()


app = create_app()


if __name__ == "__main__":
    # Direct invocation for local dev. Production runs through gunicorn
    # in the container.
    app.run(host="0.0.0.0", port=8058, debug=True)
