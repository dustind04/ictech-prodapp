# Deploying

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

- Displays: point each TV/kiosk browser at the printed URLs
  (`http://<pc-ip>:<port>/`, `/micboard`, `/techdashboard`). F11.
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
   curl -su admin:PASS localhost:8058/admin/export.json \
     | python3 -c 'import json,sys; d=json.load(sys.stdin); [d.pop(k,None) for k in ("person","slot")]; json.dump(d, sys.stdout, indent=1, sort_keys=True)' \
     > seeds/inventory-$(date +%F).json
   git add seeds/ && git commit -m "Inventory snapshot $(date +%F)" && git push
   ```

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
