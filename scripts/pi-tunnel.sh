#!/usr/bin/env bash
# Publish this Pi's icTech to the internet through a Cloudflare tunnel.
# Run ON the Pi, after creating the tunnel in the Zero Trust dashboard:
#
#   bash scripts/pi-tunnel.sh
#
# Prompts for the tunnel token and admin credentials (typed here, never
# echoed, never leave the box), writes them to .env, recreates the app
# so Basic Auth on /admin takes effect, and starts the cloudflared
# sidecar. Re-run any time to rotate the token or the password.
set -euo pipefail
cd "$(dirname "$0")/.."
[ -f .env ] || cp .env.example .env

set_env() {  # set_env KEY VALUE — replace or append in .env
    if grep -q "^$1=" .env; then
        sed -i "s|^$1=.*|$1=$2|" .env
    else
        printf '%s=%s\n' "$1" "$2" >> .env
    fi
}

echo "Cloudflare tunnel token (from the dashboard's install command, the"
echo "long string after --token). Input is hidden:"
read -rs TOKEN; echo
[ -n "$TOKEN" ] || { echo "No token given; nothing changed."; exit 1; }

echo
echo "/admin becomes reachable from the internet, so it needs a login."
read -rp "Admin username: " ADMIN_USER
read -rsp "Admin password (hidden): " ADMIN_PASS; echo
[ -n "$ADMIN_USER" ] && [ -n "$ADMIN_PASS" ] || { echo "Admin login required for a public tunnel."; exit 1; }

set_env TUNNEL_TOKEN "$TOKEN"
set_env ICTECH_ADMIN_USER "$ADMIN_USER"
set_env ICTECH_ADMIN_PASSWORD "$ADMIN_PASS"
chmod 600 .env

GIT_SHA=$(git rev-parse --short HEAD 2>/dev/null || echo unknown)
export GIT_SHA
docker compose -f docker-compose.backstage.yaml -f docker-compose.pi.yaml --profile tunnel up -d
sleep 4
echo
echo "Tunnel log (look for 'Registered tunnel connection'):"
docker logs --tail 8 ictech_tunnel 2>&1 | sed 's/^/  /'
echo
echo "Done. Your public hostname is whatever you mapped in the dashboard"
echo "(service http://ictech:8058). /admin now asks for $ADMIN_USER's login,"
echo "on the LAN too. Displays stay open."
