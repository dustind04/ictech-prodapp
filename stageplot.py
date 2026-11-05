"""
Auto-generated stage plot.

Rebuilds Dave's weekly stage plot from what the imports already know:
who stands at which pool, who plays what upstage, mic colors, IEM pack
numbers, MyMix units, and how each instrument reaches the board. Output
is a print-friendly white-sheet SVG served from the Import/Export tab —
always current with the database, never stored.

Layout (top-down, audience at the bottom):
    UPSTAGE      : band (instrument-only people)
    FRONT ROW    : pool positions, numeric order left to right
    CS POOL      : hosts, closest to the audience
    below stage  : tech booth line
"""

from __future__ import annotations

import base64
from pathlib import Path
from xml.sax.saxutils import escape

# Overhead photo of the actual stage (from Dave's immanuel-stage.pdf),
# pre-rotated so the audience is at the bottom: pool numbers 1..6 run
# left to right along the lip, drum kit upper stage left. Embedded as a
# data URI so a downloaded SVG stays self-contained.
_BG_FILE = Path(__file__).parent / "static" / "stage-bg.jpg"
_BG_RATIO = 534 / 952   # height / width of the photo


DEFAULT_BG_URL = "/static/stage-bg.jpg"
_MIME = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png",
         "webp": "image/webp", "gif": "image/gif"}


def _bg_datauri(path: Path = _BG_FILE):
    try:
        mime = _MIME.get(path.suffix.lstrip(".").lower(), "image/jpeg")
        return f"data:{mime};base64," + base64.b64encode(path.read_bytes()).decode()
    except OSError:
        return None


def stage_layout(db, photo_dir) -> dict | None:
    """The admin-assigned stage (Admin → Stage), or None for the
    built-in layout. Spots are percent of the image; the image is the
    uploaded one, or the built-in photo when only spots were set."""
    spots = {r["label"].lower(): (r["x"], r["y"])
             for r in db.execute("SELECT label, x, y FROM stage_spot")}
    if not spots:
        return None
    s = {r["key"]: r["value"] for r in db.execute(
        "SELECT key, value FROM app_setting WHERE key IN ('stage_image', 'stage_ratio')")}
    url, path, ratio = DEFAULT_BG_URL, _BG_FILE, _BG_RATIO
    if s.get("stage_image", "").startswith("/photos/"):
        url = s["stage_image"]
        path = Path(photo_dir) / url[len("/photos/"):]
        try:
            ratio = float(s.get("stage_ratio") or ratio)
        except ValueError:
            pass
    return {"url": url, "path": path, "ratio": ratio, "spots": spots}


def spot_for(pool, instruments, role, spots: dict):
    """Where one person stands: their pool's spot, else their
    instrument seat's, else Speaker / CS Pool for speakers and hosts."""
    if pool and pool.lower() in spots:
        return spots[pool.lower()]
    for inst in instruments or []:
        if inst.lower() in spots:
            return spots[inst.lower()]
    r = (role or "").lower()
    if any(w in r for w in ("speaker", "host", "preach")) or "cs" in (pool or "").lower():
        return spots.get("speaker") or spots.get("cs pool")
    return None

MIC_HEX = {
    "red": "#D64545", "wht": "#B9B9B4", "white": "#B9B9B4",
    "blu": "#4A90D9", "blue": "#4A90D9", "blk": "#1F1F1F", "black": "#1F1F1F",
    "orng": "#E05A0E", "orange": "#E05A0E", "ylo": "#D4B71E", "yellow": "#D4B71E",
    "grn": "#7AB648", "green": "#7AB648",
}
GENERIC_INPUTS = {"xlr", "di", "mono di"}


def _mic_hex(label):
    for word in (label or "").lower().replace("/", " ").split():
        if word in MIC_HEX:
            return MIC_HEX[word]
    return None


