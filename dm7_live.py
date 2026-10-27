"""
Live FOH console state from the Yamaha DM7 — strictly read-only.

Same shape as shure_live.py: one daemon thread, one TCP connection to
the console's Remote Control Protocol (RCP, TCP 49280, newline-
delimited text), state in memory, nothing written to the DB. What it
keeps:

  InCh  Label/Name, Label/Color, Fader/On, Port/HA/Gain   (+ meters)
  Mix   Label/Name, Fader/On
  Mtrx  Label/Name, Fader/On                              (+ meters)
  InCh/Mix → Mtrx sends for the matrices that feed MyMix
  current scene number + name, console model / name

Immanuel's ears aren't fed by console mixes: DM7 matrix outs and
direct outs are the 16 MyMix inputs, and each person dials their own
IEM mix on their MyMix station. So what the console can tell us is
whether each MyMix feed is alive — and what's inside each matrix.

The console pushes `NOTIFY set ...` whenever a value changes, so after
the first read the link is quiet except for meters; `mtrstart` streams
stop on their own 10 s after the request, so they're renewed every 5 s.
A scene recall re-reads everything.

Protocol strings are from Bitfocus Companion's DM7 parameter dump and
a DM7 meter bridge measured against a real console (2026-09). The +48V
path is NOT in either — it's tried once and the column is hidden if
the console answers ERROR.

This module never sends `set`, `ssrecall` or anything else that changes
the console: `_send()` refuses them. It's Pete's board.
"""

from __future__ import annotations

import logging
import os
import re
import select
import socket
import sqlite3
import threading
import time

log = logging.getLogger("ictech.dm7")

PORT = 49280
CONNECT_TIMEOUT = 2.0
RECONNECT_EVERY = 10
OFFLINE_AFTER = 15          # s of silence (meters arrive ~4x/s when healthy)
METER_RENEW = 5             # s; the DM7 stops a stream 10 s after mtrstart
METER_MS = 250
CONFIG_EVERY = 15
PEAK_HOLD = 2.0             # s — a 2 s wall poll still sees a short phrase

IN_COUNT = 72               # DM7 meter source counts (mtrinfo)
MIX_COUNT = 48
MTRX_COUNT = 12
METERS = ("InCh/PreFader", "Mtrx/PostOn")

IN_PARAMS = ("Label/Name", "Label/Color", "Fader/On", "Port/HA/Gain")
MIX_PARAMS = ("Label/Name", "Fader/On")
MTRX_PARAMS = ("Label/Name", "Fader/On")
PHANTOM_PARAM = "Port/HA/Phantom"        # unverified on DM7 — see above
MTRX_RE = re.compile(r"\bm(?:a)?t(?:r)?(?:i)?x\s*(\d+)", re.I)   # Mtx 1 / Mtrx 1 / Matrix 1

READ_ONLY_VERBS = ("get ", "devinfo ", "devstatus ", "mtrstart ", "mtrstop ",
                   "scpmode ", "sscurrentt_ex ", "sscurrent_ex ", "ssinfot_ex ",
                   "ssinfo_ex ")

# levelwt (0-255) -> dB anchors, measured on a DM7 (raw 255 = over).
_LEVELWT = ((0, -120.0), (21, -60.0), (31, -50.0), (46, -40.0), (66, -30.0),
            (116, -20.0), (166, -10.0), (186, -6.0), (216, 0.0), (237, 6.0),
            (241, 10.0), (246, 18.0), (254, 20.0))
_TOKENS = re.compile(r'"(?:[^"\\]|\\.)*"|\S+')


def levelwt_db(raw: int) -> float:
    if raw <= 0:
        return -120.0
    for (r0, d0), (r1, d1) in zip(_LEVELWT, _LEVELWT[1:]):
        if raw <= r1:
            return d0 + (d1 - d0) * (raw - r0) / (r1 - r0)
    return 20.0


def signal_bars(db: float | None) -> int | None:
    """dB -> 0-5 for the wall: -50 / -35 / -20 / -10 / -3."""
    if db is None:
        return None
    return sum(db >= t for t in (-50, -35, -20, -10, -3))


def _unquote(tok: str):
    if tok.startswith('"') and tok.endswith('"') and len(tok) >= 2:
        return tok[1:-1].replace('\\"', '"')
    try:
        return int(tok)
    except ValueError:
        return tok


