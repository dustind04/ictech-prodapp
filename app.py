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
from datetime import datetime, timedelta, timezone
from io import BytesIO
from pathlib import Path
from zoneinfo import ZoneInfo

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
import segno
from werkzeug.utils import secure_filename

import importer
import stageplot
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
# Asset management. Statuses are the DB CHECK's values; categories
# are only suggestions (free text in the schema by design).
# ---------------------------------------------------------------
ASSET_STATUSES = {
    "in_service": "In service",
    "storage":    "In storage",
    "repair":     "In repair",
    "loaned":     "Loaned out",
    "missing":    "Missing",
    "retired":    "Retired",
}
# ---------------------------------------------------------------
# Weekly reset: the wall must not keep showing last Sunday's roster.
# Every week is cleared automatically at 1 PM Sunday (church local
# time) unless the new week's files were already imported.
# ---------------------------------------------------------------
CHURCH_TZ = ZoneInfo("America/Chicago")
WEEKLY_CLEAR_WEEKDAY = 6   # Sunday (Monday=0)
WEEKLY_CLEAR_HOUR = 13     # 1 PM

ASSET_CATEGORIES = [
    "wireless", "iem", "microphone", "receiver", "console", "stagebox",
    "di", "speaker", "monitor", "computer", "video", "lighting",
    "cable", "stand", "case", "other",
]

