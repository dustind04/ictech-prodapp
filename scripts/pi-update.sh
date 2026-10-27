#!/usr/bin/env bash
# Bring this Pi fully up to date in one go. Run ON the Pi:
#
#   bash scripts/pi-update.sh                         # code only
#   bash scripts/pi-update.sh --from https://<debian-host>
#                                                     # + Dave's inventory
#
# 1. Backs up the Pi's current data (data/backups/, never deleted).
# 2. Pulls the latest code for the checked-out branch.
# 3. Rebuilds + restarts the backstage stack (migrations run on boot).
# 4. --from: downloads /admin/export.json and every headshot from the
#    Debian box (asks for its admin login, hidden) and restores them —
#    the Debian copy REPLACES people, channels, positions, slots and
#    assets here. Gear catalogs merge.
# 5. Health check + what's left to plug in.
set -euo pipefail
cd "$(dirname "$0")/.."

FROM=""
while [ $# -gt 0 ]; do
    case "$1" in
        --from) FROM="${2%/}"; shift 2 ;;
        *) echo "Unknown option: $1"; exit 1 ;;
    esac
done

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

# --- 4. inventory from the Debian box ----------------------------
if [ -n "$FROM" ]; then
    read -rp "Admin username on $FROM: " U
    read -rsp "Admin password (hidden): " P; echo
    SNAP="data/backups/debian-$STAMP.json"
    curl -fsS -u "$U:$P" "$FROM/admin/export.json" -o "$SNAP" \
        || { echo "Couldn't download $FROM/admin/export.json (login? hostname?)"; exit 1; }
    echo "Downloaded inventory → $SNAP"

    # Headshots aren't in the JSON — fetch each managed photo by name.
    python3 - "$SNAP" <<'EOF' > data/backups/photos-$STAMP.txt
import json, sys
for p in json.load(open(sys.argv[1])).get("person", []):
    u = p.get("photo_url") or ""
    if u.startswith("/photos/"):
        print(u[len("/photos/"):])
EOF
    N=0
    while read -r f; do
        [ -n "$f" ] || continue
        curl -fsS -u "$U:$P" "$FROM/photos/$f" -o "data/photos/$f" && N=$((N+1)) \
            || echo "  photo missing on server: $f"
    done < "data/backups/photos-$STAMP.txt"
    echo "Photos: $N downloaded"

    docker exec -i ictech python3 tools/restore_snapshot.py < "$SNAP"
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
