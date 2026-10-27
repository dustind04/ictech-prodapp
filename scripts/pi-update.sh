#!/usr/bin/env bash
# Bring this Pi fully up to date in one go. Run ON the Pi:
#
#   bash scripts/pi-update.sh
#
# Everything comes from GitHub — nothing is pulled from another box.
# 1. Backs up the Pi's current data (data/backups/, never deleted).
# 2. Pulls the latest code + inventory for the checked-out branch.
# 3. Rebuilds + restarts the backstage stack (migrations run on boot).
# 4. Restores the newest seeds/inventory-*.json (channels, positions,
#    assets, gear) if this Pi hasn't applied it yet. People and slots
#    aren't in git (public repo) — the Pi's own stay, and Planning
#    Center + the Input List import fill them in. Committed from the
#    data-entry box with: bash scripts/snapshot-inventory.sh
# 5. Health check + what's left to plug in.
set -euo pipefail
cd "$(dirname "$0")/.."

FORCE=0
[ "${1:-}" = "--force-inventory" ] && FORCE=1   # re-apply even if seen

STAMP=$(date +%Y%m%d-%H%M%S)
mkdir -p data/backups data/photos

# --- 1. backup ---------------------------------------------------
if [ -f data/ictech.db ]; then
    cp data/ictech.db "data/backups/ictech-$STAMP.db"
    echo "Backed up current DB → data/backups/ictech-$STAMP.db"
fi

# --- 2. code -----------------------------------------------------
BRANCH=$(git rev-parse --abbrev-ref HEAD)
git pull --ff-only origin "$BRANCH"
GIT_SHA=$(git rev-parse --short HEAD)
export GIT_SHA
echo "Code: $BRANCH @ $GIT_SHA"

if [ ! -f .env ]; then                               # first run: .env + secret
    cp .env.example .env
    sed -i "s/^ICTECH_SECRET=$/ICTECH_SECRET=$(python3 -c 'import secrets; print(secrets.token_hex(32))')/" .env
fi

# --- 3. rebuild --------------------------------------------------
docker compose -f docker-compose.backstage.yaml up -d --build
echo -n "Waiting for the app"
for _ in $(seq 1 60); do
    if curl -fs -o /dev/null http://localhost:8058/api/state; then echo " — up."; break; fi
    echo -n "."; sleep 2
done
curl -fs -o /dev/null http://localhost:8058/api/state || { echo; echo "App didn't come up: docker logs ictech"; exit 1; }

# --- 4. inventory from git --------------------------------------
INV=$(ls -1 seeds/inventory-*.json 2>/dev/null | sort | tail -1 || true)
if [ -n "$INV" ]; then
    SUM=$(sha256sum "$INV" | cut -c1-16)
    MARK=data/.inventory-applied
    if [ "$FORCE" = 1 ] || [ "$(cat "$MARK" 2>/dev/null)" != "$INV $SUM" ]; then
        echo "Restoring inventory from $INV"
        docker exec -i ictech python3 tools/restore_snapshot.py < "$INV"
        echo "$INV $SUM" > "$MARK"
    else
        echo "Inventory: $INV already applied."
    fi
fi

# --- 5. health + checklist ---------------------------------------
HOST=$(hostname); IP=$(hostname -I | awk '{print $1}')
python3 - <<EOF
import json, urllib.request
def get(u):
    try: return json.load(urllib.request.urlopen("http://localhost:8058" + u, timeout=5))
    except Exception as e: return {"_err": str(e)}
live, con, st = get("/api/live"), get("/api/console"), get("/api/state")
rx = live.get("receivers", [])
print()
print("Status")
print(f"  Build:      {st.get('version')}")
print(f"  People on the wall this week: {sum(1 for s in st.get('slots', []) if s.get('person_id'))}")
print(f"  Receivers:  {sum(r['online'] for r in rx)}/{len(rx)} online" if rx else
      "  Receivers:  none configured (Admin → Channels: receiver + IP + ch #)")
c = con.get("console", {})
print("  DM7:        " + ("online" if c.get("online") else "configured, OFFLINE" if c.get("configured")
                          else "not set (Admin → Channels → FOH console IP)"))
EOF
grep -q '^ICTECH_PCO_APP_ID=.\+' .env \
    && echo "  Planning Center: token present (pick service type in Admin → Import)" \
    || echo "  Planning Center: not linked — run: bash scripts/pco-setup.sh"
echo
echo "Displays: http://$HOST/tv   (or http://$IP/tv)   Admin: http://$HOST/admin"
