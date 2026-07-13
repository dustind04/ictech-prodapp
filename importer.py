"""
Weekly Input List importer.

Dave produces "<date> Input List.xlsx" every week (sheets: 'Input List',
'MyMix', 'Mic Assign'). This module turns that workbook into a
slot-assignment plan:

  parse_workbook(bytes)  -> what the spreadsheet says
  build_plan(db, parsed) -> resolved against people/channels/positions,
                            with per-slot warnings for anything unmatched
  apply_plan(db, plan)   -> writes the assignments

The flow is deliberately two-step (preview, then apply) — the admin sees
exactly what will land on the wall before it does.

Matching philosophy: the spreadsheet is Dave's language ("Chris Vox",
"Red HH", "Pack 1", "Pool 2"). We match loosely — first names against
people, color tags against channel labels, pack numbers against IEM
labels — and warn rather than guess when a match isn't clean. A slot
row with no matching person is still applied (empty slot): the sheet is
the weekly truth, including who ISN'T on this week.
"""

from __future__ import annotations

import re
from io import BytesIO

from openpyxl import load_workbook


# Mic-color words as they appear in 'Mic Assign' -> tag spellings Dave
# uses in channel names ("Wht HH", "Orng RF").
COLOR_SYNONYMS = {
    "red": ("red",),
    "white": ("white", "wht"),
    "blue": ("blue", "blu"),
    "black": ("black", "blk"),
    "orange": ("orange", "orng"),
    "yellow": ("yellow", "ylo"),
    "green": ("green", "grn"),
}

PAIRED_SLOTS = (1, 2, 3, 4, 5, 6)
MIC_ONLY_SLOTS = (7, 8, 9, 10)


def _s(v) -> str:
    """Cell value as a clean string. Dave's sheets have literal 0s in
    blank-ish cells; treat those as empty."""
    if v is None or v == 0:
        return ""
    return str(v).strip()


def parse_workbook(data: bytes) -> dict:
    wb = load_workbook(BytesIO(data), data_only=True)
    warnings = []

    if "Input List" not in wb.sheetnames:
        raise ValueError("Workbook has no 'Input List' sheet — is this the right file?")
    ws = wb["Input List"]

    sunday = _s(ws["A2"].value).removeprefix("Sunday:").strip() or None

    # Rows keyed by the Mic column (D): "... HH" = vocalist handheld,
    # "... RF" = wireless misc (host mics, sermon headset).
    vocals, misc = [], []
    for row in ws.iter_rows(min_row=4):
        instrument = _s(row[2].value)   # C
        mic = _s(row[3].value)          # D
        mymix = _s(row[6].value)        # G
        info = _s(row[7].value) if len(row) > 7 else ""  # H
        foh = row[1].value              # B
        entry = {
            "foh": foh if isinstance(foh, (int, float)) else None,
            "instrument": instrument,
            "mic": mic,
            "mymix": mymix,
            "info": info,
        }
        if mic.upper().endswith("HH") and instrument:
            vocals.append(entry)
        elif "RF" in mic.upper() and instrument:
            misc.append(entry)
    vocals.sort(key=lambda e: (e["foh"] is None, e["foh"]))

    # 'Mic Assign' adds stage position + IEM pack per vocalist.
    assign = {}
    if "Mic Assign" in wb.sheetnames:
        for row in wb["Mic Assign"].iter_rows(min_row=3):
            name = _s(row[0].value)
            if not name:
                continue
            assign[_person_key(name)] = {
                "position": _s(row[1].value),
                "color": _s(row[2].value),
                "pack": _s(row[3].value) if len(row) > 3 else "",
            }
    else:
        warnings.append("No 'Mic Assign' sheet — positions and IEM packs unavailable.")

    return {"sunday": sunday, "vocals": vocals, "misc": misc,
            "assign": assign, "warnings": warnings}


def _person_key(name: str) -> str:
    """'Chris Vox' -> 'chris'; 'Joe B' -> 'joe b'. Strips the role suffix
    Dave appends to vocalists."""
    name = name.strip()
    if name.lower().endswith(" vox"):
        name = name[:-4]
    return name.strip().lower()


def _match_person(people, raw_name: str):
    """Match a sheet name against person rows. Exact display-name match
    (ignoring a trailing initial's dot) wins; then unique first-name
    match. Returns (person_row_or_None, warning_or_None)."""
    key = _person_key(raw_name)
    if not key:
        return None, None
    for p in people:
        if p["display_name"].rstrip(".").lower() == key:
            return p, None
    first_matches = [
        p for p in people
        if p["display_name"].split()[0].lower() == key.split()[0]
    ]
    if len(first_matches) == 1:
        return first_matches[0], None
    if len(first_matches) > 1:
        return None, f"'{raw_name}': several people share that first name — pick manually."
    return None, f"'{raw_name}': no matching person (add them on the People page, then re-import)."


def _match_channel_by_tag(channels, tag: str, kinds: tuple):
    """Match 'Red HH' / 'Orng RF' / 'Sermon RF' against channel labels
    or color tags, restricted to the given kinds."""
    tag_l = tag.lower()
    pool = [c for c in channels if c["kind"] in kinds]
    # 1. Whole-tag match against label or the free-text capsule tag.
    for c in pool:
        if c["label"].lower() == tag_l or (c["capsule"] or "").lower() == tag_l:
            return c
    # 2. Color-word match ("Red HH" ~ "Red Handheld"; "Wht HH" ~ "White HH").
    words = re.split(r"[\s/]+", tag_l)
    for word in words:
        for color, spellings in COLOR_SYNONYMS.items():
            if word in spellings:
                hits = [
                    c for c in pool
                    if any(sp in c["label"].lower() for sp in spellings)
                    or any(sp in (c["capsule"] or "").lower() for sp in spellings)
                ]
                if len(hits) == 1:
                    return hits[0]
    # 3. Distinctive-word match ("Sermon RF" ~ "Sermon Headset").
    for word in words:
        if word in ("rf", "hh", "pack"):
            continue
        hits = [c for c in pool if word in c["label"].lower()]
        if len(hits) == 1:
            return hits[0]
    return None


