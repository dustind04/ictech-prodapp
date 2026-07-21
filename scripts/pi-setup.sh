#!/usr/bin/env bash
# icTech on a Raspberry Pi — one-shot bootstrap. Run ON the Pi:
#
#   bash scripts/pi-setup.sh
#
# Brings up the backstage stack (app on :80 + :8058, snapshotter for
# the Roku channel) with Docker Compose. Data lives in ./data — copy a
# data/ bundle (ictech.db + photos/) in BEFORE first start, or restore
# a snapshot afterwards:
#   docker exec -i ictech python3 tools/restore_snapshot.py < snapshot.json
set -euo pipefail
cd "$(dirname "$0")/.."

command -v docker >/dev/null || { echo "Docker is not installed."; exit 1; }

# .env: generate the secret on first run; admin auth is optional on the
# production VLAN (leave unset = /admin open on the LAN).
if [ ! -f .env ]; then
    cp .env.example .env
    sed -i "s/^ICTECH_SECRET=$/ICTECH_SECRET=$(python3 -c 'import secrets; print(secrets.token_hex(32))')/" .env
    echo "Created .env (secret generated; admin auth unset = open on LAN)."
fi

GIT_SHA=$(git rev-parse --short HEAD 2>/dev/null || echo unknown)
export GIT_SHA

docker compose -f docker-compose.backstage.yaml up -d --build

IP=$(hostname -I | awk '{print $1}')
HOST=$(hostname)
echo
echo "icTech is up."
echo "  TV picker:   http://$HOST/tv   (or http://$IP/tv)"
echo "  Dashboard:   http://$HOST/"
echo "  Micboard:    http://$HOST/mb"
echo "  Tech:        http://$HOST/tech"
echo "  Admin:       http://$HOST/admin"
echo
echo "Give this Pi a DHCP reservation so the TVs' URLs never move."
