#!/usr/bin/env bash
# Link this server to Planning Center Services (replaces the weekly
# Tech Report PDF). Run ON the server (Pi or Debian box):
#
#   bash scripts/pco-setup.sh
#
# First make a Personal Access Token: signed in to Planning Center,
# https://api.planningcenteronline.com/oauth/applications → Personal
# Access Tokens → New. Paste its Application ID and Secret here
# (hidden; they never leave this box), then pick the service type in
# Admin → Import. Re-run to rotate the token.
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

read -rsp "Planning Center Application ID (hidden): " APP_ID; echo
read -rsp "Planning Center Secret (hidden): " SECRET; echo
[ -n "$APP_ID" ] && [ -n "$SECRET" ] || { echo "Both are required; nothing changed."; exit 1; }

set_env ICTECH_PCO_APP_ID "$APP_ID"
set_env ICTECH_PCO_SECRET "$SECRET"
chmod 600 .env

# Recreate the app on whichever stack this box already runs (Debian:
# prod; Pi / backstage PC: backstage) so it picks up the new env.
CFG=$(docker inspect ictech --format '{{index .Config.Labels "com.docker.compose.project.config_files"}}' 2>/dev/null || true)
# Match the compose FILE names — the checkout folder itself is called
# ictech-prodapp, so a bare *prod* matched every box.
case "$CFG" in
    *docker-compose.pi.yaml*)   COMPOSE=(-f docker-compose.backstage.yaml -f docker-compose.pi.yaml) ;;
    *docker-compose.prod.yaml*) COMPOSE=(-f docker-compose.prod.yaml) ;;
    *)                          COMPOSE=(-f docker-compose.backstage.yaml) ;;
esac
# A Raspberry Pi always runs the Pi stack, whatever is running now.
grep -qi raspberry /proc/device-tree/model 2>/dev/null \
    && COMPOSE=(-f docker-compose.backstage.yaml -f docker-compose.pi.yaml)
GIT_SHA=$(git rev-parse --short HEAD 2>/dev/null || echo unknown)
export GIT_SHA
docker compose "${COMPOSE[@]}" up -d ictech
echo
echo "Linked. Admin → Import → Planning Center: pick the service type,"
echo "check the teams, Preview, Apply — and tick Auto-sync to keep it current."