class Meter:
    """Peak-hold over PEAK_HOLD seconds per channel, plus a clip stamp."""

    def __init__(self):
        self.peak: dict[int, int] = {}
        self.peak_t: dict[int, float] = {}
        self.clip_t: dict[int, float] = {}
        self.last_t = 0.0

    def feed(self, vals: list[int]):
        now = self.last_t = time.time()
        for i, v in enumerate(vals):
            if v >= self.peak.get(i, -1) or now - self.peak_t.get(i, 0) > PEAK_HOLD:
                self.peak[i], self.peak_t[i] = v, now
            if v >= 255:
                self.clip_t[i] = now

    def db(self, i: int) -> float | None:
        if time.time() - self.last_t > 3 or i not in self.peak:
            return None
        return round(levelwt_db(self.peak[i]), 1)

    def clipped(self, i: int) -> bool:
        return time.time() - self.clip_t.get(i, 0) < 5


class Console:
    def __init__(self, ip: str):
        self.ip = ip
        self.sock: socket.socket | None = None
        self.online = False
        self.last_rx = 0.0
        self.last_attempt = 0.0
        self.last_meter = 0.0
        self.buf = ""
        self.out = bytearray()
        self.device: dict = {}
        self.inch: dict[int, dict] = {}
        self.mix: dict[int, dict] = {}
        self.mtrx: dict[int, dict] = {}
        # (src 'InCh'|'Mix', index, matrix) -> {"Level": .., "On": ..}
        self.sends: dict[tuple[str, int, int], dict] = {}
        self.want_inputs: list[int] = []     # 0-based, from the patch
        self.want_mtrx: list[int] = list(range(MTRX_COUNT))
        self.meters = {m: Meter() for m in METERS}
        self.scene: dict = {}
        self.unsupported: set[str] = set()
        self.extra_inputs = 0        # patch rows beyond IN_COUNT

    # --- outbound --------------------------------------------------
    def _send(self, cmd: str):
        if not cmd.startswith(READ_ONLY_VERBS):
            raise ValueError(f"refusing non-read-only RCP command: {cmd!r}")
        self.out += (cmd + "\n").encode("utf-8")

    def read_all(self):
        for k in ("productname", "devicename"):
            self._send(f"devinfo {k}")
        n_in = max(IN_COUNT, self.extra_inputs)
        for p in IN_PARAMS:
            for i in range(n_in):
                self._send(f"get MIXER:Current/InCh/{p} {i} 0")
        if PHANTOM_PARAM not in self.unsupported:
            self._send(f"get MIXER:Current/InCh/{PHANTOM_PARAM} 0 0")
        for p in MIX_PARAMS:
            for i in range(MIX_COUNT):
                self._send(f"get MIXER:Current/Mix/{p} {i} 0")
        for p in MTRX_PARAMS:
            for i in range(MTRX_COUNT):
                self._send(f"get MIXER:Current/Mtrx/{p} {i} 0")
        self.read_scene()
        self.read_sends()

    def read_scene(self):
        self._send('scpmode sstype "text"')
        for bank in ("scene_a", "scene_b"):
            self._send(f"sscurrentt_ex {bank}")

    def read_sends(self):
        """What's in each MyMix matrix: InCh→Mtrx for the patched inputs,
        Mix→Mtrx for every bus (vocal subgroups often feed matrices).
        Only the matrices the MyMix legend names — 120 x 12 x 2 reads
        for every matrix would be thousands."""
        self.sends = {}
        inputs = self.want_inputs or range(max(IN_COUNT, self.extra_inputs))
        for m in self.want_mtrx:
            for i in inputs:
                self._send(f"get MIXER:Current/InCh/ToMtrx/Level {i} {m}")
                self._send(f"get MIXER:Current/InCh/ToMtrx/On {i} {m}")
            for i in range(MIX_COUNT):
                self._send(f"get MIXER:Current/Mix/ToMtrx/Level {i} {m}")
                self._send(f"get MIXER:Current/Mix/ToMtrx/On {i} {m}")

    def renew_meters(self):
        for m in METERS:
            self._send(f"mtrstart MIXER:Current/{m} {METER_MS}")
        self.last_meter = time.time()

    # --- connection ------------------------------------------------
    def connect(self):
        self.close()
        self.last_attempt = time.time()
        try:
            s = socket.create_connection((self.ip, PORT), timeout=CONNECT_TIMEOUT)
            s.setblocking(False)
        except OSError as e:
            log.debug("connect %s failed: %s", self.ip, e)
            return
        self.sock = s
        self.online = True
        self.last_rx = time.time()
        log.info("DM7 %s connected", self.ip)
        self.read_all()
        self.renew_meters()

    def close(self):
        if self.sock is not None:
            try:
                self.sock.close()
            except OSError:
                pass
            if self.online:
                log.info("DM7 %s offline", self.ip)
        self.sock = None
        self.online = False
        self.buf = ""
        self.out = bytearray()

    def flush(self):
        if not self.out or self.sock is None:
            return
        try:
            n = self.sock.send(self.out)
        except BlockingIOError:
            return
        except OSError:
            self.close()
            return
        del self.out[:n]

    def read(self):
        try:
            data = self.sock.recv(65536)
        except BlockingIOError:
            return
        except OSError:
            self.close()
            return
        if not data:
            self.close()
            return
        self.last_rx = time.time()
        self.buf += data.decode("utf-8", "replace")
        while "\n" in self.buf:
            line, self.buf = self.buf.split("\n", 1)
            line = line.strip()
            if line:
                try:
                    self.parse(line)
                except (IndexError, ValueError):
                    log.debug("unparsed DM7 line: %s", line)

    # --- inbound ---------------------------------------------------
    def parse(self, line: str):
        t = _TOKENS.findall(line)
        if len(t) < 2:
            return
        status, verb = t[0].upper(), t[1]
        if status == "ERROR":
            if verb == "get" and len(t) > 2 and PHANTOM_PARAM in t[2]:
                self.unsupported.add(PHANTOM_PARAM)
            return
        if verb == "mtr" and len(t) > 4:
            addr = t[2].replace("MIXER:Current/", "")
            if addr in self.meters:
                self.meters[addr].feed([int(x, 16) for x in t[4:]])
            return
        if verb in ("get", "set") and len(t) >= 6:
            self._param(t[2], int(t[3]), int(t[4]), _unquote(t[5]))
            return
        if verb == "devinfo" and len(t) >= 4:
            self.device[t[2]] = _unquote(t[3])
            return
        if verb in ("sscurrentt_ex", "sscurrent_ex"):
            if status == "NOTIFY":           # recall: names/on all moved
                self.read_all()
                return
            if len(t) >= 4:
                num = _unquote(t[3])
                self.scene = {"bank": t[2], "number": str(num), "name": self.scene.get("name")
                              if self.scene.get("number") == str(num) else None}
                self._send(f'ssinfot_ex {t[2]} "{num}"')
            return
        if verb in ("ssinfot_ex", "ssinfo_ex") and len(t) >= 4:
            quoted = [_unquote(x) for x in t[3:] if x.startswith('"')]
            num = self.scene.get("number")
            names = [q for q in quoted if str(q) != num]
            if names:
                self.scene["name"] = str(names[0])
            return
        if verb.startswith("ssrecall") and status == "NOTIFY":
            self.read_all()

    def _param(self, addr: str, x: int, y: int, val):
        addr = addr.replace("MIXER:Current/", "")
        src, _, param = addr.partition("/")
        if param.startswith("ToMtrx/") and src in ("InCh", "Mix"):
            self.sends.setdefault((src, x, y), {})[param[7:]] = val
        elif src == "InCh":
            self.inch.setdefault(x, {})[param] = val
        elif src == "Mix":
            self.mix.setdefault(x, {})[param] = val
        elif src == "Mtrx":
            self.mtrx.setdefault(x, {})[param] = val

    # --- read side -------------------------------------------------
    def channel(self, ch: int) -> dict | None:
        """ch is 1-based (what the Input List calls FOH ch)."""
        i = ch - 1
        c = self.inch.get(i)
        if c is None and not self.online:
            return None
        c = c or {}
        db = self.meters["InCh/PreFader"].db(i)
        return {"ch": ch, "name": c.get("Label/Name"), "color": c.get("Label/Color"),
                "on": None if c.get("Fader/On") is None else bool(c.get("Fader/On")),
                "gain": c.get("Port/HA/Gain"), "phantom": c.get(PHANTOM_PARAM),
                "db": db, "signal": signal_bars(db),
                "clip": self.meters["InCh/PreFader"].clipped(i)}

    def matrix_state(self, n: int) -> dict:
        """n is 1-based ('Mtx 2' -> 2)."""
        i = n - 1
        m = self.mtrx.get(i, {})
        meter = self.meters["Mtrx/PostOn"]
        db = meter.db(i)
        return {"mtrx": n, "name": m.get("Label/Name"),
                "on": None if m.get("Fader/On") is None else bool(m.get("Fader/On")),
                "db": db, "signal": signal_bars(db), "clip": meter.clipped(i)}

    def matrix_sources(self, n: int) -> list[dict]:
        """Inputs and buses sent to matrix n (send on, above -inf,
        source on), loudest first."""
        out = []
        for (src, x, m), snd in self.sends.items():
            lvl = snd.get("Level")
            if m != n - 1 or not snd.get("On") or lvl is None or lvl <= -13800:
                continue
            table = self.inch if src == "InCh" else self.mix
            row = table.get(x, {})
            if not row.get("Fader/On", 1):
                continue
            name = row.get("Label/Name") or (f"Ch {x + 1}" if src == "InCh" else f"Mix {x + 1}")
            out.append({"src": src, "n": x + 1, "name": name, "db": round(lvl / 100, 1)})
        return sorted(out, key=lambda s: -s["db"])


