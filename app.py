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
import secrets
from pathlib import Path

from flask import (
    Flask,
    Response,
    abort,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    send_from_directory,
    url_for,
)
from werkzeug.utils import secure_filename

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

# ---------------------------------------------------------------
# Photo upload constraints.
#   - Accepted MIME-mapped extensions only; we trust the browser
#     extension after stripping with secure_filename but cross-check
#     against the bytes' content-type Werkzeug parsed from the upload.
#   - 8 MB cap. Big enough for a high-res phone photo, small enough
#     that a misuse attempt can't fill the disk.
# ---------------------------------------------------------------
ALLOWED_PHOTO_EXTS = {"jpg", "jpeg", "png", "webp", "gif"}
ALLOWED_PHOTO_MIMES = {
    "image/jpeg", "image/png", "image/webp", "image/gif",
}
MAX_PHOTO_BYTES = 8 * 1024 * 1024  # 8 MB


def create_app() -> Flask:
    app = Flask(__name__, static_folder="static", template_folder="templates")
    app.config["DATABASE_PATH"] = os.environ.get(
        "ICTECH_DB", str(Path(__file__).parent / "data" / "ictech.db")
    )
    # Flash messaging needs a secret key. For a single-instance internal app
    # this can come from env or default to a fixed string.
    app.config["SECRET_KEY"] = os.environ.get("ICTECH_SECRET", "ictech-dev-secret")

    # Photo storage: defaults to a sibling of the DB. Both live under /data
    # in production so the persistent volume covers both.
    db_dir = Path(app.config["DATABASE_PATH"]).parent
    app.config["PHOTO_DIR"] = os.environ.get(
        "ICTECH_PHOTO_DIR", str(db_dir / "photos")
    )
    Path(app.config["PHOTO_DIR"]).mkdir(parents=True, exist_ok=True)
    # Werkzeug enforces this for us; requests larger than this 413 automatically.
    app.config["MAX_CONTENT_LENGTH"] = MAX_PHOTO_BYTES

    init_db(app.config["DATABASE_PATH"])

    _register_admin_auth(app)
    register_display_routes(app)
    register_api_routes(app)
    register_admin_routes(app)
    register_photo_routes(app)
    register_teardown(app)
    return app


