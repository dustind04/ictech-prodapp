"""
icTech Services — production tooling for Immanuel Church.

This commit adds the admin CRUD UI (people, channels, slot assignments)
plus a real wall display rendering the 10-slot grid from live data.

Architecture is intentionally boring:
  - Flask + SQLite + server-rendered Jinja2 templates
  - Forms POST to the same controller that rendered them
  - The wall display polls /api/state every 2s for updates
  - No client-side framework; vanilla JS for the polling

Routes are grouped under three Blueprints in this single file for now.
If app.py grows past ~500 lines we'll split it up; today's complexity
doesn't warrant the file structure.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from flask import (
    Flask,
    abort,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    url_for,
)

from db import get_db, init_db


logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("ictech")


# ---------------------------------------------------------------
# Channel kinds + Shure receiver types — the only enum-like values
# we need at the application layer. The DB CHECKs are the source
# of truth; these constants are for form validation + dropdowns.
# ---------------------------------------------------------------
CHANNEL_KINDS = ["handheld", "beltpack", "iem"]
SHURE_TYPES = ["qlxd", "ulxd", "axtd", "p10t", "uhfr"]
SHURE_TYPE_LABELS = {
    "qlxd": "QLX-D",
    "ulxd": "ULX-D",
    "axtd": "Axient Digital",
    "p10t": "PSM 1000",
    "uhfr": "UHF-R",
}


def create_app() -> Flask:
    app = Flask(__name__, static_folder="static", template_folder="templates")
    app.config["DATABASE_PATH"] = os.environ.get(
        "ICTECH_DB", str(Path(__file__).parent / "data" / "ictech.db")
    )
    # Flash messaging needs a secret key. For a single-instance internal app
    # this can come from env or default to a fixed string.
    app.config["SECRET_KEY"] = os.environ.get("ICTECH_SECRET", "ictech-dev-secret")

    init_db(app.config["DATABASE_PATH"])

    register_display_routes(app)
    register_api_routes(app)
    register_admin_routes(app)
    register_teardown(app)
    return app


# =============================================================
# Display routes — the wall display itself
# =============================================================
def register_display_routes(app: Flask) -> None:
    @app.route("/")
    def wall_display():
        """The backstage wall display.

        Renders the static page shell. All data comes from /api/state via
        client-side polling — that way the page never reloads, keeps its
        scroll position, and degrades gracefully when the server hiccups.
        """
        return render_template("wall.html")


# =============================================================
# API routes — for the wall display to poll
# =============================================================
def register_api_routes(app: Flask) -> None:
    @app.route("/api/state")
    def api_state():
        """Snapshot of slot assignments. Live receiver data will be added
        in commit 3; today everything is static config data."""
        db = get_db(app.config["DATABASE_PATH"])
        slots = db.execute(_SLOT_QUERY).fetchall()
        rows = []
        for row in slots:
            d = dict(row)
            # Reserved keys for future live state overlay (commit 3).
            d["mic_live"] = None
            d["iem_live"] = None
            rows.append(d)
        return jsonify({"slots": rows})


# Single source of truth for the slot-resolution query. Used by both
# /api/state and the admin slots page so changes apply consistently.
_SLOT_QUERY = """
    SELECT
      s.id            AS slot_id,
      s.bank_order    AS bank_order,
      s.kind          AS kind,
      s.person_id     AS person_id,
      p.display_name  AS person_name,
      p.nickname      AS person_nickname,
      p.photo_url     AS photo_url,
      s.mic_channel_id AS mic_channel_id,
      mc.label         AS mic_label,
      mc.shure_channel AS mic_shure_channel,
      mc.shure_ip      AS mic_shure_ip,
      mc.shure_type    AS mic_shure_type,
      mc.capsule       AS mic_capsule,
      s.iem_channel_id AS iem_channel_id,
      ic.label         AS iem_label,
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


