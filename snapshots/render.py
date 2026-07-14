"""
Snapshot renderer for the Roku channel.

Runs in the Playwright sidecar container: keeps the three display pages
open in headless Chromium (they poll their own data, so they stay
current on their own) and writes a fresh 1920x1080 JPEG of each every
few seconds. The app serves them at /snapshot/<name>.jpg and the Roku
channel just flips images. Writes are atomic (tmp + rename) so a Roku
never fetches a half-written file.
"""

import os
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = os.environ.get("SNAP_BASE", "http://ictech:8058")
OUT = Path(os.environ.get("SNAP_DIR", "/data/snapshots"))
INTERVAL = float(os.environ.get("SNAP_INTERVAL", "4"))
RELOAD_CYCLES = 150            # full page reload ~10 min: picks up deploys
VIEWS = [("dashboard", "/"), ("mb", "/micboard"), ("tech", "/techdashboard")]

OUT.mkdir(parents=True, exist_ok=True)


def open_page(browser, pages, name, path):
    pg = pages.get(name)
    if pg is None or pg.is_closed():
        pg = browser.new_page(viewport={"width": 1920, "height": 1080})
        pages[name] = pg
    # NOT networkidle: the displays poll /api/state every 2s, so the
    # network never goes idle. Load + a settle beat is enough.
    pg.goto(BASE + path, wait_until="load", timeout=30000)
    pg.wait_for_timeout(3000)
    return pg


def main():
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        pages = {}
        for name, path in VIEWS:
            open_page(browser, pages, name, path)
        print("snapshotter up:", BASE, "->", OUT, flush=True)
        cycle = 0
        while True:
            for name, path in VIEWS:
                try:
                    tmp = OUT / f".{name}.tmp.jpg"
                    pages[name].screenshot(path=str(tmp), type="jpeg", quality=80)
                    tmp.replace(OUT / f"{name}.jpg")
                except Exception as exc:
                    print(f"snapshot failed for {name}: {exc}", flush=True)
                    try:
                        open_page(browser, pages, name, path)
                    except Exception as exc2:
                        print(f"reopen failed for {name}: {exc2}", flush=True)
            cycle += 1
            if cycle % RELOAD_CYCLES == 0:
                for name, path in VIEWS:
                    try:
                        open_page(browser, pages, name, path)
                    except Exception as exc:
                        print(f"reload failed for {name}: {exc}", flush=True)
            time.sleep(INTERVAL)


if __name__ == "__main__":
    main()
