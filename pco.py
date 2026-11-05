"""
Planning Center Services link — the Tech Report without the PDF.

The Tech Report Dave prints is Planning Center's view of one plan's
team members. This reads the same data straight from the Services API
and hands importer.build_tech_plan() the exact shape
importer.parse_tech_report() produces, so matching, new-person rules,
seat mapping and apply are shared — one set of rules, two sources.

  PC team            -> "category"   (Audio/Visual, Band, Music Leader...)
  team_position_name -> "position"   (Sound, Drums, Keys & Vocals...)
  status U           -> tentative    (the PDF's trailing '?')
  status D           -> dropped      (filter=not_declined)

Auth: a Personal Access Token (api.planningcenteronline.com →
Personal Access Tokens) from env ICTECH_PCO_APP_ID / ICTECH_PCO_SECRET,
sent as HTTP Basic. Never stored in the DB. Stdlib only.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, timedelta

API = "https://api.planningcenteronline.com/services/v2"
TIMEOUT = 15

# Teams pulled by default — the categories the Tech Report prints.
# Anything else in the plan (greeters, kids...) is ignored unless
# ticked in admin, so it never mints people or roles on the wall.
DEFAULT_TEAM_WORDS = ("audio", "visual", "tech", "band", "vocal", "music",
                      "leader", "worship", "stream", "interpret",
                      "speaker", "preach", "host")


class PCOError(Exception):
    pass


def credentials() -> tuple[str, str] | None:
    app_id = os.environ.get("ICTECH_PCO_APP_ID", "").strip()
    secret = os.environ.get("ICTECH_PCO_SECRET", "").strip()
    return (app_id, secret) if app_id and secret else None


def configured() -> bool:
    return credentials() is not None


def _get(path_or_url: str, params: dict | None = None) -> dict:
    creds = credentials()
    if not creds:
        raise PCOError("Planning Center isn't connected (no token in .env).")
    url = path_or_url if path_or_url.startswith("http") else API + path_or_url
    if params:
        url += ("&" if "?" in url else "?") + urllib.parse.urlencode(params)
    token = base64.b64encode(f"{creds[0]}:{creds[1]}".encode()).decode()
    req = urllib.request.Request(url, headers={
        "Authorization": f"Basic {token}",
        "Accept": "application/json",
        "User-Agent": "icTech-prodapp",
    })
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        if e.code == 401:
            raise PCOError("Planning Center rejected the token (401) — "
                           "check ICTECH_PCO_APP_ID / ICTECH_PCO_SECRET.") from None
        if e.code == 403:
            raise PCOError("The token's Planning Center user can't see "
                           "Services (403).") from None
        if e.code == 429:
            raise PCOError("Planning Center rate limit — try again in a minute.") from None
        raise PCOError(f"Planning Center error {e.code}.") from None
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise PCOError(f"Can't reach Planning Center: {getattr(e, 'reason', e)}") from None


def _get_all(path: str, params: dict | None = None) -> tuple[list, list]:
    """Follow JSON:API pagination. Returns (data, included)."""
    params = dict(params or {}, per_page=100)
    body = _get(path, params)
    data, included = list(body.get("data", [])), list(body.get("included", []))
    pages = 0
    while body.get("links", {}).get("next") and pages < 20:
        body = _get(body["links"]["next"])
        data += body.get("data", [])
        included += body.get("included", [])
        pages += 1
    return data, included


def service_types() -> list[dict]:
    data, _ = _get_all("/service_types", {"order": "sequence"})
    return [{"id": d["id"], "name": d["attributes"].get("name")} for d in data]


def teams(service_type_id: str) -> list[dict]:
    data, _ = _get_all(f"/service_types/{service_type_id}/teams")
    out = [{"id": d["id"], "name": d["attributes"].get("name") or ""}
           for d in data if not d["attributes"].get("archived_at")]
    return sorted(out, key=lambda t: t["name"].lower())


def default_team_ids(team_list: list[dict]) -> list[str]:
    return [t["id"] for t in team_list
            if any(w in t["name"].lower() for w in DEFAULT_TEAM_WORDS)]


def plan_for(service_type_id: str, service_day: date) -> dict | None:
    """The plan for this week's service: the first plan dated on or
    after service_day (the wall's week rolls over Sunday 12:30 PM)."""
    after = (service_day - timedelta(days=1)).isoformat()
    body = _get(f"/service_types/{service_type_id}/plans",
                {"filter": "after", "after": after, "order": "sort_date",
                 "per_page": 5})
    for p in body.get("data", []):
        a = p["attributes"]
        if (a.get("sort_date") or "")[:10] >= service_day.isoformat():
            return {"id": p["id"], "title": a.get("title"),
                    "dates": a.get("dates"), "sort_date": a.get("sort_date"),
                    "url": a.get("planning_center_url"),
                    "updated_at": a.get("updated_at")}
    return None


def fetch_parsed(service_type_id: str, team_ids: list[str] | None,
                 service_day: date) -> tuple[dict, dict]:
    """(parsed, plan_meta). parsed matches parse_tech_report()'s
    output: {date, positions: [{category, position, people}], leader_name}."""
    plan = plan_for(service_type_id, service_day)
    if plan is None:
        raise PCOError(f"No plan on or after {service_day:%B %-d} in that service type.")
    data, included = _get_all(
        f"/service_types/{service_type_id}/plans/{plan['id']}/team_members",
        {"filter": "not_declined,not_deleted", "include": "team"})
    team_names = {i["id"]: i["attributes"].get("name") or ""
                  for i in included if i.get("type") == "Team"}
    wanted = set(team_ids) if team_ids else None

    groups: dict[tuple, dict] = {}
    leader_name = None
    for m in data:
        a = m["attributes"]
        if (a.get("status") or "").upper().startswith("D"):
            continue
        team_rel = (m.get("relationships", {}).get("team", {}) or {}).get("data") or {}
        tid = team_rel.get("id")
        if wanted is not None and tid not in wanted:
            continue
        name = " ".join((a.get("name") or "").split())
        if len(name.split()) < 2:        # matcher needs first + last
            continue
        team = team_names.get(tid, "")
        pos = (a.get("team_position_name") or team or "").strip()
        key = (team, pos)
        g = groups.setdefault(key, {"category": team, "position": pos, "people": []})
        g["people"].append({"name": name,
                            "tentative": (a.get("status") or "").upper().startswith("U")})
        if leader_name is None and (team.lower() == "music leader"
                                    or re.search(r"(music|worship) leader", pos, re.I)):
            leader_name = name

    positions = sorted(groups.values(), key=lambda g: (g["category"].lower(), g["position"].lower()))
    for g in positions:
        g["people"].sort(key=lambda p: p["name"])
    parsed = {"date": plan.get("dates"), "positions": positions, "leader_name": leader_name}
    return parsed, plan


def fingerprint(parsed: dict) -> str:
    """Stable hash of who-is-on-what: auto-sync applies only when the
    plan actually changed, so hand edits on the Slots page survive
    until Planning Center says something new."""
    return hashlib.sha256(json.dumps(parsed, sort_keys=True).encode()).hexdigest()[:16]


# ------------------------------------------------------------------
# Services LIVE: where we are in the service right now.
# ------------------------------------------------------------------
# GET .../plans/{id}/live?include=current_item_time,next_item_time
# gives the item TIMES (when the operator advanced, planned length);
# which ITEM each time belongs to comes from the plan's items with
# their item_times. Items change rarely, so they're cached a minute;
# the live pointer is cheap and re-read on every (cached) call.
_items_cache: dict = {}            # plan_id -> (fetched_at, {item_time_id: item})
_plan_cache: dict = {}             # (st, day) -> (fetched_at, plan)
ITEM_TYPES = {"song": "Song", "header": "Section", "media": "Media", "item": "Item"}


def _iso_ms(v):
    from datetime import datetime
    if not v:
        return None
    try:
        return int(datetime.fromisoformat(v.replace("Z", "+00:00")).timestamp() * 1000)
    except ValueError:
        return None


def _items_by_time(st: str, plan_id: str, need: set, now: float) -> dict:
    hit = _items_cache.get(plan_id)
    if hit and now - hit[0] < 60 and need <= set(hit[1]):
        return hit[1]
    data, _ = _get_all(f"/service_types/{st}/plans/{plan_id}/items", {"include": "item_times"})
    by_time = {}
    for it in data:
        a = it["attributes"]
        info = {"title": (a.get("title") or "").strip(), "type": a.get("item_type") or "item",
                "length": a.get("length") or 0, "sequence": a.get("sequence"),
                "position": a.get("service_position")}
        for t in ((it.get("relationships", {}).get("item_times") or {}).get("data") or []):
            by_time[t["id"]] = info
    _items_cache[plan_id] = (now, by_time)
    return by_time


def live_now(service_type_id: str, service_day: date) -> dict:
    """{live, plan, now, next}; now/next = {title, type, label,
    length (s), start_ms, end_ms}. live False when nobody is running
    Services LIVE for this week's plan."""
    import time as _time
    now = _time.time()
    key = (service_type_id, service_day.isoformat())
    hit = _plan_cache.get(key)
    if not hit or now - hit[0] > 300:
        hit = (now, plan_for(service_type_id, service_day))
        _plan_cache[key] = hit
    plan = hit[1]
    if plan is None:
        return {"live": False, "plan": None, "now": None, "next": None}
    body = _get(f"/service_types/{service_type_id}/plans/{plan['id']}/live",
                {"include": "current_item_time,next_item_time"})
    rel = (body.get("data") or {}).get("relationships") or {}
    times = {i["id"]: i for i in body.get("included", []) if i.get("type") == "ItemTime"}

    def ref(name):
        d = (rel.get(name) or {}).get("data")
        return d.get("id") if isinstance(d, dict) else None

    cur_id, next_id = ref("current_item_time"), ref("next_item_time")
    need = {i for i in (cur_id, next_id) if i}
    items = _items_by_time(service_type_id, plan["id"], need, now) if need else {}

    def entry(tid):
        if not tid:
            return None
        it = items.get(tid) or {}
        t = (times.get(tid) or {}).get("attributes") or {}
        length = int(t.get("length") or it.get("length") or 0)
        start = _iso_ms(t.get("live_start_at"))
        return {"title": it.get("title") or "—", "type": it.get("type"),
                "label": ITEM_TYPES.get(it.get("type"), "Item"), "length": length,
                "start_ms": start,
                "end_ms": start + length * 1000 if start and length else None}

    return {"live": cur_id is not None,
            "plan": {"title": plan.get("title"), "dates": plan.get("dates")},
            "now": entry(cur_id), "next": entry(next_id)}
