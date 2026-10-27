"""
Fake Yamaha DM7 — exercise the console link without Pete's board.

Speaks the read side of RCP on TCP 49280 the way dm7_live.py uses it:
devinfo, get (names / colors / on / HA gain / sends), mtrstart meter
streams (auto-stop after 10 s like the real console), scpmode,
sscurrentt_ex / ssinfot_ex. Anything else — including every `set` —
gets ERROR and is printed, so a test can prove the app never writes.

  python tools/fake_dm7.py                    # 127.0.0.1:49280
  python tools/fake_dm7.py --toggle 20        # ch 3 flips on/off every 20 s

Then Admin → Channels → FOH console IP = 127.0.0.1.
"""

from __future__ import annotations

import argparse
import random
import socket
import threading
import time

IN_NAMES = {1: "Chris Vx", 2: "Becky Vx", 3: "Kiara Vx", 4: "Joanna", 5: "Kick",
            6: "Snare", 7: "OH L", 8: "OH R", 9: "Bass", 10: "Keys", 11: "Orng RF",
            12: "Click"}
MIX_NAMES = {1: "IEM 1", 2: "IEM 2", 3: "IEM 3", 4: "IEM 4", 5: "Drum IEM",
             9: "Lobby", 10: "Stream"}
STATE = {"on": {i: 1 for i in IN_NAMES}, "lock": threading.Lock(), "clients": []}
STATE["on"][4] = 0          # Joanna's channel off at FOH


def value(addr: str, x: int, y: int):
    ch = x + 1
    if addr.endswith("InCh/Label/Name"):
        return f'"{IN_NAMES.get(ch, "")}"'
    if addr.endswith("InCh/Label/Color"):
        return '"Blue"' if ch in IN_NAMES else '"Off"'
    if addr.endswith("InCh/Fader/On"):
        return str(STATE["on"].get(ch, 0))
    if addr.endswith("InCh/Port/HA/Gain"):
        return str(30 if ch in IN_NAMES else 0)
    if addr.endswith("Mix/Label/Name"):
        return f'"{MIX_NAMES.get(ch, "")}"'
    if addr.endswith("Mix/Fader/On"):
        return "1"
    if addr.endswith("InCh/ToMix/On"):
        return "1" if (ch == y + 1 or ch == 12 or (y == 4 and ch in (5, 6, 9))) else "0"
    if addr.endswith("InCh/ToMix/Level"):
        return "0" if ch == y + 1 else "-600" if ch == 12 else "-1000"
    return None


def serve(conn: socket.socket, args):
    meters: dict[str, float] = {}
    buf = ""
    conn.settimeout(0.05)
    STATE["clients"].append(conn)
    try:
        while True:
            try:
                data = conn.recv(65536)
                if not data:
                    return
                buf += data.decode()
            except socket.timeout:
                pass
            out = []
            while "\n" in buf:
                line, buf = buf.split("\n", 1)
                t = line.split()
                if not t:
                    continue
                verb = t[0]
                if verb == "devinfo":
                    out.append(f'OK devinfo {t[1]} "{"DM7" if t[1] == "productname" else "FOH"}"')
                elif verb == "get":
                    v = value(t[1], int(t[2]), int(t[3]))
                    out.append(f"OK get {t[1]} {t[2]} {t[3]} {v}" if v is not None
                               else f"ERROR get {t[1]} UnknownAddress")
                elif verb == "mtrstart":
                    meters[t[1]] = time.time() + 10
                    out.append(f"OK mtrstart {t[1]} {t[2]}")
                elif verb == "mtrstop":
                    meters.pop(t[1], None)
                elif verb == "scpmode":
                    out.append('OK scpmode sstype "text"')
                elif verb == "sscurrentt_ex":
                    out.append(f'OK sscurrentt_ex {t[1]} "12.00"' if t[1] == "scene_a"
                               else f"ERROR sscurrentt_ex {t[1]} InvalidArgument")
                elif verb == "ssinfot_ex":
                    out.append(f'OK ssinfot_ex {t[1]} "12.00" "Worship Set" "Week 9"')
                else:
                    print("REFUSED (non-read):", line, flush=True)
                    out.append(f"ERROR {verb} AccessDenied")
            now = time.time()
            for addr, until in list(meters.items()):
                if now > until:
                    del meters[addr]
                    continue
                n = 72 if "InCh" in addr else 48
                vals = []
                for i in range(n):
                    live = (i + 1) in (IN_NAMES if "InCh" in addr else MIX_NAMES)
                    vals.append(random.randint(120, 200) if live else 0)
                out.append(f"NOTIFY mtr {addr} levelwt " + " ".join(f"{v:02x}" for v in vals))
            if out:
                conn.sendall(("\n".join(out) + "\n").encode())
            time.sleep(0.2)
    except OSError:
        return
    finally:
        STATE["clients"].remove(conn)
        conn.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=49280)
    ap.add_argument("--toggle", type=int, default=0, help="flip ch 3 on/off every N s")
    args = ap.parse_args()

    if args.toggle:
        def toggler():
            while True:
                time.sleep(args.toggle)
                STATE["on"][3] ^= 1
                v = STATE["on"][3]
                msg = f"NOTIFY set MIXER:Current/InCh/Fader/On 2 0 {v} {v}\n".encode()
                for c in list(STATE["clients"]):
                    try:
                        c.sendall(msg)
                    except OSError:
                        pass
                print("ch3", "ON" if v else "OFF", flush=True)
        threading.Thread(target=toggler, daemon=True).start()

    srv = socket.socket()
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind((args.host, args.port))
    srv.listen()
    print(f"fake DM7 on {args.host}:{args.port}", flush=True)
    while True:
        conn, _ = srv.accept()
        threading.Thread(target=serve, args=(conn, args), daemon=True).start()


if __name__ == "__main__":
    main()