# ---------------------------------------------------------------
# Build-your-own dashboards: the widget vocabulary. Each entry is
# type -> (label, hint) for the builder palette; rendering lives in
# templates/_dash_widgets.html. Unknown types in a saved config are
# ignored at render, so removing one here never breaks a dashboard.
# ---------------------------------------------------------------
DASH_WIDGETS = {
    "header":     ("Header", "Logo, Welcome HOME mark, schedule line"),
    "thisweek":   ("This Week", "Service date, leader, live countdown"),
    "clock":      ("Clock", "Big time + date (church time)"),
    "vocals":     ("Vocals zone", "Slot tiles 1–6"),
    "band":       ("Band zone", "Seat tiles 11–16"),
    "speakers":   ("Speakers zone", "Slot tiles 7–10"),
    "techcrew":   ("Tech crew", "Who's behind the controls"),
    "patch":      ("Patch list", "Full input list w/ phantom + routing"),
    "iemrf":      ("IEM RF", "Pack → RF path assignments"),
    "mymixlegend": ("MyMix legend", "The 16 personal-mixer channels"),
    "mixers":     ("Mixer owners", "Which MyMix unit belongs to whom"),
    "stageplot":  ("Stage plot", "This week's auto-drawn plot"),
    "notes":      ("Notes", "Free text — announcements, reminders"),
}
# Layout canvas: widgets carry x/y/w/h on a 24x12 grid over the TV's
# screen, so a dashboard lays out EXACTLY as designed at that aspect
# ratio (mismatched TVs letterbox). Sizes below are the defaults a
# widget gets when dropped on the canvas (and what v1 flow configs
# convert to).
DASH_COLS, DASH_ROWS = 24, 12
DASH_DEFAULT_SIZES = {
    "header": (24, 2), "thisweek": (8, 3), "clock": (6, 3),
    "vocals": (24, 5), "band": (24, 5), "speakers": (16, 5),
    "techcrew": (12, 2), "patch": (12, 10), "iemrf": (8, 4),
    "mymixlegend": (24, 3), "mixers": (6, 4), "stageplot": (10, 7),
    "notes": (6, 3),
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
    # Photographer role: valid ONLY under /admin/photos — lets a
    # volunteer manage headshots without the keys to anything else.
    photo_user = os.environ.get("ICTECH_PHOTO_USER")
    photo_password = os.environ.get("ICTECH_PHOTO_PASSWORD")
    if not (admin_user and admin_password):
        return

    def _ok(auth, user, password):
        return (auth is not None and auth.type == "basic"
                and user and password
                and secrets.compare_digest(auth.username or "", user)
                and secrets.compare_digest(auth.password or "", password))

    @app.before_request
    def require_admin_auth():
        if not request.path.startswith("/admin"):
            return None
        auth = request.authorization
        if _ok(auth, admin_user, admin_password):
            return None
        if request.path.startswith("/admin/photos") and _ok(auth, photo_user, photo_password):
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
        """Home = the dataviz view (the evolving display)."""
        return render_template("wall.html")

    @app.route("/micboard")
    def micboard_display():
        """The TV directly above the charger banks. Same design as the
        home wall, pinned to physical reality: every slot renders in
        its fixed position (slot 03 on screen = charger 3), empties
        included, no collapse/merge, and an admin-set column width so
        the on-screen columns line up with the chargers below."""
        return render_template("wall.html", pinned=True)

    @app.route("/dataviz")
    def dataviz_display():
        """The evolving display view (auto-collapse and onward)."""
        return render_template("wall.html")

    # Short aliases — every character hurts on a TV remote.
    @app.route("/mb")
    def mb_alias():
        return redirect(url_for("micboard_display"))

    @app.route("/tech")
    @app.route("/td")
    def tech_alias():
        return redirect(url_for("techdashboard"))

    @app.route("/tv")
    def tv_picker():
        """One-time TV setup page: type the host, tap a big button.
        Each display bookmarks/lands itself from here."""
        db = get_db(app.config["DATABASE_PATH"])
        dashboards = db.execute(
            "SELECT slug, name FROM dashboard WHERE archived=0 ORDER BY name"
        ).fetchall()
        return render_template("tv.html", dashboards=dashboards)

    # --- Build-your-own dashboards ---
    @app.route("/d/<slug>")
    def dashboard_display(slug):
        """A custom dashboard, TV-ready. ?partial=1 returns just the
        widget grid — the page swaps it in every 10s to stay live
        without reloading."""
        import json as _json
        db = get_db(app.config["DATABASE_PATH"])
        row = db.execute(
            "SELECT * FROM dashboard WHERE slug=? AND archived=0", (slug,)
        ).fetchone()
        if not row:
            abort(404)
        config = _parse_dash_config(row["config"])
        ctx = _dashboard_context(db, config)
        if request.args.get("partial"):
            return render_template("_dash_widgets.html",
                                   widgets=config["widgets"], **ctx)
        return render_template("dashboard.html", dash=row,
                               widgets=config["widgets"], **ctx)

    @app.route("/stageplot.svg")
    def stageplot_svg():
        """Public copy of the stage plot for dashboard embeds (the
        admin route stays gated on tunnel deployments)."""
        db = get_db(app.config["DATABASE_PATH"])
        settings = {r["key"]: r["value"] for r in
                    db.execute("SELECT key, value FROM app_setting")}
        svg = stageplot.build_stage_plot(
            db, service_label=settings.get("import_source"),
            generated=settings.get("import_at"))
        return Response(svg, mimetype="image/svg+xml",
                        headers={"Cache-Control": "no-store"})

    @app.route("/snapshot/<name>.jpg")
    def snapshot(name):
        """Latest JPEG render of a display, produced by the Playwright
        sidecar — what the Roku channel polls. 404 until the sidecar
        has produced its first frame."""
        if name not in ("dashboard", "mb", "tech"):
            abort(404)
        snap_dir = Path(app.config["DATABASE_PATH"]).parent / "snapshots"
        if not (snap_dir / f"{name}.jpg").exists():
            abort(404)
        resp = send_from_directory(snap_dir, f"{name}.jpg", max_age=0)
        resp.headers["Cache-Control"] = "no-store"
        return resp

    @app.route("/backline")
    def backline_redirect():
        return redirect(url_for("techdashboard"))

    # --- Asset scan targets (public: a phone scanning a gear label
    # lands here; the LAN deployment has no auth in the way) ---
    @app.route("/a/<tag>")
    def asset_card(tag):
        db = get_db(app.config["DATABASE_PATH"])
        asset = db.execute(
            """SELECT a.*, c.label AS channel_label FROM asset a
               LEFT JOIN channel c ON c.id = a.channel_id
               WHERE upper(a.tag)=upper(?)""", (tag,)).fetchone()
        if not asset:
            abort(404)
        return render_template("asset_card.html", asset=asset,
                               statuses=ASSET_STATUSES)

    @app.route("/a/<tag>.svg")
    def asset_qr(tag):
        """QR code for a gear label. Encodes the absolute /a/<tag> URL
        against whatever host serves the request, so labels printed off
        the Pi point phones at the Pi."""
        db = get_db(app.config["DATABASE_PATH"])
        if not db.execute("SELECT 1 FROM asset WHERE upper(tag)=upper(?)",
                          (tag,)).fetchone():
            abort(404)
        url = url_for("asset_card", tag=tag, _external=True)
        buf = BytesIO()
        segno.make(url, error="m").save(buf, kind="svg", scale=4, border=1,
                                        dark="#1F1F1F")
        return Response(buf.getvalue(), mimetype="image/svg+xml",
                        headers={"Cache-Control": "max-age=86400"})

    @app.route("/techdashboard")
    def techdashboard():
        """Tech dashboard: the full technical layer of the weekly
        workbook — patch list, phantom flags, monitor routing, IEM RF
        paths, MyMix legend, mixer ownership. Server-rendered,
        auto-refreshes; deliberately dense and unpretty."""
        db = get_db(app.config["DATABASE_PATH"])
        _maybe_weekly_clear(db)
        patch = db.execute("SELECT * FROM patch_row ORDER BY sort_order").fetchall()
        settings = {r["key"]: r["value"] for r in
                    db.execute("SELECT key, value FROM app_setting")}
        return render_template(
            "techdashboard.html",
            patch=patch,
            channels=db.execute(
                "SELECT * FROM channel WHERE archived=0 ORDER BY kind, label"
            ).fetchall(),
            iem_rf=db.execute("SELECT * FROM iem_rf ORDER BY sort_order").fetchall(),
            legend=db.execute("SELECT * FROM mymix_channel ORDER BY ch").fetchall(),
            mixers=db.execute("SELECT * FROM mymix_mixer ORDER BY sort_order").fetchall(),
            phantom_count=sum(1 for p in patch if p["phantom"]),
            import_source=settings.get("import_source"),
            import_at=settings.get("import_at"),
        )

    @app.route("/designs/<int:variant>")
    def design_preview(variant):
        """Three white-sheet design candidates for the wall — static
        renderings of the July 19 demo data with real photos. Pick one,
        then it gets ported to the live wall. Not polled, not the DB."""
        if variant not in (1, 2, 3):
            abort(404)
        db = get_db(app.config["DATABASE_PATH"])
        photos = {r["display_name"]: r["photo_url"]
                  for r in db.execute("SELECT display_name, photo_url FROM person")}
        # On white sheets, "white" mics rim in warm gray so they read.
        rim_hex = {"red": "#D64545", "wht": "#CFCFC9", "blu": "#4A90D9",
                   "blk": "#1F1F1F", "orng": "#E05A0E", "ylo": "#F6DE4C"}

        def s(bank_order, kind, name=None, **kw):
            mic = kw.get("mic_label", "")
            return {
                "bank_order": bank_order, "kind": kind,
                "person_id": kw.get("person_id"), "person_name": name,
                "photo_url": photos.get(name),
                "rim": rim_hex.get(mic.split()[0].lower()) if mic else None,
                "slot_label": kw.get("slot_label"),
                "position_label": kw.get("position_label"),
                "mic_label": mic or None,
                "mic_shure_channel_name": kw.get("chname"),
                "mymix_channel": kw.get("mymix"), "iem_label": kw.get("iem"),
            }

        zones = [
            {"title": "Vocals", "slots": [
                s(1, "paired", "Chris C.", person_id=901, position_label="Pool 2",
                  mic_label="Red HH", chname="Vox 1", mymix="Vox 1", iem="Pack 1"),
                s(2, "paired", "Becky B.", person_id=902, position_label="Pool 3",
                  mic_label="Wht HH", chname="Vox 2", mymix="Vox 2", iem="Pack 2"),
                s(3, "paired", "Kiara H.", person_id=903, position_label="Pool 4",
                  mic_label="Blu HH", chname="Vox 3", mymix="Vox 3", iem="Pack 3"),
                s(4, "paired", "Joanna E.", person_id=904, position_label="Pool 5",
                  mic_label="Blk HH", chname="Vox 4", mymix="Vox 4", iem="Pack 4"),
                s(5, "paired"), s(6, "paired"),
            ]},
            {"title": "Band", "slots": [
                s(11, "band", "Kyle D.", person_id=908, slot_label="Drums", mymix="Drums"),
                s(12, "band", "Chip", person_id=909, slot_label="Bass", mymix="Bass"),
                s(13, "band", "Jo", person_id=910, slot_label="Keys", mymix="Keys"),
                s(14, "band", "Dave H.", person_id=911, slot_label="Elec 1",
                  mymix="Elec 1", iem="Pack 5"),
                s(15, "band", slot_label="Acous"), s(16, "band", slot_label="Synth"),
            ]},
            {"title": "Speakers", "slots": [
                s(7, "mic_only", "Nate B.", person_id=905, position_label="CS Pool",
                  mic_label="Orng RF", mymix="Misc"),
                s(8, "mic_only", "Angel L.", person_id=906, position_label="CS Pool",
                  mic_label="Ylo RF", mymix="Misc"),
                s(9, "mic_only", "Joe B.", person_id=907, mic_label="Sermon RF", mymix="Misc"),
                s(10, "mic_only"),
            ]},
        ]
        return render_template("designs.html", v=variant, zones=zones,
                               leader={"person_id": 901, "name": "Chris C."})


# =============================================================
# API routes — for the wall display to poll
# =============================================================
def register_api_routes(app: Flask) -> None:
    @app.route("/api/state")
    def api_state():
        """Snapshot of slot assignments. Live receiver data will be added
        in commit 3; today everything is static config data."""
        db = get_db(app.config["DATABASE_PATH"])
        _maybe_weekly_clear(db)
        slots = db.execute(_SLOT_QUERY).fetchall()

        # How an instrument gets into the board, from the imported patch
        # list: prefer the specific device (Avalon DI); when the mic
        # column is generic (XLR/DI) fall back to the rig note (IC
        # Kemper); a multi-input source like the drum kit collapses to
        # "Kit Mics".
        patch_by_mymix = {}
        for p in db.execute("SELECT mymix_ch, mic, info, snake_ch FROM patch_row"):
            if p["mymix_ch"]:
                patch_by_mymix.setdefault(p["mymix_ch"], []).append(p)
        GENERIC_INPUTS = {"xlr", "di", "mono di"}

        def input_label(mymix):
            rows_ = [p for p in patch_by_mymix.get(mymix, []) if p["mic"] or p["info"]]
            if not rows_:
                return None
            if len(rows_) > 2:
                drummy = any((p["snake_ch"] or "").lower().startswith("drum") for p in rows_)
                return "Kit Mics" if drummy else f"{len(rows_)} inputs"
            first = rows_[0]
            mic = (first["mic"] or "").strip()
            if mic.lower() in GENERIC_INPUTS and first["info"]:
                return first["info"]
            return mic or first["info"]

        rows = []
        for row in slots:
            d = dict(row)
            d["input_label"] = input_label(d["mymix_channel"]) if d["kind"] == "band" else None
            # Reserved keys for future live state overlay (commit 3).
            d["mic_live"] = None
            d["iem_live"] = None
            rows.append(d)
        mixers = [dict(r) for r in db.execute(
            "SELECT mixer, owner FROM mymix_mixer ORDER BY sort_order")]
        # Display knobs ride the poll: change a value in admin and the
        # TVs pick it up on the next 2s tick — no kiosk fiddling.
        width = db.execute(
            "SELECT value FROM app_setting WHERE key='micboard_col_width'"
        ).fetchone()
        return jsonify({"slots": rows, "leader": _current_leader(db),
                        "mixers": mixers,
                        "settings": {"micboard_col_width":
                                     width["value"] if width else None}})


# Single source of truth for the slot-resolution query. Used by both
# /api/state and the admin slots page so changes apply consistently.
_SLOT_QUERY = """
    SELECT
      s.id            AS slot_id,
      s.bank_order    AS bank_order,
      s.kind          AS kind,
      s.person_id     AS person_id,
      s.label         AS slot_label,
      s.pc_role       AS pc_role,
      p.display_name  AS person_name,
      p.nickname      AS person_nickname,
      p.photo_url     AS photo_url,
      s.mic_channel_id AS mic_channel_id,
      mc.label         AS mic_label,
      mc.kind          AS mic_kind,
      mc.shure_channel AS mic_shure_channel,
      mc.shure_channel_name AS mic_shure_channel_name,
      mc.shure_ip      AS mic_shure_ip,
      mc.shure_type    AS mic_shure_type,
      mc.capsule       AS mic_capsule,
      s.iem_channel_id AS iem_channel_id,
      ic.label         AS iem_label,
      ic.shure_channel AS iem_shure_channel,
      ic.shure_channel_name AS iem_shure_channel_name,
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
            "assets":   db.execute("SELECT COUNT(*) c FROM asset   WHERE archived=0").fetchone()["c"],
            "assigned_slots": db.execute(
                "SELECT COUNT(*) c FROM slot WHERE archived=0 AND person_id IS NOT NULL"
            ).fetchone()["c"],
        }
        width = db.execute(
            "SELECT value FROM app_setting WHERE key='micboard_col_width'"
        ).fetchone()
        return render_template("admin/index.html", counts=counts,
                               micboard_col_width=width["value"] if width else "",
                               update=_update_status())

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
                      cm.brand AS cm_brand, cm.model AS cm_model,
                      rm.model AS rm_model
                 FROM channel c
                 LEFT JOIN wireless_model wm ON wm.id = c.wireless_model_id
                 LEFT JOIN capsule_model cm ON cm.id = c.capsule_model_id
                 LEFT JOIN wireless_model rm ON rm.id = c.receiver_model_id
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
        values["shure_type"] = _derive_shure_type(db, values["receiver_model_id"])
        db.execute(
            """INSERT INTO channel
                 (label, kind, shure_ip, shure_channel_name, shure_type,
                  capsule, frequency_mhz, wireless_model_id, capsule_model_id,
                  receiver_model_id)
               VALUES (:label, :kind, :shure_ip, :shure_channel_name, :shure_type,
                       :capsule, :frequency_mhz, :wireless_model_id, :capsule_model_id,
                       :receiver_model_id)""",
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
        values["shure_type"] = _derive_shure_type(db, values["receiver_model_id"])
        values["id"] = channel_id
        db.execute(
            """UPDATE channel SET
                 label=:label, kind=:kind,
                 shure_ip=:shure_ip, shure_channel_name=:shure_channel_name, shure_type=:shure_type,
                 capsule=:capsule, frequency_mhz=:frequency_mhz,
                 wireless_model_id=:wireless_model_id, capsule_model_id=:capsule_model_id,
                 receiver_model_id=:receiver_model_id,
                 updated_at=datetime('now')
               WHERE id=:id""",
            values,
        )
        db.commit()
        flash(f"Updated {label}.", "success")
        return redirect(url_for("admin_channels"))

    # --- Photos (photographer-accessible) ---
    @app.route("/admin/photos")
    def admin_photos():
        db = get_db(db_path)
        people = db.execute(
            "SELECT id, display_name, photo_url FROM person WHERE archived=0 "
            "ORDER BY display_name"
        ).fetchall()
        return render_template("admin/photos.html", people=people)

    @app.route("/admin/photos/<int:person_id>", methods=["POST"])
    def admin_photos_update(person_id):
        db = get_db(db_path)
        person = db.execute("SELECT * FROM person WHERE id=?", (person_id,)).fetchone()
        if not person:
            abort(404)
        current_managed = person["photo_url"] if _is_managed_photo(person["photo_url"]) else None
        current_filename = (
            current_managed[len(_MANAGED_PHOTO_PREFIX):] if current_managed else None
        )
        if request.form.get("action") == "remove":
            _delete_managed_photo(app, person["photo_url"])
            photo_url = None
            flash(f"Removed photo for {person['display_name']}.", "success")
        else:
            uploaded = _resolve_photo_input(app, current_filename=current_filename)
            if uploaded is None:
                return redirect(url_for("admin_photos"))
            photo_url = uploaded
            flash(f"Updated photo for {person['display_name']}.", "success")
        db.execute(
            "UPDATE person SET photo_url=?, updated_at=datetime('now') WHERE id=?",
            (photo_url, person_id),
        )
        db.commit()
        return redirect(url_for("admin_photos"))

    # --- Weekly import: ONE step ---
    # Drop both weekly files in a single form; one preview shows the
    # whole week; one Apply lands it (workbook first, then Tech Report
    # — the order that used to be a documented footgun is now just
    # code). Either file alone still works, but the wall is only fully
    # right once both have been applied.
    @app.route("/admin/import")
    def admin_import():
        return render_template("admin/import.html", plan=None, tplan=None)

    @app.route("/admin/import", methods=["POST"])
    def admin_import_preview():
        xf = request.files.get("input_list")
        pf = request.files.get("tech_report")
        have_x = xf is not None and xf.filename
        have_p = pf is not None and pf.filename
        if not (have_x or have_p):
            flash("Choose the week's files first (either or both).", "error")
            return redirect(url_for("admin_import"))
        db = get_db(db_path)
        plan = tplan = None
        if have_x:
            try:
                plan = importer.build_plan(db, importer.parse_workbook(xf.read()))
            except Exception as exc:  # bad zip, wrong sheet names, etc.
                flash(f"Could not read the Input List workbook: {exc}", "error")
                return redirect(url_for("admin_import"))
        if have_p:
            try:
                tplan = importer.build_tech_plan(db, importer.parse_tech_report(pf.read()))
            except Exception as exc:
                flash(f"Could not read the Tech Report PDF: {exc}", "error")
                return redirect(url_for("admin_import"))
        return render_template("admin/import.html", plan=plan, tplan=tplan)

    @app.route("/admin/import/apply", methods=["POST"])
    def admin_import_apply():
        import json as _json
        try:
            plan = _json.loads(request.form.get("plan_json") or "null")
            tplan = _json.loads(request.form.get("tplan_json") or "null")
        except ValueError:
            flash("Import plan was malformed — re-upload and preview again.", "error")
            return redirect(url_for("admin_import"))
        if isinstance(plan, list):  # pre-backline plan format
            plan = {"assignments": plan}
        db = get_db(db_path)
        done = []
        if plan:
            done.append(f"{importer.apply_plan(db, plan)} slots from the Input List")
        if tplan:
            done.append(f"{importer.apply_tech_plan(db, tplan)} seats from the Tech Report")
        if not done:
            flash("Nothing to apply — upload and preview first.", "error")
            return redirect(url_for("admin_import"))
        flash("Applied " + " and ".join(done) + ".", "success")
        return redirect(url_for("admin_slots"))

    @app.route("/admin/export/stageplot.svg")
    def admin_stageplot():
        """Dave's stage plot, auto-recreated from the week's imports.
        Rendered fresh on every request — grab it, print it, or don't."""
        db = get_db(db_path)
        settings = {r["key"]: r["value"] for r in
                    db.execute("SELECT key, value FROM app_setting")}
        svg = stageplot.build_stage_plot(
            db,
            service_label=settings.get("import_source"),
            generated=settings.get("import_at"),
        )
        resp = Response(svg, mimetype="image/svg+xml")
        if request.args.get("download"):
            resp.headers["Content-Disposition"] = "attachment; filename=stage-plot.svg"
        return resp

    # --- Inventory export (backup) ---
    @app.route("/admin/export.json")
    def admin_export():
        """Complete dump of everything operators have entered. This is
        the backup format — snapshot it into the git repo so inventory
        can never be lost. Excludes nothing; photos are files on disk
        and are backed up separately with the data directory."""
        db = get_db(db_path)
        def rows(table):
            return [dict(r) for r in db.execute(f"SELECT * FROM {table}")]
        return jsonify({
            "exported_at": db.execute("SELECT datetime('now') AS t").fetchone()["t"],
            "schema_migrations": rows("schema_migrations"),
            "person": rows("person"),
            "channel": rows("channel"),
            "position": rows("position"),
            "slot": rows("slot"),
            "wireless_model": rows("wireless_model"),
            "capsule_model": rows("capsule_model"),
            "asset": rows("asset"),
        })

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

    # --- Dashboards (build your own) ---
    @app.route("/admin/dashboards")
    def admin_dashboards():
        import json as _json
        db = get_db(db_path)
        dashboards = []
        for r in db.execute("SELECT * FROM dashboard WHERE archived=0 ORDER BY name"):
            cfg = _parse_dash_config(r["config"])
            dashboards.append({**dict(r), "widget_count": len(cfg["widgets"])})
        return render_template("admin/dashboards.html", dashboards=dashboards)

    @app.route("/admin/dashboards", methods=["POST"])
    def admin_dashboards_create():
        db = get_db(db_path)
        name = (request.form.get("name") or "").strip()
        if not name:
            flash("Give the dashboard a name.", "error")
            return redirect(url_for("admin_dashboards"))
        slug = _dash_slug(db, name)
        cur = db.execute("INSERT INTO dashboard (slug, name) VALUES (?, ?)",
                         (slug, name))
        db.commit()
        return redirect(url_for("admin_dashboards_edit", dashboard_id=cur.lastrowid))

    @app.route("/admin/dashboards/<int:dashboard_id>/edit")
    def admin_dashboards_edit(dashboard_id):
        db = get_db(db_path)
        dash = db.execute("SELECT * FROM dashboard WHERE id=?",
                          (dashboard_id,)).fetchone()
        if not dash:
            abort(404)
        return render_template("admin/dashboard_edit.html", dash=dash,
                               widget_types=DASH_WIDGETS,
                               default_sizes=DASH_DEFAULT_SIZES,
                               cols=DASH_COLS, rows=DASH_ROWS,
                               config=_parse_dash_config(dash["config"]))

    @app.route("/admin/dashboards/<int:dashboard_id>/preview", methods=["POST"])
    def admin_dashboards_preview(dashboard_id):
        """Render the REAL display page for an unsaved config — the
        builder pipes this into its canvas iframe, so what you lay out
        is literally what the TV will serve."""
        db = get_db(db_path)
        dash = db.execute("SELECT * FROM dashboard WHERE id=?",
                          (dashboard_id,)).fetchone()
        if not dash:
            abort(404)
        config = _parse_dash_config(request.form.get("config_json") or "")
        ctx = _dashboard_context(db, config)
        return render_template("dashboard.html", dash=dash, preview=True,
                               widgets=config["widgets"], **ctx)

    @app.route("/admin/dashboards/<int:dashboard_id>", methods=["POST"])
    def admin_dashboards_update(dashboard_id):
        import json as _json
        db = get_db(db_path)
        dash = db.execute("SELECT * FROM dashboard WHERE id=?",
                          (dashboard_id,)).fetchone()
        if not dash:
            abort(404)
        if request.form.get("action") == "archive":
            db.execute("UPDATE dashboard SET archived=1, updated_at=datetime('now') "
                       "WHERE id=?", (dashboard_id,))
            db.commit()
            flash(f"Archived {dash['name']}.", "success")
            return redirect(url_for("admin_dashboards"))
        name = (request.form.get("name") or "").strip() or dash["name"]
        config = _parse_dash_config(request.form.get("config_json") or "")
        db.execute("UPDATE dashboard SET name=?, config=?, updated_at=datetime('now') "
                   "WHERE id=?",
                   (name, _json.dumps(config), dashboard_id))
        db.commit()
        flash(f"Saved {name} — {len(config['widgets'])} widgets.", "success")
        return redirect(url_for("admin_dashboards_edit", dashboard_id=dashboard_id))

    # --- Display settings ---
    @app.route("/admin/displays", methods=["POST"])
    def admin_displays_update():
        """Micboard column width in px. The TV above the chargers picks
        the change up within 2s (it rides /api/state) — stand at the
        rack, nudge the number on your phone, watch the columns move."""
        db = get_db(db_path)
        raw = (request.form.get("micboard_col_width") or "").strip()
        if raw and not (raw.isdigit() and 40 <= int(raw) <= 1000):
            flash("Column width must be 40–1000 px (or blank for automatic).", "error")
            return redirect(url_for("admin_index"))
        if raw:
            db.execute("""INSERT INTO app_setting (key, value)
                          VALUES ('micboard_col_width', ?)
                          ON CONFLICT(key) DO UPDATE SET value=excluded.value""", (raw,))
        else:
            db.execute("DELETE FROM app_setting WHERE key='micboard_col_width'")
        db.commit()
        flash("Micboard columns set to " + (f"{raw} px." if raw else "automatic."), "success")
        return redirect(url_for("admin_index"))

    # --- Slots ---
    @app.route("/admin/slots/clear", methods=["POST"])
    def admin_slots_clear():
        """Manual version of the Sunday-1-PM automatic clear."""
        _weekly_clear(get_db(db_path))
        flash("Week cleared — every seat is empty, inventory untouched.", "success")
        return redirect(url_for("admin_slots"))

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
        leader = _current_leader(db)
        return render_template(
            "admin/slots.html",
            slots=slots,
            people=people,
            handhelds=handhelds,
            beltpacks=beltpacks,
            iems=iems,
            positions=positions,
            leader_person_id=leader["person_id"] if leader else None,
        )

    @app.route("/admin/leader", methods=["POST"])
    def admin_leader_update():
        db = get_db(db_path)
        raw = (request.form.get("leader_person_id") or "").strip()
        value = raw if raw.isdigit() else None
        db.execute(
            """INSERT INTO app_setting (key, value) VALUES ('leader_person_id', ?)
               ON CONFLICT(key) DO UPDATE SET value=excluded.value""",
            (value,),
        )
        db.commit()
        flash("Music leader updated." if value else "Music leader cleared.", "success")
        return redirect(url_for("admin_slots"))

    @app.route("/admin/slots/<int:slot_id>", methods=["POST"])
    def admin_slots_update(slot_id):
        db = get_db(db_path)
        slot = db.execute("SELECT id, kind, label, pc_role FROM slot WHERE id=?", (slot_id,)).fetchone()
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
        # Instrument label — only the band forms post it; other slots
        # keep whatever they had. Same guard for the PC role.
        if "label" in request.form:
            label = (request.form.get("label") or "").strip() or None
        else:
            label = slot["label"]
        if "pc_role" in request.form:
            pc_role = (request.form.get("pc_role") or "").strip() or None
        else:
            pc_role = slot["pc_role"]

        # mic_only slots can't have an IEM regardless of what was posted
        if slot["kind"] == "mic_only":
            iem_id = None

        db.execute(
            """UPDATE slot SET
                 person_id=?, mic_channel_id=?, iem_channel_id=?, position_id=?,
                 mymix_channel=?, label=?, pc_role=?,
                 updated_at=datetime('now')
               WHERE id=?""",
            (person_id, mic_id, iem_id, position_id, mymix_channel, label, pc_role, slot_id),
        )
        db.commit()
        flash(f"Slot {slot_id} updated.", "success")
        return redirect(url_for("admin_slots"))

    # --- Assets ---
    def _next_asset_tag(db) -> str:
        """ICT-0001, ICT-0002, ... — highest existing number + 1,
        archived rows included so a tag is never reissued."""
        n = 0
        for r in db.execute("SELECT tag FROM asset WHERE tag LIKE 'ICT-%'"):
            digits = r["tag"][4:]
            if digits.isdigit():
                n = max(n, int(digits))
        return f"ICT-{n + 1:04d}"

    def _asset_form_values(form) -> dict:
        def txt(name):
            return (form.get(name) or "").strip() or None
        price = txt("purchase_price")
        try:
            price = float(price) if price else None
        except ValueError:
            price = None
        status = form.get("status") or "in_service"
        if status not in ASSET_STATUSES:
            status = "in_service"
        return {
            "name": txt("name"),
            "category": (txt("category") or "other").lower(),
            "brand": txt("brand"),
            "model": txt("model"),
            "serial_number": txt("serial_number"),
            "status": status,
            "location": txt("location"),
            "channel_id": int(form["channel_id"]) if (form.get("channel_id") or "").isdigit() else None,
            "purchase_date": txt("purchase_date"),
            "purchase_price": price,
            "notes": txt("notes"),
        }

    @app.route("/admin/assets")
    def admin_assets():
        db = get_db(db_path)
        q = (request.args.get("q") or "").strip()
        status = request.args.get("status") or ""
        category = request.args.get("category") or ""
        sql = """SELECT a.*, c.label AS channel_label FROM asset a
                 LEFT JOIN channel c ON c.id = a.channel_id
                 WHERE a.archived=0"""
        params: list = []
        if q:
            sql += """ AND (a.tag LIKE ? OR a.name LIKE ? OR a.model LIKE ?
                       OR a.serial_number LIKE ? OR a.location LIKE ?)"""
            params += [f"%{q}%"] * 5
        if status in ASSET_STATUSES:
            sql += " AND a.status=?"
            params.append(status)
        if category:
            sql += " AND a.category=?"
            params.append(category)
        assets = db.execute(sql + " ORDER BY a.tag", params).fetchall()
        categories = [r["category"] for r in db.execute(
            "SELECT DISTINCT category FROM asset WHERE archived=0 ORDER BY category")]
        channels = db.execute(
            "SELECT id, label FROM channel WHERE archived=0 ORDER BY label").fetchall()
        unseeded = db.execute(
            """SELECT COUNT(*) c FROM channel WHERE archived=0
               AND id NOT IN (SELECT channel_id FROM asset WHERE channel_id IS NOT NULL)"""
        ).fetchone()["c"]
        return render_template(
            "admin/assets.html", assets=assets, q=q, status=status,
            category=category, categories=categories, channels=channels,
            statuses=ASSET_STATUSES, category_suggestions=ASSET_CATEGORIES,
            unseeded=unseeded, next_tag=_next_asset_tag(db))

    @app.route("/admin/assets", methods=["POST"])
    def admin_assets_create():
        db = get_db(db_path)
        v = _asset_form_values(request.form)
        if not v["name"]:
            flash("Name is required.", "error")
            return redirect(url_for("admin_assets"))
        tag = (request.form.get("tag") or "").strip().upper() or _next_asset_tag(db)
        if db.execute("SELECT 1 FROM asset WHERE tag=?", (tag,)).fetchone():
            flash(f"Tag {tag} is already in use.", "error")
            return redirect(url_for("admin_assets"))
        db.execute(
            """INSERT INTO asset (tag, name, category, brand, model, serial_number,
                 status, location, channel_id, purchase_date, purchase_price, notes)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (tag, v["name"], v["category"], v["brand"], v["model"],
             v["serial_number"], v["status"], v["location"], v["channel_id"],
             v["purchase_date"], v["purchase_price"], v["notes"]))
        db.commit()
        flash(f"Added {tag} — {v['name']}.", "success")
        return redirect(url_for("admin_assets"))

    @app.route("/admin/assets/seed", methods=["POST"])
    def admin_assets_seed():
        """One asset per wireless channel that doesn't have one yet —
        the transmitter/IEM pack IS the per-channel physical unit.
        (Receivers are shared across channels; add those by hand.)"""
        db = get_db(db_path)
        rows = db.execute(
            """SELECT c.id, c.label, c.kind, w.model AS wmodel
               FROM channel c LEFT JOIN wireless_model w ON w.id = c.wireless_model_id
               WHERE c.archived=0
               AND c.id NOT IN (SELECT channel_id FROM asset WHERE channel_id IS NOT NULL)
               ORDER BY c.label""").fetchall()
        for c in rows:
            db.execute(
                """INSERT INTO asset (tag, name, category, brand, model,
                     status, location, channel_id)
                   VALUES (?, ?, ?, 'Shure', ?, 'in_service', 'Mic rack', ?)""",
                (_next_asset_tag(db), c["label"],
                 "iem" if c["kind"] == "iem" else "wireless", c["wmodel"], c["id"]))
        db.commit()
        flash(f"Created {len(rows)} assets from the wireless inventory.", "success")
        return redirect(url_for("admin_assets"))

    @app.route("/admin/assets/<int:asset_id>/edit")
    def admin_assets_edit(asset_id):
        db = get_db(db_path)
        asset = db.execute("SELECT * FROM asset WHERE id=?", (asset_id,)).fetchone()
        if not asset:
            abort(404)
        channels = db.execute(
            "SELECT id, label FROM channel WHERE archived=0 ORDER BY label").fetchall()
        return render_template("admin/asset_edit.html", asset=asset,
                               channels=channels, statuses=ASSET_STATUSES,
                               category_suggestions=ASSET_CATEGORIES)

    @app.route("/admin/assets/<int:asset_id>", methods=["POST"])
    def admin_assets_update(asset_id):
        db = get_db(db_path)
        asset = db.execute("SELECT * FROM asset WHERE id=?", (asset_id,)).fetchone()
        if not asset:
            abort(404)
        if request.form.get("action") == "archive":
            db.execute("UPDATE asset SET archived=1, updated_at=datetime('now') WHERE id=?",
                       (asset_id,))
            db.commit()
            flash(f"Archived {asset['tag']}.", "success")
            return redirect(url_for("admin_assets"))
        v = _asset_form_values(request.form)
        if not v["name"]:
            flash("Name is required.", "error")
            return redirect(url_for("admin_assets_edit", asset_id=asset_id))
        db.execute(
            """UPDATE asset SET name=?, category=?, brand=?, model=?,
                 serial_number=?, status=?, location=?, channel_id=?,
                 purchase_date=?, purchase_price=?, notes=?,
                 updated_at=datetime('now')
               WHERE id=?""",
            (v["name"], v["category"], v["brand"], v["model"], v["serial_number"],
             v["status"], v["location"], v["channel_id"], v["purchase_date"],
             v["purchase_price"], v["notes"], asset_id))
        db.commit()
        flash(f"{asset['tag']} updated.", "success")
        return redirect(url_for("admin_assets"))

    @app.route("/admin/assets/labels")
    def admin_asset_labels():
        """Printable QR label sheet. ?ids=1,2,3 for a selection (default
        all active), ?size=large for big case/rack labels; the default
        grid matches Avery 5160 address-label stock (30 per sheet)."""
        db = get_db(db_path)
        ids = request.args.get("ids") or ""
        sql = "SELECT * FROM asset WHERE archived=0"
        params: list = []
        id_list = [int(i) for i in ids.split(",") if i.strip().isdigit()]
        if id_list:
            sql += f" AND id IN ({','.join('?' * len(id_list))})"
            params += id_list
        assets = db.execute(sql + " ORDER BY tag", params).fetchall()
        return render_template("admin/asset_labels.html", assets=assets,
                               size=request.args.get("size", "small"))


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
_UPDATE_CACHE = {"at": 0.0, "status": None}


def _update_status() -> dict | None:
    """Compare the running build against GitHub master, cached for an
    hour, fail-silent (returns None offline / rate-limited / unknown).
    The image bakes its commit in via the GIT_SHA build arg."""
    import json
    import time
    import urllib.request

    now = time.time()
    if now - _UPDATE_CACHE["at"] < 3600:
        return _UPDATE_CACHE["status"]
    _UPDATE_CACHE["at"] = now
    local = os.environ.get("ICTECH_VERSION", "unknown")
    status = None
    try:
        req = urllib.request.Request(
            "https://api.github.com/repos/dustind04/ictech-prodapp/commits/master",
            headers={"Accept": "application/vnd.github+json",
                     "User-Agent": "ictech-prodapp"})
        with urllib.request.urlopen(req, timeout=4) as resp:
            remote = json.load(resp)["sha"][:7]
        status = {
            "local": local,
            "remote": remote,
            "update_available": local != "unknown" and not remote.startswith(local[:7]),
            "local_unknown": local == "unknown",
        }
    except Exception:  # offline, rate-limited, DNS — never break admin
        status = None
    _UPDATE_CACHE["status"] = status
    return status


def _schedule_status(now=None) -> dict:
    """Python port of the wall's week clock: what's next (or live) and
    when. Sundays 9:00/11:00 (70 min on paper, +5 grace), Tuesday
    rehearsal 6:30–9:00 PM. Returns label/mode plus epoch millis so the
    page can tick client-side between refreshes."""
    now = now or datetime.now(CHURCH_TZ)

    def at(d, h, m):
        return d.replace(hour=h, minute=m, second=0, microsecond=0)

    def next_dow(dow, h, m):
        d = at(now, h, m) + timedelta(days=(dow - now.weekday()) % 7)
        if d <= now:
            d += timedelta(days=7)
        return d

    def wait(label, target):
        return {"mode": "wait", "label": label,
                "target_ms": int(target.timestamp() * 1000)}

    def live(label, start, over):
        return {"mode": "over" if over else "live", "label": label,
                "start_ms": int(start.timestamp() * 1000)}

    day = now.weekday()  # Monday=0 ... Sunday=6
    if day == 6:
        for svc_h in (9, 11):
            start = at(now, svc_h, 0)
            if now < start:
                return wait(f"{'1st' if svc_h == 9 else '2nd'} service", start)
            if now < start + timedelta(minutes=70):
                return live("Service time", start, False)
            if now < start + timedelta(minutes=75):
                return live("Service time", start, True)
        return wait("Rehearsal", next_dow(1, 18, 30))
    if day == 1:
        if now < at(now, 18, 30):
            return wait("Rehearsal", at(now, 18, 30))
        if now < at(now, 21, 0):
            return live("Rehearsal", at(now, 18, 30), False)
        return wait("1st service", next_dow(6, 9, 0))
    if day == 0:
        return wait("Rehearsal", next_dow(1, 18, 30))
    return wait("1st service", next_dow(6, 9, 0))


def _service_sunday(now=None) -> datetime:
    """The Sunday this week's data is for (rolls over after 12:30 PM)."""
    now = now or datetime.now(CHURCH_TZ)
    add = (6 - now.weekday()) % 7
    if now.weekday() == 6 and now >= now.replace(hour=12, minute=30,
                                                 second=0, microsecond=0):
        add = 7
    return now + timedelta(days=add)


def _parse_dash_config(raw: str) -> dict:
    """Sanitize a builder-submitted config: known widget types only,
    geometry clamped inside the 24x12 canvas, opts kept plain. Legacy
    v1 configs (flow "width" entries) get packed onto the canvas so
    nothing built earlier breaks."""
    import json as _json
    try:
        cfg = _json.loads(raw or "{}")
    except ValueError:
        cfg = {}
    screen = cfg.get("screen") if isinstance(cfg.get("screen"), dict) else {}
    try:
        sw, sh = int(screen.get("w", 1920)), int(screen.get("h", 1080))
    except (TypeError, ValueError):
        sw, sh = 1920, 1080
    sw, sh = min(max(sw, 480), 7680), min(max(sh, 320), 4320)

    V1_SPANS = {"full": 24, "twothirds": 16, "half": 12, "third": 8}
    widgets = []
    cx = cy = row_h = 0  # packing cursor for v1 conversion
    for w in (cfg.get("widgets") or []):
        if not isinstance(w, dict) or w.get("type") not in DASH_WIDGETS:
            continue
        opts = w.get("opts") if isinstance(w.get("opts"), dict) else {}
        if all(k in w for k in ("x", "y", "w", "h")):
            try:
                x, y, ww, hh = int(w["x"]), int(w["y"]), int(w["w"]), int(w["h"])
            except (TypeError, ValueError):
                continue
        else:  # v1 flow entry
            span = V1_SPANS.get(w.get("width"), 24)
            hh = DASH_DEFAULT_SIZES.get(w["type"], (24, 3))[1]
            if cx + span > DASH_COLS:
                cx, cy, row_h = 0, cy + row_h, 0
            x, y, ww = cx, cy, span
            cx, row_h = cx + span, max(row_h, hh)
        x = max(0, min(x, DASH_COLS - 1))
        y = max(0, min(y, DASH_ROWS - 1))
        ww = max(1, min(ww, DASH_COLS - x))
        hh = max(1, min(hh, DASH_ROWS - y))
        widgets.append({
            "type": w["type"], "x": x, "y": y, "w": ww, "h": hh,
            "opts": {k: v for k, v in opts.items()
                     if k in ("title", "text", "occupied_only") and
                     isinstance(v, (str, bool))},
        })
    return {"screen": {"w": sw, "h": sh}, "widgets": widgets}


def _dash_slug(db, name: str) -> str:
    import re as _re
    base = _re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "dashboard"
    slug, n = base, 2
    while db.execute("SELECT 1 FROM dashboard WHERE slug=?", (slug,)).fetchone():
        slug, n = f"{base}-{n}", n + 1
    return slug


def _dashboard_context(db, config: dict) -> dict:
    """Everything the used widgets need, queried once per render."""
    types = {w["type"] for w in config.get("widgets", [])}
    ctx: dict = {"cols": DASH_COLS, "rows": DASH_ROWS,
                 "screen": config.get("screen", {"w": 1920, "h": 1080})}
    if types & {"vocals", "band", "speakers", "techcrew"}:
        slots = [dict(r) for r in db.execute(_SLOT_QUERY)]
        ctx["zone_slots"] = {
            "vocals":   [s for s in slots if 1 <= s["bank_order"] <= 6],
            "speakers": [s for s in slots if 7 <= s["bank_order"] <= 10],
            "band":     [s for s in slots if 11 <= s["bank_order"] <= 16],
            "techcrew": [s for s in slots if s["kind"] == "tech"],
        }
    if "patch" in types:
        ctx["patch"] = db.execute(
            "SELECT * FROM patch_row ORDER BY sort_order").fetchall()
    if "iemrf" in types:
        ctx["iem_rf"] = db.execute(
            "SELECT * FROM iem_rf ORDER BY sort_order").fetchall()
    if "mymixlegend" in types:
        ctx["legend"] = db.execute(
            "SELECT * FROM mymix_channel ORDER BY ch").fetchall()
    if "mixers" in types:
        ctx["mixers"] = db.execute(
            "SELECT * FROM mymix_mixer ORDER BY sort_order").fetchall()
    if "thisweek" in types:
        ctx["leader"] = _current_leader(db)
        ctx["schedule"] = _schedule_status()
        ctx["service_date"] = _service_sunday().strftime("%A, %B %-d")
    return ctx


def _weekly_clear(db) -> None:
    """Empty the week: people off every seat, roles, leader, backline
    tables. Inventory (channels, positions, assets, photos) is
    untouched — this is the Sunday-afternoon blank slate."""
    db.execute("""UPDATE slot SET person_id=NULL, mic_channel_id=NULL,
                    iem_channel_id=NULL, position_id=NULL, mymix_channel=NULL,
                    pc_role=NULL, updated_at=datetime('now')
                  WHERE kind IN ('paired', 'mic_only') AND archived=0""")
    db.execute("""UPDATE slot SET person_id=NULL, pc_role=NULL,
                    iem_channel_id=NULL, mymix_channel=NULL,
                    updated_at=datetime('now')
                  WHERE kind='band' AND archived=0""")
    db.execute("""UPDATE slot SET person_id=NULL, pc_role=NULL,
                    updated_at=datetime('now')
                  WHERE kind='tech' AND archived=0""")
    for table in ("patch_row", "iem_rf", "mymix_channel", "mymix_mixer"):
        db.execute(f"DELETE FROM {table}")
    db.execute("DELETE FROM app_setting WHERE key='leader_person_id'")
    db.execute("""INSERT INTO app_setting (key, value)
                  VALUES ('week_cleared_at', datetime('now'))
                  ON CONFLICT(key) DO UPDATE SET value=excluded.value""")
    db.commit()


def _last_clear_boundary(now=None) -> datetime:
    """The most recent Sunday 1 PM church time at or before `now`."""
    now = now or datetime.now(CHURCH_TZ)
    b = now.replace(hour=WEEKLY_CLEAR_HOUR, minute=0, second=0, microsecond=0)
    b -= timedelta(days=(now.weekday() - WEEKLY_CLEAR_WEEKDAY) % 7)
    if b > now:
        b -= timedelta(days=7)
    return b


def _maybe_weekly_clear(db) -> None:
    """Piggybacks on the wall's poll loop — no scheduler process to
    babysit, and a Pi that was off at 1 PM clears on next boot. Runs
    the clear once per Sunday-1-PM boundary; files imported AFTER the
    boundary are the new week and are left alone."""
    boundary = (_last_clear_boundary().astimezone(timezone.utc)
                .strftime("%Y-%m-%d %H:%M:%S"))
    s = {r["key"]: r["value"] for r in db.execute(
        "SELECT key, value FROM app_setting WHERE key IN "
        "('week_cleared_at', 'import_at', 'tech_report_at')")}
    if (s.get("week_cleared_at") or "") >= boundary:
        return
    if max(s.get("import_at") or "", s.get("tech_report_at") or "") >= boundary:
        db.execute("""INSERT INTO app_setting (key, value)
                      VALUES ('week_cleared_at', datetime('now'))
                      ON CONFLICT(key) DO UPDATE SET value=excluded.value""")
        db.commit()
        return
    log.info("Weekly clear: emptying last week (boundary %s UTC)", boundary)
    _weekly_clear(db)


def _current_leader(db):
    """This week's music leader, or None. Stored in app_setting because
    the leader may have no mic-board slot (leading from an instrument)."""
    row = db.execute(
        "SELECT value FROM app_setting WHERE key='leader_person_id'"
    ).fetchone()
    if not row or not row["value"]:
        return None
    p = db.execute(
        "SELECT id, display_name, nickname FROM person WHERE id=? AND archived=0",
        (int(row["value"]),),
    ).fetchone()
    if p is None:
        return None
    return {"person_id": p["id"], "name": p["nickname"] or p["display_name"]}


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
        "shure_channel_name": _opt_str("shure_channel_name"),
        "shure_type": shure_type,
        "capsule": _opt_str("capsule"),
        "frequency_mhz": _opt_float("frequency_mhz"),
        "wireless_model_id": _opt_int("wireless_model_id"),
        "capsule_model_id": _opt_int("capsule_model_id"),
        "receiver_model_id": _opt_int("receiver_model_id"),
    }


# Receiver family -> network protocol family for the polling worker.
_FAMILY_PROTOCOL = {
    "ULX-D": "ulxd",
    "QLX-D": "qlxd",
    "Axient Digital": "axtd",
    "PSM 1000": "p10t",
    "UHF-R (legacy)": "uhfr",
}


def _derive_shure_type(db, receiver_model_id):
    """Protocol family from the chosen receiver, or None when the
    receiver family has no network control we speak."""
    if receiver_model_id is None:
        return None
    row = db.execute("SELECT family FROM wireless_model WHERE id=?",
                     (receiver_model_id,)).fetchone()
    return _FAMILY_PROTOCOL.get(row["family"]) if row else None


def _validate_gear_ids(db, values: dict) -> None:
    """Null out gear FK values that don't exist — a stale form beats a 500."""
    for col, table in (
        ("wireless_model_id", "wireless_model"),
        ("capsule_model_id", "capsule_model"),
        ("receiver_model_id", "wireless_model"),
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


def _free_port(preferred: int = 8058, tries: int = 20) -> int:
    """The preferred port, or the next free one after it. Containers
    never collide internally — this guards bare `python app.py` runs."""
    import socket
    for port in range(preferred, preferred + tries):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("0.0.0.0", port))
            except OSError:
                continue
        if port != preferred:
            log.warning("Port %d busy — using %d instead", preferred, port)
        return port
    raise RuntimeError(f"No free port in {preferred}..{preferred + tries}")


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=_free_port(), debug=True)