class LiveConsole:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self.lock = threading.Lock()
        self.console: Console | None = None
        self._thread: threading.Thread | None = None
        self._last_cfg = 0.0

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._run, name="dm7-live", daemon=True)
        self._thread.start()

    def _run(self):
        while True:
            try:
                self._tick()
            except Exception:
                log.exception("DM7 poller tick failed")
                time.sleep(1)

    def _config(self):
        ip, extra = os.environ.get("ICTECH_DM7_IP", "").strip(), 0
        try:
            conn = sqlite3.connect(self.db_path, timeout=5)
            if not ip:
                row = conn.execute("SELECT value FROM app_setting WHERE key='dm7_ip'").fetchone()
                ip = (row[0] if row else "").strip()
            row = conn.execute("SELECT MAX(foh_ch) FROM patch_row").fetchone()
            extra = int(row[0] or 0)
            inputs = sorted({r[0] - 1 for r in conn.execute(
                "SELECT foh_ch FROM patch_row WHERE foh_ch BETWEEN 1 AND 120")})
            srcs = [r[0] for r in conn.execute("SELECT source FROM mymix_channel")]
            srcs += [r[0] for r in conn.execute("SELECT mymix_route FROM patch_row")]
            mtrx = sorted({int(m.group(1)) - 1 for v in srcs if v
                           for m in [MTRX_RE.search(v)] if m and 1 <= int(m.group(1)) <= MTRX_COUNT})
            conn.close()
        except sqlite3.Error:
            inputs, mtrx = [], []
        with self.lock:
            if not ip:
                if self.console:
                    self.console.close()
                self.console = None
            elif self.console is None or self.console.ip != ip:
                if self.console:
                    self.console.close()
                self.console = Console(ip)
            c = self.console
            if c:
                c.extra_inputs = min(extra, 120)
                mtrx = mtrx or list(range(MTRX_COUNT))
                if (inputs, mtrx) != (c.want_inputs, c.want_mtrx):
                    c.want_inputs, c.want_mtrx = inputs, mtrx
                    if c.online:            # new week's patch: re-read
                        c.read_sends()

    def _tick(self):
        now = time.time()
        if now - self._last_cfg > CONFIG_EVERY:
            self._config()
            self._last_cfg = now
        c = self.console
        if c is None:
            time.sleep(1)
            return
        if c.sock is None:
            if now - c.last_attempt > RECONNECT_EVERY:
                c.connect()             # outside the lock: may block 2 s
            else:
                time.sleep(0.5)
            return
        with self.lock:
            if now - c.last_rx > OFFLINE_AFTER:
                c.close()
                return
            if now - c.last_meter > METER_RENEW:
                c.renew_meters()
            sock = c.sock
            want_write = bool(c.out)
        r, w, _ = select.select([sock], [sock] if want_write else [], [], 0.5)
        with self.lock:
            if c.sock is not sock:
                return
            if w:
                c.flush()
            if r:
                c.read()

    # --- read side ---------------------------------------------------
    def state(self) -> dict:
        with self.lock:
            c = self.console
            if c is None:
                return {"configured": False, "online": False}
            return {"configured": True, "online": c.online, "ip": c.ip,
                    "model": c.device.get("productname"),
                    "name": c.device.get("devicename"),
                    "scene": dict(c.scene) if c.scene else None,
                    "phantom_readable": (PHANTOM_PARAM not in c.unsupported
                                         and any(PHANTOM_PARAM in v for v in c.inch.values()))}

    def channels(self, chs: list[int]) -> list[dict]:
        with self.lock:
            c = self.console
            if c is None or not c.online:
                return []
            return [x for x in (c.channel(ch) for ch in chs) if x]

    def matrix(self, n: int, sources: bool = False) -> dict | None:
        with self.lock:
            c = self.console
            if c is None or not c.online or not 1 <= n <= MTRX_COUNT:
                return None
            st = c.matrix_state(n)
            if sources:
                st["sources"] = c.matrix_sources(n)
            return st


_instance: LiveConsole | None = None
_instance_lock = threading.Lock()


def get(db_path: str, start: bool = True) -> LiveConsole:
    global _instance
    with _instance_lock:
        if _instance is None:
            _instance = LiveConsole(db_path)
        if start and os.environ.get("ICTECH_LIVE", "1") != "0":
            _instance.start()
        return _instance