def _gather(db):
    """One plot item per person on stage, all roles folded together."""
    rows = db.execute("""
        SELECT s.bank_order, s.kind, s.label AS slot_label, s.pc_role,
               s.mymix_channel, p.id AS pid, p.display_name AS name,
               pos.label AS pool, mc.label AS mic, ic.label AS iem
          FROM slot s
          JOIN person p ON p.id = s.person_id
          LEFT JOIN position pos ON pos.id = s.position_id
          LEFT JOIN channel mc ON mc.id = s.mic_channel_id
          LEFT JOIN channel ic ON ic.id = s.iem_channel_id
         WHERE s.archived = 0 AND s.kind != 'tech'
         ORDER BY s.bank_order""").fetchall()

    patch_by_mymix = {}
    for pr in db.execute("SELECT mymix_ch, mic, info, snake_ch FROM patch_row"):
        if pr["mymix_ch"]:
            patch_by_mymix.setdefault(pr["mymix_ch"], []).append(pr)

    def input_label(mymix):
        rows_ = [r for r in patch_by_mymix.get(mymix, []) if r["mic"] or r["info"]]
        if not rows_:
            return None
        if len(rows_) > 2:
            drummy = any((r["snake_ch"] or "").lower().startswith("drum") for r in rows_)
            return "Kit Mics" if drummy else f"{len(rows_)} inputs"
        first = rows_[0]
        mic = (first["mic"] or "").strip()
        if mic.lower() in GENERIC_INPUTS and first["info"]:
            return first["info"]
        return mic or first["info"]

    mixer_by_owner = {}
    for m in db.execute("SELECT mixer, owner FROM mymix_mixer"):
        if m["owner"]:
            mixer_by_owner[m["owner"].strip().lower()] = m["mixer"]

    people = {}
    for r in rows:
        it = people.setdefault(r["pid"], {
            "name": r["name"], "role": None, "pool": None, "mics": [],
            "iems": [], "channels": [], "instruments": [], "inputs": [],
            "order": r["bank_order"],
        })
        it["role"] = it["role"] or r["pc_role"]
        it["pool"] = it["pool"] or r["pool"]
        if r["mic"] and r["mic"] not in it["mics"]:
            it["mics"].append(r["mic"])
        if r["iem"] and r["iem"] not in it["iems"]:
            it["iems"].append(r["iem"])
        if r["mymix_channel"] and r["mymix_channel"] not in it["channels"]:
            it["channels"].append(r["mymix_channel"])
        if r["kind"] == "band":
            if r["slot_label"] and r["slot_label"] not in it["instruments"]:
                it["instruments"].append(r["slot_label"])
            lab = input_label(r["mymix_channel"])
            if lab and lab not in it["inputs"]:
                it["inputs"].append(lab)
        first = r["name"].split()[0].lower()
        it["mymix_unit"] = mixer_by_owner.get(first)

    techs = db.execute("""
        SELECT s.label AS role, p.display_name AS name
          FROM slot s JOIN person p ON p.id = s.person_id
         WHERE s.archived = 0 AND s.kind = 'tech'
         ORDER BY s.bank_order""").fetchall()
    return list(people.values()), techs


def _card(x, y, w, h, it):
    lines = []
    detail = []
    if it["mics"]:
        detail.append("Mic: " + ", ".join(it["mics"]))
    if it["inputs"]:
        detail.append("In: " + ", ".join(it["inputs"]))
    if it["iems"]:
        detail.append("IEM: " + ", ".join(it["iems"]))
    if it.get("mymix_unit"):
        detail.append("MyMix: " + it["mymix_unit"])
    elif it["channels"]:
        detail.append("Ch: " + " · ".join(it["channels"]))

    chip = _mic_hex(it["mics"][0] if it["mics"] else "")
    lines.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="10" '
                 f'fill="#FFFFFF" stroke="#1F1F1F" stroke-width="1.5"/>')
    if chip:
        lines.append(f'<rect x="{x}" y="{y}" width="{w}" height="8" rx="4" fill="{chip}"/>')
    ty = y + 30
    lines.append(f'<text x="{x + w / 2}" y="{ty}" text-anchor="middle" '
                 f'font-size="17" font-weight="800" fill="#1F1F1F">{escape(it["name"])}</text>')
    ty += 17
    role = it["role"] or " / ".join(it["instruments"]) or ""
    if role:
        lines.append(f'<text x="{x + w / 2}" y="{ty}" text-anchor="middle" '
                     f'font-size="11" font-weight="700" letter-spacing="1" '
                     f'fill="#5E9034">{escape(role.upper())}</text>')
    ty += 16
    for d in detail[:4]:
        lines.append(f'<text x="{x + w / 2}" y="{ty}" text-anchor="middle" '
                     f'font-size="11" fill="#4A4A4A">{escape(d)}</text>')
        ty += 14
    return "".join(lines)


