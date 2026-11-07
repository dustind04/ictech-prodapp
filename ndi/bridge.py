"""
NDI → browser bridge for the dashboards.

Browsers can't play NDI, so this sidecar receives NDI sources on the
production network and re-serves them as MJPEG, which any <img> tag
shows with ~0.2 s of delay. Read-only: it never sends NDI.

  GET /sources                      → ["BOOTH (ProPresenter)", ...]
  GET /stream?src=<name>&q=low|high → multipart MJPEG
  GET /snapshot?src=<name>&q=...    → one JPEG
  GET /health

A source is only received while someone is watching it (plus 30 s),
so idle sources cost nothing. q=low asks the sender for NDI's preview
stream (small, cheap to decode — right for a dashboard tile); q=high
is the full stream, scaled to at most 1280 px wide.

Needs host networking (NDI discovery is mDNS). Sources on another
subnet than the Pi (mDNS doesn't cross VLANs): list their machines'
IPs in NDI_EXTRA_IPS, comma-separated. Port: NDI_BRIDGE_PORT (8060).
"""

from __future__ import annotations

import io
import json
import logging
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import NDIlib as ndi
import numpy as np
from PIL import Image

log = logging.getLogger("ndi-bridge")
PORT = int(os.environ.get("NDI_BRIDGE_PORT", "8060"))
IDLE_STOP = 30          # s without viewers before a receiver is closed
MAX_W = {"low": 640, "high": 1280}
FPS = {"low": 12, "high": 20}
JPEG_Q = 72


class Finder:
    """Keeps the list of NDI sources on the network current."""

    def __init__(self):
        self.lock = threading.Lock()
        self.sources: dict[str, object] = {}
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self):
        fc = ndi.FindCreate()
        fc.show_local_sources = True
        extra = os.environ.get("NDI_EXTRA_IPS", "").strip()
        if extra:
            fc.extra_ips = extra
        f = ndi.find_create_v2(fc)
        while True:
            ndi.find_wait_for_sources(f, 2000)
            found = {s.ndi_name: s for s in ndi.find_get_current_sources(f)}
            with self.lock:
                self.sources = found

    def names(self) -> list[str]:
        with self.lock:
            return sorted(self.sources)

    def get(self, name: str):
        with self.lock:
            return self.sources.get(name)


class Receiver:
    """One NDI source at one quality; latest frame as JPEG."""

    def __init__(self, src_name: str, quality: str, finder: Finder):
        self.name, self.q, self.finder = src_name, quality, finder
        self.cond = threading.Condition()
        self.jpeg: bytes | None = None
        self.seq = 0
        self.last_wanted = time.time()
        self.alive = True
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self):
        rc = ndi.RecvCreateV3()
        rc.color_format = ndi.RECV_COLOR_FORMAT_BGRX_BGRA
        rc.bandwidth = ndi.RECV_BANDWIDTH_LOWEST if self.q == "low" else ndi.RECV_BANDWIDTH_HIGHEST
        recv = ndi.recv_create_v3(rc)
        connected, last_enc = False, 0.0
        try:
            while self.alive and time.time() - self.last_wanted < IDLE_STOP:
                if not connected:
                    src = self.finder.get(self.name)
                    if src is None:
                        time.sleep(1)
                        continue
                    ndi.recv_connect(recv, src)
                    connected = True
                    log.info("receiving %s (%s)", self.name, self.q)
                t, v, a, m = ndi.recv_capture_v2(recv, 1000)
                if t == ndi.FRAME_TYPE_VIDEO:
                    now = time.time()
                    if now - last_enc >= 1 / FPS[self.q]:     # don't encode faster than shown
                        self._encode(v.data)
                        last_enc = now
                    ndi.recv_free_video_v2(recv, v)
                elif t == ndi.FRAME_TYPE_AUDIO:
                    ndi.recv_free_audio_v2(recv, a)
                elif t == ndi.FRAME_TYPE_METADATA:
                    ndi.recv_free_metadata(recv, m)
        finally:
            ndi.recv_destroy(recv)
            self.alive = False
            log.info("stopped %s (%s)", self.name, self.q)

    def _encode(self, data):
        img = Image.fromarray(np.ascontiguousarray(data[:, :, :3][:, :, ::-1]))   # BGRX → RGB
        if img.width > MAX_W[self.q]:
            img = img.resize((MAX_W[self.q], round(img.height * MAX_W[self.q] / img.width)))
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=JPEG_Q)
        with self.cond:
            self.jpeg = buf.getvalue()
            self.seq += 1
            self.cond.notify_all()

    def wait_frame(self, after_seq: int, timeout: float = 5.0):
        self.last_wanted = time.time()
        with self.cond:
            self.cond.wait_for(lambda: (self.jpeg is not None and self.seq != after_seq)
                               or not self.alive, timeout)
            return self.seq, self.jpeg


FINDER = None
RECEIVERS: dict[tuple, Receiver] = {}
RLOCK = threading.Lock()


def receiver(name: str, q: str) -> Receiver:
    with RLOCK:
        r = RECEIVERS.get((name, q))
        if r is None or not r.alive:
            r = RECEIVERS[(name, q)] = Receiver(name, q, FINDER)
        r.last_wanted = time.time()
        return r


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    def _params(self):
        q = parse_qs(urlparse(self.path).query)
        src = (q.get("src") or [""])[0]
        qual = (q.get("q") or ["low"])[0]
        return src, qual if qual in MAX_W else "low"

    def _send(self, code, body: bytes, ctype: str):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/health":
            return self._send(200, b"ok", "text/plain")
        if path == "/sources":
            return self._send(200, json.dumps(FINDER.names()).encode(), "application/json")
        src, q = self._params()
        if not src:
            return self._send(400, b"src= is required", "text/plain")
        r = receiver(src, q)
        if path == "/snapshot":
            _, jpg = r.wait_frame(-1, 6)            # latest frame, or the first one
            return self._send(200, jpg, "image/jpeg") if jpg else \
                self._send(503, b"no video from that source yet", "text/plain")
        if path == "/stream":
            self.send_response(200)
            self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            seq = -1
            try:
                while True:
                    r = receiver(src, q)               # revives after an idle stop
                    new_seq, jpg = r.wait_frame(seq)
                    if not jpg or new_seq == seq:
                        continue                       # timed out (source gone); keep waiting
                    seq = new_seq
                    self.wfile.write(b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: "
                                     + str(len(jpg)).encode() + b"\r\n\r\n" + jpg + b"\r\n")
            except (BrokenPipeError, ConnectionResetError):
                return
        self._send(404, b"not found", "text/plain")


def main():
    global FINDER
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    if not ndi.initialize():
        raise SystemExit("NDI runtime failed to initialize (unsupported CPU?)")
    FINDER = Finder()
    srv = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    srv.daemon_threads = True
    log.info("NDI bridge on :%d", PORT)
    srv.serve_forever()


if __name__ == "__main__":
    main()
