"""
Live Shure receiver telemetry — the "commit 3" the wall was built for.

One daemon thread inside the app process (gunicorn runs a single
worker, so there is exactly one). It reads which receivers to talk to
straight from the channel table (shure_ip + shure_type, derived from
the receiver chosen in admin), keeps one connection per receiver on
TCP/UDP 2202, and holds the latest battery / runtime / RF / audio / TX
state in memory. Nothing live is ever written to the DB: it's
ephemeral and joins onto channel rows at read time by
(shure_ip, receiver channel number) — or, when no number was entered,
by matching the WWB channel name the receiver reports.

Protocol knowledge comes from py/ (micboard, Python 2) plus Shure's
published command-string docs. Families:
  ulxd / qlxd  TCP  < GET n ALL >, BATT_BARS, BATT_RUN_TIME, RX_RF_LVL
  axtd         TCP  Axient Digital: TX_BATT_BARS, TX_BATT_MINS, RSSI
  slxd         TCP  SLX-D / SLX-D+: same TX_ names; SAMPLE pk rms rssi.
                    Third-party control is OFF by default on SLX-D —
                    enable it on the receiver (Menu → Network) first.
  uhfr         UDP  UHF-R: * GET n TX_BAT * ; star-delimited
  p10t         TCP  PSM 1000: rack transmitter — online/offline only

Stdlib only. Nothing here imports Flask.
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

log = logging.getLogger("ictech.live")

PORT = 2202
POLL_TARGETS_EVERY = 15      # s — pick up admin edits without a restart
QUERY_EVERY = 10             # s — re-ask battery/runtime (keepalive too)
OFFLINE_AFTER = 25           # s of silence → receiver is "RX error"
RECONNECT_EVERY = 10         # s between connection attempts
CONNECT_TIMEOUT = 2.0

# Status thresholds. Bars are Shure's 0-5; runtime (rechargeables
# only) beats bars when the transmitter reports it. Conservative on
# purpose: a "Low" pack still does a service, a "Replace" pack doesn't.
REPLACE_BARS = 2             # 0-2 bars
LOW_BARS = 3
REPLACE_MINUTES = 45
LOW_MINUTES = 90

BADGES = {
    "OK": "OK",
    "LOW": "Low",
    "REPLACE": "Replace",
    "TX_OFF": "TX off",
    "RX_ERROR": "RX error",
    "ONLINE": "Online",
}

MIC_FAMILIES = {"ulxd", "qlxd", "axtd", "slxd", "uhfr"}
TCP_FAMILIES = {"ulxd", "qlxd", "axtd", "slxd", "p10t"}


def channel_count(model: str | None) -> int:
    """Channels on a receiver, from its model number: ULXD4Q / AD4Q /
    SLXD4Q+ → 4, ULXD4D / AD4D / UR4D / P10T → 2, else 1."""
    m = (model or "").upper().replace("DAN", "").rstrip("+")
    if m == "P10T":
        return 2
    if m.endswith("Q"):
        return 4
    if m.endswith("D"):
        return 2
    return 1


def norm_name(s: str | None) -> str:
    return re.sub(r"[\s_]+", " ", (s or "")).strip().upper()


def rf_bars(dbm: float | None) -> int | None:
    if dbm is None:
        return None
    for floor, bars in ((-60, 5), (-68, 4), (-75, 3), (-82, 2), (-90, 1)):
        if dbm >= floor:
            return bars
    return 0


def fmt_minutes(mins: int | None) -> str | None:
    if mins is None:
        return None
    mins = max(0, int(mins))
    return f"{mins // 60}h {mins % 60:02d}m" if mins >= 60 else f"{mins}m"


class Channel:
    """Latest known state of one receiver channel."""

    def __init__(self, rx: "Receiver", num: int):
        self.rx = rx
        self.num = num
        self.name = None
        self.battery = None          # 0-5, None = unknown / no TX
        self.runtime = None          # minutes, rechargeables only
        self.tx_model = None
        self.rf_dbm = None
        self.audio = None            # 0-100
        self.frequency = None        # "578.350"
        self.tx_seen = False         # has the TX ever been on this session
        self.tx_on_since = None
        # Battery-drain history for the time-left estimate: (t, bars)
        # at each bar change since this transmitter powered on.
        self._drops: list[tuple[float, int]] = []

    # --- setters -------------------------------------------------
    def set_battery(self, raw: str):
        try:
            v = int(raw)
        except ValueError:          # UHF-R reports 'U' for unknown
            v = 255
        bars = v if 0 <= v <= 5 else None
        now = time.time()
        if bars is None:
            if self.battery is not None:
                self._drops = []
                self.tx_on_since = None
            self.battery = None
            return
        if self.battery is None:
            self.tx_on_since = now
            self._drops = [(now, bars)]
        elif bars > self.battery:      # fresh battery: restart history
            self._drops = [(now, bars)]
        elif bars < self.battery:
            self._drops.append((now, bars))
        self.battery = bars
        self.tx_seen = True

    def set_runtime(self, raw: str):
        try:
            v = int(raw)
        except ValueError:
            return
        self.runtime = v if 0 <= v <= 65532 else None

    def set_frequency(self, raw: str):
        digits = re.sub(r"\D", "", raw)
        if digits and int(digits):
            self.frequency = f"{int(digits) / 1000:.3f}"

    # --- derived -------------------------------------------------
    @property
    def tx_on(self) -> bool:
        if self.tx_model is not None and self.tx_model.upper() == "UNKNOWN":
            return False
        return self.battery is not None or self.runtime is not None

    def estimate_minutes(self) -> int | None:
        """Bars-only transmitters (AA packs): extrapolate from how fast
        the bars have been falling. Needs two bar drops to say anything."""
        if self.battery is None or len(self._drops) < 3:
            return None
        (t0, b0), (tk, bk) = self._drops[1], self._drops[-1]
        if b0 <= bk or tk <= t0:
            return None
        per_bar = (tk - t0) / (b0 - bk)
        left = self.battery * per_bar - (time.time() - tk)
        return max(0, int(left // 60))

    def status(self) -> str:
        if not self.rx.online:
            return "RX_ERROR"
        if self.rx.family == "p10t":
            return "ONLINE"
        if not self.tx_on:
            return "TX_OFF"
        if self.runtime is not None:
            if self.runtime < REPLACE_MINUTES:
                return "REPLACE"
            if self.runtime < LOW_MINUTES:
                return "LOW"
            return "OK"
        if self.battery is not None:
            if self.battery <= REPLACE_BARS:
                return "REPLACE"
            if self.battery <= LOW_BARS:
                return "LOW"
        return "OK"

    def as_dict(self) -> dict:
        st = self.status()
        on = st not in ("RX_ERROR", "TX_OFF", "ONLINE")
        mins, est = self.runtime, False
        if on and mins is None:
            mins, est = self.estimate_minutes(), True
            if mins is None:
                est = False
        return {
            "status": st,
            "badge": BADGES[st],
            "tx_on": on,
            "battery": self.battery if on else None,
            "rf": rf_bars(self.rf_dbm) if on else None,
            "rf_dbm": round(self.rf_dbm) if on and self.rf_dbm is not None else None,
            "audio": self.audio if on else None,
            "runtime_min": mins if on else None,
            "runtime_est": est,
            "runtime_text": (("~" if est else "") + fmt_minutes(mins)) if on and mins is not None else None,
            "tx_model": self.tx_model if on else None,
            "frequency": self.frequency,
            "rx_name": self.name,
            "rx_channel": self.num,
            "rx_ip": self.rx.ip,
            "family": self.rx.family,
        }


class Receiver:
    """One rack unit at one IP."""

    def __init__(self, ip: str, family: str, nch: int):
        self.ip = ip
        self.family = family
        self.channels = {n: Channel(self, n) for n in range(1, nch + 1)}
        self.sock: socket.socket | None = None
        self.online = False
        self.last_rx = 0.0
        self.last_query = 0.0
        self.last_attempt = 0.0
        self.buf = ""
        self.out: list[str] = []

    @property
    def udp(self) -> bool:
        return self.family == "uhfr"

    def ensure_channels(self, nch: int):
        for n in range(1, nch + 1):
            self.channels.setdefault(n, Channel(self, n))

    # --- outbound ------------------------------------------------
    def cmd(self, s: str):
        self.out.append(s)

    def hello(self):
        for n in self.channels:
            if self.udp:
                for prop in ("CHAN_NAME", "TX_BAT", "FREQUENCY"):
                    self.cmd(f"* GET {n} {prop} *")
                self.cmd(f"* METER {n} ALL 033 *")     # ~1 s (30 ms units)
            elif self.family == "p10t":
                self.cmd(f"< GET {n} CHAN_NAME >")
                self.cmd(f"< GET {n} FREQUENCY >")
            else:
                self.cmd(f"< GET {n} ALL >")
                self.cmd(f"< SET {n} METER_RATE 01000 >")
        self.last_query = time.time()

    def query(self):
        bat = {"ulxd": ("BATT_BARS", "BATT_RUN_TIME"),
               "qlxd": ("BATT_BARS", "BATT_RUN_TIME"),
               "axtd": ("TX_BATT_BARS", "TX_BATT_MINS"),
               "slxd": ("TX_BATT_BARS", "TX_BATT_MINS", "TX_MODEL")}
        for n in self.channels:
            if self.udp:
                self.cmd(f"* GET {n} TX_BAT *")
                self.cmd(f"* GET {n} CHAN_NAME *")
            elif self.family == "p10t":
                self.cmd(f"< GET {n} CHAN_NAME >")
            else:
                for prop in bat[self.family]:
                    self.cmd(f"< GET {n} {prop} >")
        self.last_query = time.time()

    # --- connection ----------------------------------------------
    def connect(self):
        self.close()
        self.last_attempt = time.time()
        try:
            if self.udp:
                s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                s.connect((self.ip, PORT))
            else:
                s = socket.create_connection((self.ip, PORT), timeout=CONNECT_TIMEOUT)
            s.setblocking(False)
        except OSError as e:
            log.debug("connect %s failed: %s", self.ip, e)
            self.sock = None
            return
        self.sock = s
        # TCP: the connect itself proves the box is there; UDP has to
        # wait for the first reply.
        if not self.udp:
            self.mark_alive()
        self.hello()

    def close(self):
        if self.sock is not None:
            try:
                if not self.udp and self.family != "p10t":
                    for n in self.channels:     # be polite: stop metering
                        self.sock.send(f"< SET {n} METER_RATE 00000 >".encode())
            except OSError:
                pass
            try:
                self.sock.close()
            except OSError:
                pass
        self.sock = None
        if self.online:
            log.info("receiver %s (%s) offline", self.ip, self.family)
        self.online = False
        self.buf = ""
        self.out = []

    def mark_alive(self):
        if not self.online:
            log.info("receiver %s (%s) online", self.ip, self.family)
        self.online = True
        self.last_rx = time.time()

    def flush(self):
        while self.out and self.sock is not None:
            msg = self.out.pop(0)
            try:
                self.sock.send(msg.encode("ascii", "replace"))
            except BlockingIOError:
                self.out.insert(0, msg)
                return
            except OSError:
                self.close()
                return

    def read(self):
        try:
            data = self.sock.recv(4096)
        except BlockingIOError:
            return
        except OSError:
            self.close()
            return
        if not data:
            self.close()
            return
        self.mark_alive()
        self.buf += data.decode("ascii", "replace")
        delim = "*" if self.udp else ">"
        if self.udp:
            # UHF-R frames start and end with '*'; split on the pairs.
            for frame in re.findall(r"\*([^*]*)\*", self.buf):
                self.parse(frame)
            self.buf = ""
            return
        while delim in self.buf:
            frame, self.buf = self.buf.split(delim, 1)
            frame = frame.split("<", 1)[-1]
            self.parse(frame)

    # --- inbound -------------------------------------------------
    def parse(self, frame: str):
        frame = frame.strip()
        names = re.findall(r"\{([^}]*)\}", frame)
        flat = re.sub(r"\{[^}]*\}", "{}", frame)
        parts = flat.split()
        if len(parts) < 3 or not parts[1].isdigit():
            return
        kind, n = parts[0], int(parts[1])
        ch = self.channels.get(n)
        if ch is None:
            return
        try:
            if kind == "SAMPLE":
                self.parse_sample(ch, parts)
            elif kind in ("REP", "REPORT"):
                self.parse_report(ch, parts[2], parts[3:], names)
        except (IndexError, ValueError):
            log.debug("unparsed %s: %s", self.ip, frame)

    def parse_report(self, ch: Channel, prop: str, args: list[str], names: list[str]):
        val = args[0] if args else ""
        if prop == "CHAN_NAME":
            ch.name = (names[0] if names else " ".join(args)).strip() or None
        elif prop in ("BATT_BARS", "TX_BATT_BARS", "TX_BAT"):
            ch.set_battery(val)
        elif prop in ("BATT_RUN_TIME", "TX_BATT_MINS"):
            ch.set_runtime(val)
        elif prop in ("TX_MODEL", "TX_TYPE"):
            ch.tx_model = val or None
            if val.upper() == "UNKNOWN":
                ch.set_battery("255")
                ch.runtime = None
        elif prop == "FREQUENCY":
            ch.set_frequency(val)
        elif prop == "RX_RF_LVL" and self.family in ("ulxd", "qlxd"):
            ch.rf_dbm = int(val) - 128
        elif prop == "AUDIO_LVL" and self.family in ("ulxd", "qlxd"):
            ch.audio = min(100, int(val) * 2)

    def parse_sample(self, ch: Channel, p: list[str]):
        # Field orders per Shure's command-string docs / micboard.
        if p[2] != "ALL":
            return
        if self.family in ("ulxd", "qlxd"):
            # SAMPLE n ALL <antenna> <rf 0-115> <audio 0-50>
            ch.rf_dbm = int(p[4]) - 128
            ch.audio = min(100, int(p[5]) * 2)
        elif self.family == "slxd":
            # SAMPLE n ALL <audPeak> <audRms> <rssi>, each value-120
            ch.audio = _dbfs_pct(int(p[4]) - 120)
            ch.rf_dbm = int(p[5]) - 120
        elif self.family == "axtd":
            # SAMPLE n ALL <qual> <audBitmap> <audPeak> <audRms> <ant>
            #              <rfBitmapA> <rssiA> <rfBitmapB> <rssiB>
            ch.audio = _dbfs_pct(int(p[6]) - 120)
            rssi = [int(p[i]) - 120 for i in (9, 11) if len(p) > i]
            ch.rf_dbm = max(rssi) if rssi else None
        elif self.family == "uhfr":
            # SAMPLE n ALL <ant> <rf> <?> <battery> <audio bitmap>
            ch.rf_dbm = -int(p[4])
            ch.set_battery(p[6])


def _dbfs_pct(dbfs: float) -> int:
    """-60 dBFS..0 → 0..100: the range where a vocal actually lives."""
    return int(max(0, min(100, (dbfs + 60) / 60 * 100)))


class LiveTelemetry:
    """The poller thread plus the read side the routes use."""

    def __init__(self, db_path: str):
        self.db_path = db_path
        self.lock = threading.Lock()
        self.receivers: dict[str, Receiver] = {}
        # channel_id -> (ip, receiver channel number or None, WWB name)
        self.targets: dict[int, tuple[str, int | None, str | None]] = {}
        self._thread: threading.Thread | None = None
        self._last_targets = 0.0

    # --- lifecycle -----------------------------------------------
    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._run, name="shure-live", daemon=True)
        self._thread.start()
        log.info("live receiver polling started")

    def _run(self):
        while True:
            try:
                self._tick()
            except Exception:                     # never let the thread die
                log.exception("live poller tick failed")
                time.sleep(1)

    def _tick(self):
        now = time.time()
        if now - self._last_targets > POLL_TARGETS_EVERY:
            self._load_targets()
            self._last_targets = now

        with self.lock:
            rxs = list(self.receivers.values())
        # Connects block for up to CONNECT_TIMEOUT each; do them outside
        # the lock so a dead receiver never stalls /api/state. This
        # thread is the only writer, so the readers just see the flip.
        for rx in rxs:
            if rx.sock is None:
                if now - rx.last_attempt > RECONNECT_EVERY:
                    rx.connect()
            elif not rx.online and now - rx.last_attempt > OFFLINE_AFTER:
                rx.connect()                # UDP box never answered: retry
        with self.lock:
            for rx in rxs:
                if rx.sock is None:
                    continue
                if rx.online and now - rx.last_rx > OFFLINE_AFTER:
                    rx.close()
                    continue
                if now - rx.last_query > QUERY_EVERY:
                    rx.query()
            socks = {rx.sock: rx for rx in rxs if rx.sock is not None}
            writers = [s for s, rx in socks.items() if rx.out]

        if not socks:
            time.sleep(0.5)
            return
        r, w, _ = select.select(list(socks), writers, [], 0.5)
        with self.lock:
            for s in w:
                socks[s].flush()
            for s in r:
                if socks[s].sock is s:
                    socks[s].read()

    def _load_targets(self):
        try:
            conn = sqlite3.connect(self.db_path, timeout=5)
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """SELECT c.id, c.shure_ip, c.shure_channel, c.shure_type,
                          c.shure_channel_name, rm.model AS rx_model
                     FROM channel c
                     LEFT JOIN wireless_model rm ON rm.id = c.receiver_model_id
                    WHERE c.archived = 0 AND c.shure_ip IS NOT NULL
                      AND c.shure_ip != '' AND c.shure_type IS NOT NULL"""
            ).fetchall()
            conn.close()
        except sqlite3.Error as e:
            log.warning("live poller couldn't read channels: %s", e)
            return

        wanted: dict[str, tuple[str, int]] = {}
        targets = {}
        for r in rows:
            ip = r["shure_ip"].strip()
            nch = max(channel_count(r["rx_model"]), r["shure_channel"] or 1)
            fam, have = wanted.get(ip, (r["shure_type"], 0))
            wanted[ip] = (fam, max(have, nch))
            targets[r["id"]] = (ip, r["shure_channel"], r["shure_channel_name"])

        with self.lock:
            for ip in list(self.receivers):
                rx = self.receivers[ip]
                if ip not in wanted or wanted[ip][0] != rx.family:
                    rx.close()
                    del self.receivers[ip]
            for ip, (fam, nch) in wanted.items():
                rx = self.receivers.get(ip)
                if rx is None:
                    self.receivers[ip] = Receiver(ip, fam, nch)
                elif len(rx.channels) < nch:
                    rx.ensure_channels(nch)
                    if rx.sock is not None:
                        rx.hello()
            self.targets = targets

    # --- read side -----------------------------------------------
    def _resolve(self, channel_id: int) -> Channel | None:
        t = self.targets.get(channel_id)
        if not t:
            return None
        ip, num, name = t
        rx = self.receivers.get(ip)
        if rx is None:
            return None
        if num:
            return rx.channels.get(num)
        want = norm_name(name)
        if want:
            for ch in rx.channels.values():
                if norm_name(ch.name) == want:
                    return ch
        if len(rx.channels) == 1:
            return rx.channels[1]
        return None

    def channel_state(self, channel_id: int | None) -> dict | None:
        """Live dict for one channel row, None when it isn't on the
        network at all (no IP / no controllable receiver)."""
        if channel_id is None:
            return None
        with self.lock:
            if channel_id not in self.targets:
                return None
            ch = self._resolve(channel_id)
            if ch is not None:
                return ch.as_dict()
            ip = self.targets[channel_id][0]
            rx = self.receivers.get(ip)
            online = bool(rx and rx.online)
            # Receiver reachable but no channel matched the WWB name:
            # say so instead of pretending the TX is off.
            st = "UNMATCHED" if online else "RX_ERROR"
            return {"status": st,
                    "badge": "Check ch #" if online else BADGES["RX_ERROR"],
                    "tx_on": False, "battery": None, "rf": None,
                    "rx_ip": ip}

    def receivers_state(self) -> list[dict]:
        with self.lock:
            return [{
                "ip": rx.ip, "family": rx.family, "online": rx.online,
                "last_rx_age": round(time.time() - rx.last_rx, 1) if rx.last_rx else None,
                "channels": [dict(ch.as_dict(), num=n) for n, ch in sorted(rx.channels.items())],
            } for rx in sorted(self.receivers.values(), key=lambda r: r.ip)]


_instance: LiveTelemetry | None = None
_instance_lock = threading.Lock()


def get(db_path: str, start: bool = True) -> LiveTelemetry:
    """Process-wide singleton, started lazily on the first display
    request — so the Flask debug reloader's watcher process (which
    never serves) doesn't open a second set of receiver sockets."""
    global _instance
    with _instance_lock:
        if _instance is None:
            _instance = LiveTelemetry(db_path)
        # ICTECH_LIVE=0: never open receiver sockets (internet-facing
        # box, CI). Reads still work — every networked channel is then
        # simply "RX error".
        if start and os.environ.get("ICTECH_LIVE", "1") != "0":
            _instance.start()
        return _instance