def build_stage_plot(db, service_label=None, generated=None, layout=None):
    people, techs = _gather(db)
    if layout:
        return _build_on_layout(people, techs, layout, service_label, generated)

    def poolnum(p):
        digits = "".join(c for c in (p or "") if c.isdigit())
        return int(digits) if digits else 99

    # The Speaker is pinned downstage center regardless of pool data.
    def is_speaker(p):
        return "speaker" in (p["role"] or "").lower()

    speakers = [p for p in people if is_speaker(p)]
    rest = [p for p in people if not is_speaker(p)]
    front = sorted([p for p in rest if p["pool"] and "cs" not in p["pool"].lower()],
                   key=lambda p: poolnum(p["pool"]))
    cs = sorted([p for p in rest if p["pool"] and "cs" in p["pool"].lower()],
                key=lambda p: p["order"])
    upstage = sorted([p for p in rest if not p["pool"]], key=lambda p: p["order"])
    mid = len(cs) // 2
    cs = cs[:mid] + speakers + cs[mid:]

    W = 1500
    CW, CH = 218, 118
    SX, SW = 40, W - 80
    SY = 110
    bg = _bg_datauri()
    if bg:
        SH = round(SW * _BG_RATIO)          # photo fills the stage box
        band_y, front_y = SY + 60, SY + SH - 290
        cs_y = SY + SH + 24                  # speakers in front, on white
        labels_y = cs_y + CH + 40
    else:
        SH = 700
        band_y, front_y = SY + 60, SY + 320
        cs_y = SY + 510
        labels_y = SY + SH - 15
    H = labels_y + 130

    svg = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" '
           f'font-family="Helvetica, Arial, sans-serif">',
           f'<rect width="{W}" height="{H}" fill="#FFFFFF"/>',
           f'<text x="40" y="52" font-size="30" font-weight="900" fill="#1F1F1F">'
           f'STAGE PLOT<tspan fill="#7AB648">.</tspan></text>',
           f'<text x="40" y="78" font-size="15" fill="#6B6B6B">Immanuel Church'
           + (f' · Sunday: {escape(service_label)}' if service_label else '')
           + (f' · generated {escape(generated)}' if generated else '') + '</text>']
    if bg:
        svg.append(f'<image x="{SX}" y="{SY}" width="{SW}" height="{SH}" '
                   f'href="{bg}" preserveAspectRatio="xMidYMid slice"/>')
        svg.append(f'<rect x="{SX}" y="{SY}" width="{SW}" height="{SH}" rx="2" '
                   f'fill="none" stroke="#1F1F1F" stroke-width="2.5"/>')
        svg.append(f'<text x="{W / 2}" y="{SY + 28}" text-anchor="middle" font-size="13" '
                   f'letter-spacing="4" fill="#FFFFFF" opacity="0.85">UPSTAGE</text>')
    else:
        svg.append(f'<rect x="{SX}" y="{SY}" width="{SW}" height="{SH}" rx="14" '
                   f'fill="#F7F7F5" stroke="#1F1F1F" stroke-width="2.5"/>')
        svg.append(f'<text x="{W / 2}" y="{SY + 30}" text-anchor="middle" font-size="13" '
                   f'letter-spacing="4" fill="#9A9A94">UPSTAGE</text>')
    svg.append(f'<text x="{W / 2}" y="{labels_y}" text-anchor="middle" font-size="13" '
               f'letter-spacing="4" fill="#9A9A94">DOWNSTAGE · AUDIENCE</text>')

    def spread(items, y):
        if not items:
            return
        gap = (W - 120) / len(items)
        for i, it in enumerate(items):
            x = 60 + i * gap + (gap - CW) / 2
            svg.append(_card(x, y, CW, CH, it))

    spread(upstage, band_y)
    spread(front, front_y)
    spread(cs, cs_y)

    if techs:
        line = "   ·   ".join(f'{t["role"]}: {t["name"]}' for t in techs)
        svg.append(f'<text x="{W / 2}" y="{labels_y + 50}" text-anchor="middle" font-size="14" '
                   f'font-weight="700" fill="#1F1F1F">TECH — {escape(line)}</text>')
    svg.append(f'<text x="{W / 2}" y="{labels_y + 80}" text-anchor="middle" font-size="11" '
               f'fill="#9A9A94">Auto-generated from the weekly Input List + Tech Report imports '
               f'· icTech Services</text>')
    svg.append("</svg>")
    return "".join(svg)


