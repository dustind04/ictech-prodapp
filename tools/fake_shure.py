"""
Fake Shure receiver — exercise live telemetry without the rack.

Speaks enough of the 2202 ASCII protocol (ULX-D, QLX-D, SLX-D/SLX-D+,
Axient Digital) for the app's poller: GET n ALL, GET n <prop>, SET n
METER_RATE → periodic SAMPLE lines. Four channels by default:

  ch1  transmitter on, 5 bars, 4h runtime        → OK
  ch2  on, 3 bars                                 → Low
  ch3  on, 1 bar, 20 min                          → Replace
  ch4  switched off                               → TX off

Usage (from the repo root):
  python tools/fake_shure.py                       # ULX-D on 127.0.0.1:2202
  python tools/fake_shure.py --family slxd --host 127.0.0.2
  python tools/fake_shure.py --toggle 30           # ch4 flips on/off every 30s

Then in Admin → Channels give a channel Receiver = ULXD4Q, IP =
127.0.0.1, Receiver ch # = 1..4. Within ~15s the wall shows it live.
Port 2202 must be free on this machine.
"""

from __future__ import annotations

import argparse
import random
import socket
import threading
import time

NAMES = ["RED HH", "WHT HH", "BLU HH", "ORNG RF"]


class Ch:
    def __init__(self, n, bars, mins, on=True):
        self.n, self.bars, self.mins, self.on = n, bars, mins, on


def reports(fam: str, c: Ch) -> list[str]:
    bars = f"{c.bars:03d}" if c.on else "255"
    mins = f"{c.mins:05d}" if c.on and c.mins is not None else "65535"
    name = "{" + NAMES[(c.n - 1) % len(NAMES)].ljust(31) + "}"
    if fam in ("ulxd", "qlxd"):
        props = [("CHAN_NAME", name), ("BATT_BARS", bars),
                 ("BATT_RUN_TIME", mins), ("FREQUENCY", "578350")]
    else:  # axtd / slxd
        props = [("CHAN_NAME", name), ("TX_BATT_BARS", bars),
                 ("TX_BATT_MINS", mins), ("FREQUENCY", "0578350"),
                 ("TX_MODEL", "SLXD2" if c.on else "UNKNOWN")]
    return [f"< REP {c.n} {k} {v} >" for k, v in props]


def sample(fam: str, c: Ch) -> str:
    rf_dbm = random.randint(-62, -50) if c.on else -110
    aud = random.randint(10, 40) if c.on else 0
    if fam in ("ulxd", "qlxd"):
        return f"< SAMPLE {c.n} ALL AB {rf_dbm + 128:03d} {aud:03d} >"
    if fam == "slxd":
        return f"< SAMPLE {c.n} ALL {aud + 75:03d} {aud + 70:03d} {rf_dbm + 120:03d} >"
    # axtd
    q = 5 if c.on else 0
    r = rf_dbm + 120
    return (f"< SAMPLE {c.n} ALL {q} 00000000 {aud + 75:03d} {aud + 70:03d} "
            f"AB 00000000 {r:03d} 00000000 {r - 3:03d} >")


def serve_client(conn, fam, chans, lock):
    conn.settimeout(0.2)
    meter = {}
    last = {}
    buf = ""
    try:
        while True:
            try:
                data = conn.recv(4096)
                if not data:
                    return
                buf += data.decode()
            except socket.timeout:
                pass
            while ">" in buf:
                frame, buf = buf.split(">", 1)
                parts = frame.replace("<", "").split()
                if len(parts) < 3:
                    continue
                verb, n, prop = parts[0], int(parts[1]), parts[2]
                with lock:
                    targets = [c for c in chans if n in (0, c.n)]
                    out = []
                    for c in targets:
                        if verb == "GET":
                            out += [r for r in reports(fam, c)
                                    if prop == "ALL" or f" {prop} " in r]
                        elif verb == "SET" and prop == "METER_RATE":
                            meter[c.n] = int(parts[3]) / 1000
                            out.append(f"< REP {c.n} METER_RATE {parts[3]} >")
                conn.sendall("".join(out).encode())
            now = time.time()
            with lock:
                for c in chans:
                    # Real receivers push a REP the moment a TX powers
                    # on/off; do the same.
                    if last.get(("on", c.n), c.on) != c.on:
                        conn.sendall("".join(reports(fam, c)).encode())
                    last[("on", c.n)] = c.on
                    rate = meter.get(c.n, 0)
                    if rate and now - last.get(c.n, 0) >= rate:
                        conn.sendall(sample(fam, c).encode())
                        last[c.n] = now
    except OSError:
        return
    finally:
        conn.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=2202)
    ap.add_argument("--family", default="ulxd", choices=["ulxd", "qlxd", "slxd", "axtd"])
    ap.add_argument("--toggle", type=int, default=0,
                    help="flip ch4 on/off every N seconds (0 = never)")
    args = ap.parse_args()

    chans = [Ch(1, 5, 240), Ch(2, 3, None), Ch(3, 1, 20), Ch(4, 4, 180, on=False)]
    lock = threading.Lock()

    if args.toggle:
        def toggler():
            while True:
                time.sleep(args.toggle)
                with lock:
                    chans[3].on = not chans[3].on
                print("ch4 TX", "ON" if chans[3].on else "OFF", flush=True)
        threading.Thread(target=toggler, daemon=True).start()

    srv = socket.socket()
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind((args.host, args.port))
    srv.listen()
    print(f"fake {args.family} receiver on {args.host}:{args.port}", flush=True)
    while True:
        conn, _ = srv.accept()
        threading.Thread(target=serve_client, args=(conn, args.family, chans, lock),
                         daemon=True).start()


if __name__ == "__main__":
    main()