def _match_iem(channels, pack: str):
    """'Pack 1' -> the IEM channel whose label carries the same number."""
    digits = re.findall(r"\d+", pack)
    if not digits:
        return None
    n = digits[0]
    pool = [c for c in channels if c["kind"] == "iem"]
    for c in pool:
        if c["label"].lower() == pack.lower():
            return c
    hits = [c for c in pool if re.findall(r"\d+", c["label"])[:1] == [n]]
    if len(hits) == 1:
        return hits[0]
    return None


def build_plan(db, parsed: dict) -> dict:
    people = db.execute(
        "SELECT id, display_name FROM person WHERE archived=0"
    ).fetchall()
    channels = db.execute(
        "SELECT id, label, kind, capsule FROM channel WHERE archived=0"
    ).fetchall()
    positions = {
        r["label"].lower(): r
        for r in db.execute("SELECT id, label FROM position WHERE archived=0")
    }
    slots = {
        r["bank_order"]: r
        for r in db.execute("SELECT id, bank_order, kind FROM slot WHERE archived=0")
    }

    plan = {"sunday": parsed["sunday"], "assignments": [],
            "warnings": list(parsed["warnings"])}

    def resolve(entry, bank_order, mic_kinds):
        slot = slots.get(bank_order)
        if slot is None:
            return None
        a = {"slot_id": slot["id"], "bank_order": bank_order,
             "person_id": None, "person": "", "mic_channel_id": None, "mic": "",
             "iem_channel_id": None, "iem": "", "position_id": None, "position": "",
             "mymix": None, "clear": entry is None, "notes": []}
        if entry is None:
            a["notes"].append("No row this week — slot will be emptied.")
            return a

        person, warn = _match_person(people, entry["instrument"])
        if person is not None:
            a["person_id"], a["person"] = person["id"], person["display_name"]
        elif warn:
            a["notes"].append(warn)

        if entry["mic"]:
            ch = _match_channel_by_tag(channels, entry["mic"], mic_kinds)
            if ch is not None:
                a["mic_channel_id"], a["mic"] = ch["id"], ch["label"]
            else:
                a["notes"].append(
                    f"Mic '{entry['mic']}': no matching channel in inventory.")

        a["mymix"] = entry["mymix"] or None

        extra = parsed["assign"].get(_person_key(entry["instrument"]), {})
        if extra.get("pack") and slot["kind"] == "paired":
            iem = _match_iem(channels, extra["pack"])
            if iem is not None:
                a["iem_channel_id"], a["iem"] = iem["id"], iem["label"]
            else:
                a["notes"].append(
                    f"IEM '{extra['pack']}': no matching IEM channel in inventory.")
        if extra.get("position"):
            pos = positions.get(extra["position"].lower())
            if pos is not None:
                a["position_id"], a["position"] = pos["id"], pos["label"]
            else:
                a["position"] = extra["position"]
                a["notes"].append(f"Position '{extra['position']}' will be created.")
        return a

    vocals, misc = parsed["vocals"], parsed["misc"]
    for i, bank_order in enumerate(PAIRED_SLOTS):
        a = resolve(vocals[i] if i < len(vocals) else None, bank_order, ("handheld",))
        if a:
            plan["assignments"].append(a)
    for i, bank_order in enumerate(MIC_ONLY_SLOTS):
        a = resolve(misc[i] if i < len(misc) else None, bank_order,
                    ("beltpack", "handheld"))
        if a:
            plan["assignments"].append(a)

    if len(vocals) > len(PAIRED_SLOTS):
        plan["warnings"].append(
            f"{len(vocals) - len(PAIRED_SLOTS)} vocalist row(s) beyond slot 6 ignored.")
    if len(misc) > len(MIC_ONLY_SLOTS):
        plan["warnings"].append(
            f"{len(misc) - len(MIC_ONLY_SLOTS)} wireless row(s) beyond slot 10 ignored.")
    return plan


def apply_plan(db, assignments: list) -> int:
    """Write the assignments. Creates any positions the plan flagged.
    Returns the number of slots updated."""
    for a in assignments:
        if a["position_id"] is None and a["position"]:
            row = db.execute(
                "SELECT id FROM position WHERE archived=0 AND lower(label)=lower(?)",
                (a["position"],),
            ).fetchone()
            if row is None:
                cur = db.execute("INSERT INTO position (label) VALUES (?)",
                                 (a["position"],))
                a["position_id"] = cur.lastrowid
            else:
                a["position_id"] = row["id"]
        db.execute(
            """UPDATE slot SET
                 person_id=?, mic_channel_id=?, iem_channel_id=?,
                 position_id=?, mymix_channel=?, updated_at=datetime('now')
               WHERE id=?""",
            (a["person_id"], a["mic_channel_id"], a["iem_channel_id"],
             a["position_id"], a["mymix"], a["slot_id"]),
        )
    db.commit()
    return len(assignments)