def _build_on_layout(people, techs, layout, service_label, generated):
    """Stage plot on the admin-assigned photo: each person's card sits
    on their spot. Anyone whose pool / seat has no saved spot is left
    off — the plot shows where people stand, not who exists."""
    W, SX, SW, SY = 1500, 40, 1420, 110
    CW, CH = 190, 108
    SH = round(SW * layout["ratio"])
    placed, seen = [], {}
    for it in people:
        xy = spot_for(it["pool"], it["instruments"], it["role"], layout["spots"])
        if xy is None:
            continue
        key = (round(xy[0]), round(xy[1]))
        bump = seen.get(key, 0)
        seen[key] = bump + 1
        cx = SX + xy[0] / 100 * SW + bump * (CW * 0.55)
        cy = SY + xy[1] / 100 * SH + bump * 18
        x = min(max(cx - CW / 2, SX), SX + SW - CW)
        y = min(max(cy - CH / 2, SY), SY + SH - CH)
        placed.append((x, y, it))
    labels_y = SY + SH + 54
    H = labels_y + 130

    svg = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" '
           f'font-family="Helvetica, Arial, sans-serif">',
           f'<rect width="{W}" height="{H}" fill="#FFFFFF"/>',
           f'<text x="40" y="52" font-size="30" font-weight="900" fill="#1F1F1F">'
           f'STAGE PLOT<tspan fill="#7AB648">.</tspan></text>',
           f'<text x="40" y="78" font-size="15" fill="#6B6B6B">Immanuel Church'
           + (f' · Sunday: {escape(service_label)}' if service_label else '')
           + (f' · generated {escape(generated)}' if generated else '') + '</text>']
    bg = _bg_datauri(layout["path"])
    if bg:
        svg.append(f'<image x="{SX}" y="{SY}" width="{SW}" height="{SH}" '
                   f'href="{bg}" preserveAspectRatio="none"/>')
    svg.append(f'<rect x="{SX}" y="{SY}" width="{SW}" height="{SH}" rx="2" '
               f'fill="none" stroke="#1F1F1F" stroke-width="2.5"/>')
    for x, y, it in placed:
        svg.append(_card(x, y, CW, CH, it))
    if techs:
        line = "   ·   ".join(f'{t["role"]}: {t["name"]}' for t in techs)
        svg.append(f'<text x="{W / 2}" y="{labels_y + 50}" text-anchor="middle" font-size="14" '
                   f'font-weight="700" fill="#1F1F1F">TECH — {escape(line)}</text>')
    svg.append(f'<text x="{W / 2}" y="{labels_y + 80}" text-anchor="middle" font-size="11" '
               f'fill="#9A9A94">Auto-generated from the weekly imports · stage from Admin → Stage '
               f'· icTech Services</text>')
    svg.append("</svg>")
    return "".join(svg)
