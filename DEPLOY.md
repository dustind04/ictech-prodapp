# Deploying to the Debian box (internet-facing via Cloudflare tunnel)

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

## Data & backups

SQLite DB and uploaded photos live in `./data/` on the host (mounted at
`/data` in the container). Back up by copying that directory; it is small.
A cron line like this keeps 14 daily snapshots:

```
15 3 * * * cd ~/ictech-prodapp && tar czf ~/backups/ictech-$(date +\%a).tgz data/
```

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