# =============================================================
# Admin auth — HTTP Basic on /admin, only when credentials are
# configured. The backstage-VLAN deployment sets neither var and
# stays open; the internet-facing deployment (Cloudflare tunnel)
# sets both. The wall display and /api/state are always open —
# they're the product.
# =============================================================
def _register_admin_auth(app: Flask) -> None:
    admin_user = os.environ.get("ICTECH_ADMIN_USER")
    admin_password = os.environ.get("ICTECH_ADMIN_PASSWORD")
    if not (admin_user and admin_password):
        return

    @app.before_request
    def require_admin_auth():
        if not request.path.startswith("/admin"):
            return None
        auth = request.authorization
        if (
            auth is not None
            and auth.type == "basic"
            and secrets.compare_digest(auth.username or "", admin_user)
            and secrets.compare_digest(auth.password or "", admin_password)
        ):
            return None
        return Response(
            "Authentication required.",
            401,
            {"WWW-Authenticate": 'Basic realm="icTech admin"'},
        )


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
      ic.shure_type    AS iem_shure_type,
      s.position_id    AS position_id,
      pos.label        AS position_label,
      s.mymix_channel  AS mymix_channel
    FROM slot s
    LEFT JOIN person  p   ON p.id = s.person_id
    LEFT JOIN channel mc  ON mc.id = s.mic_channel_id
    LEFT JOIN channel ic  ON ic.id = s.iem_channel_id
    LEFT JOIN position pos ON pos.id = s.position_id
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
            "positions": db.execute("SELECT COUNT(*) c FROM position WHERE archived=0").fetchone()["c"],
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
        # Photo: file upload takes priority over URL field
        photo_url = _resolve_photo_input(app, current_filename=None)
        if photo_url is None:
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
        person = db.execute("SELECT * FROM person WHERE id=?", (person_id,)).fetchone()
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
        if action == "remove_photo":
            _delete_managed_photo(app, person["photo_url"])
            db.execute(
                "UPDATE person SET photo_url=NULL, updated_at=datetime('now') WHERE id=?",
                (person_id,),
            )
            db.commit()
            flash("Photo removed.", "success")
            return redirect(url_for("admin_people_edit", person_id=person_id))
        # Otherwise normal update
        name = (request.form.get("display_name") or "").strip()
        if not name:
            flash("Name is required.", "error")
            return redirect(url_for("admin_people_edit", person_id=person_id))
        nickname = (request.form.get("nickname") or "").strip() or None
        # Determine photo: a new upload wins; otherwise keep the URL field's value
        # (which the template pre-fills with the existing value).
        current_managed_url = person["photo_url"] if _is_managed_photo(person["photo_url"]) else None
        current_managed_filename = (
            current_managed_url[len(_MANAGED_PHOTO_PREFIX):] if current_managed_url else None
        )
        uploaded = _resolve_photo_input(app, current_filename=current_managed_filename)
        if uploaded is not None:
            photo_url = uploaded
        else:
            posted_url = (request.form.get("photo_url") or "").strip() or None
            # If the user is *changing* away from a managed photo to a different URL
            # (or clearing it), clean up the old file.
            if current_managed_url and posted_url != person["photo_url"]:
                _delete_managed_photo(app, person["photo_url"])
            photo_url = posted_url
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
            """SELECT c.*, wm.family AS wm_family, wm.model AS wm_model,
                      cm.brand AS cm_brand, cm.model AS cm_model
                 FROM channel c
                 LEFT JOIN wireless_model wm ON wm.id = c.wireless_model_id
                 LEFT JOIN capsule_model cm ON cm.id = c.capsule_model_id
                WHERE c.archived=0 ORDER BY c.kind, c.label"""
        ).fetchall()
        return render_template(
            "admin/channels.html",
            channels=channels,
            kinds=CHANNEL_KINDS,
            shure_types=SHURE_TYPES,
            shure_type_labels=SHURE_TYPE_LABELS,
            **_gear_catalog(db),
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
        _validate_gear_ids(db, values)
        db.execute(
            """INSERT INTO channel
                 (label, kind, shure_ip, shure_channel, shure_type,
                  capsule, frequency_mhz, wireless_model_id, capsule_model_id)
               VALUES (:label, :kind, :shure_ip, :shure_channel, :shure_type,
                       :capsule, :frequency_mhz, :wireless_model_id, :capsule_model_id)""",
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
            **_gear_catalog(db),
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
        _validate_gear_ids(db, values)
        values["id"] = channel_id
        db.execute(
            """UPDATE channel SET
                 label=:label, kind=:kind,
                 shure_ip=:shure_ip, shure_channel=:shure_channel, shure_type=:shure_type,
                 capsule=:capsule, frequency_mhz=:frequency_mhz,
                 wireless_model_id=:wireless_model_id, capsule_model_id=:capsule_model_id,
                 updated_at=datetime('now')
               WHERE id=:id""",
            values,
        )
        db.commit()
        flash(f"Updated {label}.", "success")
        return redirect(url_for("admin_channels"))

    # --- Positions ---
    @app.route("/admin/positions")
    def admin_positions():
        db = get_db(db_path)
        positions = db.execute(
            "SELECT * FROM position WHERE archived=0 ORDER BY label"
        ).fetchall()
        return render_template("admin/positions.html", positions=positions)

    @app.route("/admin/positions", methods=["POST"])
    def admin_positions_create():
        db = get_db(db_path)
        label = (request.form.get("label") or "").strip()
        if not label:
            flash("Label is required.", "error")
            return redirect(url_for("admin_positions"))
        db.execute("INSERT INTO position (label) VALUES (?)", (label,))
        db.commit()
        flash(f"Added position {label}.", "success")
        return redirect(url_for("admin_positions"))

    @app.route("/admin/positions/<int:position_id>/edit")
    def admin_positions_edit(position_id):
        db = get_db(db_path)
        position = db.execute("SELECT * FROM position WHERE id=?", (position_id,)).fetchone()
        if not position:
            abort(404)
        return render_template("admin/position_edit.html", position=position)

    @app.route("/admin/positions/<int:position_id>", methods=["POST"])
    def admin_positions_update(position_id):
        db = get_db(db_path)
        position = db.execute("SELECT id FROM position WHERE id=?", (position_id,)).fetchone()
        if not position:
            abort(404)
        action = request.form.get("action", "update")
        if action == "archive":
            db.execute(
                "UPDATE position SET archived=1, updated_at=datetime('now') WHERE id=?",
                (position_id,),
            )
            db.commit()
            flash("Archived.", "success")
            return redirect(url_for("admin_positions"))
        label = (request.form.get("label") or "").strip()
        if not label:
            flash("Label is required.", "error")
            return redirect(url_for("admin_positions_edit", position_id=position_id))
        db.execute(
            "UPDATE position SET label=?, updated_at=datetime('now') WHERE id=?",
            (label, position_id),
        )
        db.commit()
        flash(f"Updated {label}.", "success")
        return redirect(url_for("admin_positions"))

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
        positions = db.execute(
            "SELECT id, label FROM position WHERE archived=0 ORDER BY label"
        ).fetchall()
        return render_template(
            "admin/slots.html",
            slots=slots,
            people=people,
            handhelds=handhelds,
            beltpacks=beltpacks,
            iems=iems,
            positions=positions,
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

        person_id   = _none_if_blank(request.form.get("person_id"))
        mic_id      = _none_if_blank(request.form.get("mic_channel_id"))
        iem_id      = _none_if_blank(request.form.get("iem_channel_id"))
        position_id = _none_if_blank(request.form.get("position_id"))
        mymix_channel = (request.form.get("mymix_channel") or "").strip() or None

        # mic_only slots can't have an IEM regardless of what was posted
        if slot["kind"] == "mic_only":
            iem_id = None

        db.execute(
            """UPDATE slot SET
                 person_id=?, mic_channel_id=?, iem_channel_id=?, position_id=?,
                 mymix_channel=?,
                 updated_at=datetime('now')
               WHERE id=?""",
            (person_id, mic_id, iem_id, position_id, mymix_channel, slot_id),
        )
        db.commit()
        flash(f"Slot {slot_id} updated.", "success")
        return redirect(url_for("admin_slots"))


# =============================================================
# Photo routes — serve uploaded files from disk
# =============================================================
def register_photo_routes(app: Flask) -> None:
    @app.route("/photos/<path:filename>")
    def serve_photo(filename):
        """Serve an uploaded person photo. send_from_directory enforces
        path safety (rejects ../ traversal). We additionally check the
        filename is one of ours."""
        if not _is_safe_managed_filename(filename):
            abort(404)
        return send_from_directory(
            app.config["PHOTO_DIR"],
            filename,
            max_age=3600,  # 1h cache; we rotate names on replacement so this is safe
        )


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
        "wireless_model_id": _opt_int("wireless_model_id"),
        "capsule_model_id": _opt_int("capsule_model_id"),
    }


def _validate_gear_ids(db, values: dict) -> None:
    """Null out gear FK values that don't exist — a stale form beats a 500."""
    for col, table in (
        ("wireless_model_id", "wireless_model"),
        ("capsule_model_id", "capsule_model"),
    ):
        if values[col] is not None:
            row = db.execute(f"SELECT 1 FROM {table} WHERE id=?", (values[col],)).fetchone()
            if row is None:
                values[col] = None


def _gear_catalog(db) -> dict:
    """The seeded equipment catalogs, shaped for the channel-form dropdowns."""
    return {
        "wireless_models": db.execute(
            "SELECT * FROM wireless_model ORDER BY kind, sort_order, model"
        ).fetchall(),
        "capsule_models": db.execute(
            "SELECT * FROM capsule_model ORDER BY brand, sort_order, model"
        ).fetchall(),
    }


# -------- Photo upload helpers --------
#
# Storage convention: managed photo URLs always look like
#   /photos/<random-hex>.<ext>
# This lets us distinguish them from externally-pasted URLs (which start
# with http:// or https:// or a custom CDN path). When a person's
# photo_url has the /photos/ prefix we own the underlying file and are
# responsible for cleaning it up on replacement or removal.

_MANAGED_PHOTO_PREFIX = "/photos/"


def _is_managed_photo(photo_url: str | None) -> bool:
    return bool(photo_url) and photo_url.startswith(_MANAGED_PHOTO_PREFIX)


def _is_safe_managed_filename(filename: str) -> bool:
    """Defense in depth: only serve files that look like ones we wrote.
    Format: <40-hex-chars>.<ext>"""
    if "/" in filename or "\\" in filename or ".." in filename:
        return False
    name, _, ext = filename.rpartition(".")
    if not name or not ext:
        return False
    if ext.lower() not in ALLOWED_PHOTO_EXTS:
        return False
    if len(name) < 16 or not all(c in "0123456789abcdef" for c in name):
        return False
    return True


def _resolve_photo_input(app: Flask, current_filename: str | None) -> str | None:
    """Process the file upload field on the form, if any.

    Returns:
      - A new "/photos/<name>" URL if a valid file was uploaded.
      - None if no upload (caller should fall back to other inputs).

    Deletes the previous managed photo if a replacement is being saved.
    Sets a flash message and returns None on validation failures, which
    the caller treats as "no upload happened".
    """
    f = request.files.get("photo_file")
    if not f or not (f.filename or "").strip():
        return None

    raw_name = secure_filename(f.filename) or ""
    ext = raw_name.rsplit(".", 1)[-1].lower() if "." in raw_name else ""
    if ext not in ALLOWED_PHOTO_EXTS:
        flash("Photo must be JPG, PNG, WebP, or GIF.", "error")
        return None
    # MIME cross-check: trust browser headers but verify against allow-list
    if f.mimetype not in ALLOWED_PHOTO_MIMES:
        flash(f"Unsupported image type: {f.mimetype}", "error")
        return None

    # Generate a random filename; never trust the user's. 20 bytes = 40 hex chars.
    new_name = f"{secrets.token_hex(20)}.{ext}"
    photo_dir = Path(app.config["PHOTO_DIR"])
    photo_dir.mkdir(parents=True, exist_ok=True)
    target = photo_dir / new_name
    f.save(str(target))

    # Replacement: delete the old managed file (if any). Failure to delete
    # doesn't roll back the save -- the orphan is harmless and a future
    # cleanup script can collect it.
    if current_filename:
        old_path = photo_dir / current_filename
        try:
            old_path.unlink()
        except FileNotFoundError:
            pass
        except OSError as e:
            log.warning("Could not remove old photo %s: %s", old_path, e)

    return f"{_MANAGED_PHOTO_PREFIX}{new_name}"


def _delete_managed_photo(app: Flask, photo_url: str | None) -> None:
    """Delete the on-disk file backing a managed photo URL, if it exists."""
    if not _is_managed_photo(photo_url):
        return
    filename = photo_url[len(_MANAGED_PHOTO_PREFIX):]
    if not _is_safe_managed_filename(filename):
        return
    path = Path(app.config["PHOTO_DIR"]) / filename
    try:
        path.unlink()
    except FileNotFoundError:
        pass
    except OSError as e:
        log.warning("Could not remove photo %s: %s", path, e)


def register_teardown(app: Flask) -> None:
    @app.teardown_appcontext
    def close_db(_exc):
        from db import close_db
        close_db()


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8058, debug=True)