# =============================================================
# Admin routes — form-based CRUD for people, channels, slots
# =============================================================
def register_admin_routes(app: Flask) -> None:
    db_path = app.config["DATABASE_PATH"]

    # --- Index ---
    @app.route("/admin")
    def admin_index():
        db = get_db(db_path)
        counts = {
            "people":   db.execute("SELECT COUNT(*) c FROM person  WHERE archived=0").fetchone()["c"],
            "channels": db.execute("SELECT COUNT(*) c FROM channel WHERE archived=0").fetchone()["c"],
            "assigned_slots": db.execute(
                "SELECT COUNT(*) c FROM slot WHERE archived=0 AND person_id IS NOT NULL"
            ).fetchone()["c"],
        }
        return render_template("admin/index.html", counts=counts)

    # --- People ---
    @app.route("/admin/people")
    def admin_people():
        db = get_db(db_path)
        people = db.execute(
            "SELECT * FROM person WHERE archived=0 ORDER BY COALESCE(nickname, display_name)"
        ).fetchall()
        return render_template("admin/people.html", people=people)

    @app.route("/admin/people", methods=["POST"])
    def admin_people_create():
        db = get_db(db_path)
        name = (request.form.get("display_name") or "").strip()
        if not name:
            flash("Name is required.", "error")
            return redirect(url_for("admin_people"))
        nickname = (request.form.get("nickname") or "").strip() or None
        photo_url = (request.form.get("photo_url") or "").strip() or None
        db.execute(
            "INSERT INTO person (display_name, nickname, photo_url) VALUES (?, ?, ?)",
            (name, nickname, photo_url),
        )
        db.commit()
        flash(f"Added {name}.", "success")
        return redirect(url_for("admin_people"))

    @app.route("/admin/people/<int:person_id>/edit")
    def admin_people_edit(person_id):
        db = get_db(db_path)
        person = db.execute("SELECT * FROM person WHERE id=?", (person_id,)).fetchone()
        if not person:
            abort(404)
        return render_template("admin/person_edit.html", person=person)

    @app.route("/admin/people/<int:person_id>", methods=["POST"])
    def admin_people_update(person_id):
        db = get_db(db_path)
        person = db.execute("SELECT id FROM person WHERE id=?", (person_id,)).fetchone()
        if not person:
            abort(404)
        action = request.form.get("action", "update")
        if action == "archive":
            db.execute(
                "UPDATE person SET archived=1, updated_at=datetime('now') WHERE id=?",
                (person_id,),
            )
            db.commit()
            flash("Archived.", "success")
            return redirect(url_for("admin_people"))
        # Otherwise normal update
        name = (request.form.get("display_name") or "").strip()
        if not name:
            flash("Name is required.", "error")
            return redirect(url_for("admin_people_edit", person_id=person_id))
        nickname = (request.form.get("nickname") or "").strip() or None
        photo_url = (request.form.get("photo_url") or "").strip() or None
        db.execute(
            """UPDATE person SET display_name=?, nickname=?, photo_url=?,
                                  updated_at=datetime('now') WHERE id=?""",
            (name, nickname, photo_url, person_id),
        )
        db.commit()
        flash(f"Updated {name}.", "success")
        return redirect(url_for("admin_people"))

    # --- Channels ---
    @app.route("/admin/channels")
    def admin_channels():
        db = get_db(db_path)
        channels = db.execute(
            "SELECT * FROM channel WHERE archived=0 ORDER BY kind, label"
        ).fetchall()
        return render_template(
            "admin/channels.html",
            channels=channels,
            kinds=CHANNEL_KINDS,
            shure_types=SHURE_TYPES,
            shure_type_labels=SHURE_TYPE_LABELS,
        )

    @app.route("/admin/channels", methods=["POST"])
    def admin_channels_create():
        db = get_db(db_path)
        label = (request.form.get("label") or "").strip()
        kind = (request.form.get("kind") or "").strip()
        if not label or kind not in CHANNEL_KINDS:
            flash("Label and kind are required.", "error")
            return redirect(url_for("admin_channels"))
        values = _channel_form_values(request.form, label, kind)
        db.execute(
            """INSERT INTO channel
                 (label, kind, shure_ip, shure_channel, shure_type,
                  capsule, frequency_mhz)
               VALUES (:label, :kind, :shure_ip, :shure_channel, :shure_type,
                       :capsule, :frequency_mhz)""",
            values,
        )
        db.commit()
        flash(f"Added channel {label}.", "success")
        return redirect(url_for("admin_channels"))

    @app.route("/admin/channels/<int:channel_id>/edit")
    def admin_channels_edit(channel_id):
        db = get_db(db_path)
        channel = db.execute("SELECT * FROM channel WHERE id=?", (channel_id,)).fetchone()
        if not channel:
            abort(404)
        return render_template(
            "admin/channel_edit.html",
            channel=channel,
            kinds=CHANNEL_KINDS,
            shure_types=SHURE_TYPES,
            shure_type_labels=SHURE_TYPE_LABELS,
        )

    @app.route("/admin/channels/<int:channel_id>", methods=["POST"])
    def admin_channels_update(channel_id):
        db = get_db(db_path)
        channel = db.execute("SELECT id FROM channel WHERE id=?", (channel_id,)).fetchone()
        if not channel:
            abort(404)
        action = request.form.get("action", "update")
        if action == "archive":
            db.execute(
                "UPDATE channel SET archived=1, updated_at=datetime('now') WHERE id=?",
                (channel_id,),
            )
            db.commit()
            flash("Archived.", "success")
            return redirect(url_for("admin_channels"))
        label = (request.form.get("label") or "").strip()
        kind = (request.form.get("kind") or "").strip()
        if not label or kind not in CHANNEL_KINDS:
            flash("Label and kind are required.", "error")
            return redirect(url_for("admin_channels_edit", channel_id=channel_id))
        values = _channel_form_values(request.form, label, kind)
        values["id"] = channel_id
        db.execute(
            """UPDATE channel SET
                 label=:label, kind=:kind,
                 shure_ip=:shure_ip, shure_channel=:shure_channel, shure_type=:shure_type,
                 capsule=:capsule, frequency_mhz=:frequency_mhz,
                 updated_at=datetime('now')
               WHERE id=:id""",
            values,
        )
        db.commit()
        flash(f"Updated {label}.", "success")
        return redirect(url_for("admin_channels"))

    # --- Slots ---
    @app.route("/admin/slots")
    def admin_slots():
        db = get_db(db_path)
        slots = db.execute(_SLOT_QUERY).fetchall()
        people = db.execute(
            "SELECT id, display_name, nickname FROM person WHERE archived=0 "
            "ORDER BY COALESCE(nickname, display_name)"
        ).fetchall()
        # For each slot kind we offer a different subset of channels:
        #   paired slots (1-6): mic dropdown = handhelds, iem dropdown = IEMs
        #   mic_only slots (7-10): mic dropdown = beltpacks only
        handhelds = db.execute(
            "SELECT id, label FROM channel WHERE archived=0 AND kind='handheld' ORDER BY label"
        ).fetchall()
        beltpacks = db.execute(
            "SELECT id, label FROM channel WHERE archived=0 AND kind='beltpack' ORDER BY label"
        ).fetchall()
        iems = db.execute(
            "SELECT id, label FROM channel WHERE archived=0 AND kind='iem' ORDER BY label"
        ).fetchall()
        return render_template(
            "admin/slots.html",
            slots=slots,
            people=people,
            handhelds=handhelds,
            beltpacks=beltpacks,
            iems=iems,
        )

    @app.route("/admin/slots/<int:slot_id>", methods=["POST"])
    def admin_slots_update(slot_id):
        db = get_db(db_path)
        slot = db.execute("SELECT id, kind FROM slot WHERE id=?", (slot_id,)).fetchone()
        if not slot:
            abort(404)

        def _none_if_blank(v):
            v = (v or "").strip()
            return int(v) if v.isdigit() else None

        person_id = _none_if_blank(request.form.get("person_id"))
        mic_id    = _none_if_blank(request.form.get("mic_channel_id"))
        iem_id    = _none_if_blank(request.form.get("iem_channel_id"))

        # mic_only slots can't have an IEM regardless of what was posted
        if slot["kind"] == "mic_only":
            iem_id = None

        db.execute(
            """UPDATE slot SET
                 person_id=?, mic_channel_id=?, iem_channel_id=?,
                 updated_at=datetime('now')
               WHERE id=?""",
            (person_id, mic_id, iem_id, slot_id),
        )
        db.commit()
        flash(f"Slot {slot_id} updated.", "success")
        return redirect(url_for("admin_slots"))


# =============================================================
# Helpers
# =============================================================
def _channel_form_values(form, label: str, kind: str) -> dict:
    """Coerce raw form values into the dict shape we insert/update with."""
    def _opt_str(name):
        v = (form.get(name) or "").strip()
        return v or None
    def _opt_int(name):
        v = (form.get(name) or "").strip()
        return int(v) if v.isdigit() else None
    def _opt_float(name):
        v = (form.get(name) or "").strip()
        try:
            return float(v) if v else None
        except ValueError:
            return None
    shure_type = _opt_str("shure_type")
    if shure_type and shure_type not in SHURE_TYPES:
        shure_type = None
    return {
        "label": label,
        "kind": kind,
        "shure_ip": _opt_str("shure_ip"),
        "shure_channel": _opt_int("shure_channel"),
        "shure_type": shure_type,
        "capsule": _opt_str("capsule"),
        "frequency_mhz": _opt_float("frequency_mhz"),
    }


def register_teardown(app: Flask) -> None:
    @app.teardown_appcontext
    def close_db(_exc):
        from db import close_db
        close_db()


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8058, debug=True)
