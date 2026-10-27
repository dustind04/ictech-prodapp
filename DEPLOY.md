# Deploying

## Raspberry Pi — server + main TV in one box (production)

A Pi 5 hardwired to the production network AND to the main TV over
HDMI: it hosts the site for every other screen on the LAN and drives
the main TV itself in kiosk mode.

**OS:** Raspberry Pi OS **64-bit with desktop** (Bookworm), flashed
with Raspberry Pi Imager — the desktop is what runs the kiosk browser,
so don't go headless/Lite. In the Imager's settings: hostname
`ictech`, user `audio`, enable SSH, skip Wi-Fi (it's hardwired).
After first boot: `sudo raspi-config` → Boot → Desktop Autologin, and
`sudo apt install -y docker.io docker-compose-plugin chromium-browser`
(add the user to the `docker` group).

```bash
git clone https://github.com/dustind04/ictech-prodapp.git ~/ictech-prodapp
cd ~/ictech-prodapp
# copy the data/ bundle (ictech.db + photos/) in now, then:
bash scripts/pi-setup.sh     # .env + docker compose up, prints URLs
bash scripts/pi-kiosk.sh     # HDMI output -> http://localhost/ kiosk
sudo reboot
```

Give the Pi a **DHCP reservation** so `http://ictech/...` URLs on the
other TVs never move.

**Updating later (one command):** `bash scripts/pi-update.sh` — backs
up `data/`, pulls from GitHub, rebuilds, applies the newest
`seeds/inventory-*.json` if it hasn't yet, health-checks. Everything
travels through GitHub: whichever box Dave enters inventory on runs
`bash scripts/snapshot-inventory.sh` to commit it. People, slots and
headshots never go to GitHub (public repo) — Planning Center and the
Input List rebuild people on each box; headshots are per box (Admin →
Photos).

**Outside access (optional):** Zero Trust dashboard → Networks →
Tunnels → Create → Cloudflared; copy the token; add a Public Hostname
(e.g. `ictech.d2audio.io`, type HTTP, URL `ictech:8058`). Then on the
Pi: `bash scripts/pi-tunnel.sh` — it asks for the token and an admin
login (typed on the Pi, never in chat), writes `.env`, and starts the
`cloudflared` sidecar. `/admin` is Basic-Auth'd from then on; the
displays stay public by design. Roku TVs: `scripts/roku-deploy.ps1` still works
from any Windows box, or sideload per DEPLOY notes below — the
snapshotter container runs on the Pi.

## Backstage PC — Docker Desktop (production)

The real deployment: a PC on the church production network, running
Docker Desktop. The app publishes 8058 on the LAN (TVs and kiosks
browse straight to it) and sits on the same network as the gear, so
live polling (Shure, DM7, ATEM, ProPresenter, ...) runs in-process —
no collector service needed.

```powershell
git clone https://github.com/dustind04/ictech-prodapp.git
cd ictech-prodapp
copy .env.example .env    # set ICTECH_SECRET + admin credentials
powershell -ExecutionPolicy Bypass -File scripts\start-backstage.ps1
```

The launch script finds a free host port (8058, or the next available
if something already owns it), **pins it in `.env` so the TVs' URLs
never move**, stamps the build with the git commit for the in-app
update check, and prints the display URLs when it's up.

### One-time TV setup

Make the URLs permanent first, then they're typed exactly once:

1. **Rename the PC to `ictech`** (Settings → System → Rename) and give
   it a **static IP or DHCP reservation** — the two things that would
   ever break a bookmarked TV.
2. The stack serves on **port 80**, so URLs need no port number.
3. On each TV, type just: **`http://ictech/tv`** (or the IP if the name
   doesn't resolve: `http://<pc-ip>/tv`). Big buttons come up — tap the
   one that matches the screen, then set it as the browser home page /
   bookmark. Done forever.

### Roku TVs — the icTech channel

Rokus have no browser, so they get a native channel that shows live
JPEG snapshots of the displays (rendered by the `snapshotter` container
every 4s at 1080p).

One-time per TV (~2 min): enable Developer Mode — press Home ×3,
Up ×2, Right, Left, Right, Left, Right — set a dev password, accept
the agreement, note the TV's IP. Then from the backstage PC:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\roku-deploy.ps1 -Password <devpass>
```

The script bakes this PC's address into the channel, finds every Roku
on the LAN, and installs/updates the **icTech** channel tile on each.
First launch on a TV asks "WHICH DISPLAY IS THIS?" — pick with the
remote; the choice sticks forever (press `*` to change it). Re-run the
same script any time to push channel updates to all TVs at once.

Cheat sheet of the short URLs:

| Display | URL |
|---|---|
| Setup picker | `http://ictech/tv` |
| Dashboard (main wall) | `http://ictech/` |
| Simple Micboard | `http://ictech/mb` |
| Tech dashboard | `http://ictech/tech` |

(`/micboard`, `/techdashboard`, and `:8058` also always work.)
- **Updates**: the Admin page checks GitHub hourly and shows a banner
  when a newer version exists; run `scripts\update.ps1` to pull and
  relaunch (data and port are untouched).
- Boot survival: set Docker Desktop to "Start when you sign in" and
  keep the PC auto-logging in; `restart: unless-stopped` handles the
  containers from there.
- Outside access is optional here: add `TUNNEL_TOKEN` to `.env` and
  start with `--profile tunnel` to run the Cloudflare tunnel too.

**Migrating data from the demo box:** copy the demo's `data/` directory
(SQLite DB + photos) into the clone before first start — or restore a
snapshot: `docker exec -i ictech python3 tools/restore_snapshot.py < snapshot.json`.

## Live receiver monitoring (battery / RF / TX on-off)

The app polls the Shure receivers itself (`shure_live.py`, a thread
inside the one gunicorn worker) — no separate micboard install. Each
wall tile's bottom LIVE row then shows battery bars + time left, RF
bars, and a **TX ON / TX OFF** chip; problems say so in words
(**Low**, **Replace**, **RX error**), not just color. TX OFF is quiet
gray while packs sit in the chargers and turns pulsing red from
20 min before a service/rehearsal until it ends. `/techdashboard`
shows the same per channel (dBm, audio %), and Admin → Channels has a
Live column.

Supported (protocol on TCP/UDP 2202): **ULX-D, QLX-D, Axient Digital
(AD4D/AD4Q), SLX-D and SLX-D+, UHF-R**, plus **PSM 1000** (P10T,
online/offline only). PSM 900, GLX-D, BLX and the analog lines have
no network control — those channels just stay dormant.

Install-day checklist:

1. Receivers on the **same network/VLAN as the Pi**, each with a
   static IP or DHCP reservation (ULX-D Q / AD4Q: the *control* port's
   IP, from the front-panel Network menu — not the Dante address).
2. **SLX-D / SLX-D+ only:** third-party control is **off by default**
   on the receiver — turn it on in the receiver's network menu.
   ULX-D/QLX-D/Axient need nothing.
3. Admin → Channels, per mic: **Receiver** (e.g. ULXD4Q), **Receiver
   IP**, **Receiver ch #** (1–4). If you leave ch # blank it matches
   the WWB channel name typed in "Channel name" against what the
   receiver reports.
4. Power a pack on. Within ~15 s its Live column says OK and the wall
   tile flips to TX ON. A receiver that can't be reached shows
   **RX error**; a reachable receiver whose name didn't match shows
   **Check ch #**.

No rack handy? `python tools/fake_shure.py` (then a channel at
`127.0.0.1`, ULXD4Q, ch 1–4) fakes a quad with one of each state.
Thresholds (Low/Replace bars and minutes) are constants at the top of
`shure_live.py`. Set `ICTECH_LIVE=0` to turn polling off — receivers and console —
e.g. on the internet-facing Debian box, which can't reach the rack.

## Debian box (internet-facing demo via Cloudflare tunnel)

Target: any Debian/ARM64/x86 box with Docker + compose. The stack is two
containers: the Flask app (gunicorn, port 8058, localhost-only) and a
`cloudflared` sidecar that carries all public traffic. Nothing is exposed
on the box's public interface.

## One-time setup

### 1. Create the tunnel (Cloudflare dashboard, ~2 minutes)

1. [Zero Trust dashboard](https://one.dash.cloudflare.com/) → **Networks → Tunnels → Create a tunnel** → connector type **Cloudflared**.
2. Name it (e.g. `ictech`). Copy the **token** from the install command — the long string after `--token`.
3. Add a **Public Hostname**: pick the subdomain/domain you want (e.g. `micboard.example.com`), service type **HTTP**, URL **`ictech:8058`**.

### 2. Bootstrap the box

```bash
git clone https://github.com/dustind04/ictech-prodapp.git ~/ictech-prodapp
cd ~/ictech-prodapp
cp .env.example .env
nano .env        # paste TUNNEL_TOKEN, set ICTECH_SECRET + admin credentials
docker compose -f docker-compose.prod.yaml up -d --build
```

Verify on the box: `curl -s localhost:8058/api/state | head -c 200`
Then hit the public hostname from anywhere.

## Updating

```bash
cd ~/ictech-prodapp
git pull
docker compose -f docker-compose.prod.yaml up -d --build
```

## Data & backups — the inventory must never be lost

Three layers:

1. **Nightly tarball on the box** (DB + photos). Cron keeps a rolling week
   by weekday name:

   ```
   15 3 * * * cd ~/ictech-prodapp && mkdir -p ~/backups/ictech && tar czf ~/backups/ictech/data-$(date +\%a).tgz data/
   ```

2. **JSON snapshot in git.** `GET /admin/export.json` (behind admin auth)
   dumps every operator-entered table. Snapshots live in `seeds/` in this
   repo — but **this repo is public, so committed snapshots must exclude
   the `person` and `slot` tables** (people's names don't belong in a
   public repo; the box tarball covers them). **After any big data-entry
   session (e.g. the one-time inventory fill), snapshot the inventory
   tables and commit:**

   ```bash
   bash scripts/snapshot-inventory.sh   # export, strip person/slot, commit, push
   ```

   (Push auth: `gh auth login` + `gh auth setup-git` once on the box.)
   Restoring a snapshot without person/slot keeps the target box's
   people; slot links to gear that no longer exists are cleared.

   (If the repo ever goes private, full snapshots are fine.)

3. **Restore path:** `tools/restore_snapshot.py` (ships in the image)
   reloads a snapshot into a fresh or existing DB:

   ```bash
   docker exec -i ictech python3 tools/restore_snapshot.py < seeds/snapshot-YYYY-MM-DD.json
   ```

## Weekly Input List import

Admin → **Weekly import** → upload Dave's `<date> Input List.xlsx` →
preview (person/mic/IEM/position/MyMix per slot, with warnings for
anything that didn't match inventory) → **Apply to slots**. The sheet is
the weekly truth: slots with no row that week are emptied.

## FOH console link (Yamaha DM7, read-only)

`dm7_live.py` holds one connection to the DM7's remote-control port
(TCP 49280) and only ever *reads* — it refuses to send anything that
could change the board. What shows up:

- **Wall tiles:** `FOH ON / FOH OFF` (is this person's channel up at
  the board) next to `TX ON/OFF`, plus a small input meter that flashes
  red on clip. A band seat folds all its inputs (the whole kit) into
  one. On the MyMix row (their station), a dot lights when *their own
  feed into MyMix* — the matrix or direct out carrying them — is up
  with signal; `FEED OFF` if that matrix is muted. Ears themselves
  are mixed on the station, which the console can't see.
- **Wall header:** current scene number + name.
- **`/techdashboard` → FOH CONSOLE:** each input from the week's Input
  List next to what the board says (name, on, preamp gain, level), ⚠
  when the sheet and the board disagree on the name. **MYMIX FEEDS:**
  the 16 MyMix inputs from the week's legend — what feeds each (Mtx n /
  Dir Out), on/off and level at the DM7, and what's inside each matrix.

Setup: Admin → Channels → **FOH console IP** (the DM7's network IP,
same VLAN as the Pi). Within ~15 s it shows Online with the scene.

How tiles find their console channel: through that week's Input List
(FOH ch column) — by the slot's mic ("Red HH"), else its MyMix name.
No Input List imported = no FOH chips. MyMix feeds come from the MyMix
sheet: the legend's Source column (`Mtx 2`, `Dir Out`) and each
input's MyMix # / route (columns H/I).

Not verified on a real DM7 yet: the +48V read (column shows the
sheet's `(X)` until the console answers it), and how many remote
connections the DM7 allows next to DM7 Editor / StageMix / Companion.
No console handy? `python tools/fake_dm7.py` and set the IP to
`127.0.0.1`.

## Planning Center link (replaces the Tech Report PDF)

Crew seats, band seats, weekly roles and the music leader come straight
from Planning Center Services — same matching rules as the PDF import
(first name + last initial; unknown names are added, likely typos warn).
The Input List `.xlsx` is still Dave's: patch, MyMix and the vocal
rack slots aren't in Planning Center.

1. Signed in to Planning Center as someone who can see Services:
   <https://api.planningcenteronline.com/oauth/applications> →
   **Personal Access Tokens** → New. Copy the Application ID + Secret.
   (The token sees what that person sees — a read-mostly staff login
   is ideal.)
2. On the server: `bash scripts/pco-setup.sh` — asks for both (hidden),
   writes `.env`, recreates the app. Works on the Debian box and the Pi.
3. Admin → Import → **Planning Center**: pick the service type, check
   the teams to pull (defaults to tech/band/vocals/leader/speaker/host;
   greeters etc. are ignored), **Preview** → **Apply**.
4. Tick **Auto-sync**: every 10 min it re-reads this week's plan and
   re-applies only when the plan changed (or after the Sunday 1 PM
   clear) — hand edits on the Slots page stand until Planning Center
   says something new. It never applies from 20 min before a
   service/rehearsal until it ends. Last result shows on the Import
   page. `ICTECH_PCO_AUTOSYNC=0` disables the thread entirely.

"This week" = the first plan dated on/after the wall's service Sunday
(rolls over Sunday 12:30 PM). Declined people are skipped.

## Security posture

- `/admin` is protected by HTTP Basic Auth **only when** `ICTECH_ADMIN_USER`
  and `ICTECH_ADMIN_PASSWORD` are set in `.env`. Always set them for an
  internet-facing deployment.
- The wall display (`/`) and `/api/state` are public by design. They show
  first names, positions, and photos. If that should be gated too, put
  Cloudflare Access (Zero Trust → Access → Applications) in front of the
  hostname — no app changes needed.
- Port 8058 binds to `127.0.0.1` only; the tunnel is the sole public path.

## Relationship to the Pi deployment

The original production target (Raspberry Pi `micboard`, kiosk mode on the
backstage VLAN) is unchanged and can use the plain `docker-compose.yaml`,
which exposes 8058 on the LAN with no tunnel and no auth.
