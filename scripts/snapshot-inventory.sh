#!/usr/bin/env bash
# Commit this box's inventory to GitHub, so every other box (the Pi)
# gets it with a plain `git pull`. Run ON the box where the data was
# entered (today: the Debian box):
#
#   bash scripts/snapshot-inventory.sh
#
# Exports /admin/export.json from the local app, drops person and slot
# (this repo is PUBLIC — names stay off GitHub; Planning Center and the
# Input List rebuild them on each box), writes
# seeds/inventory-YYYY-MM-DD.json, commits and pushes. Pushing uses
# whatever git auth the box has — `gh auth login` once and `gh auth
# setup-git` makes plain git push work.
set -euo pipefail
cd "$(dirname "$0")/.."

URL="http://localhost:8058/admin/export.json"
U=$(grep -E '^ICTECH_ADMIN_USER=' .env 2>/dev/null | cut -d= -f2- || true)
P=$(grep -E '^ICTECH_ADMIN_PASSWORD=' .env 2>/dev/null | cut -d= -f2- || true)
AUTH=()
[ -n "$U" ] && AUTH=(-u "$U:$P")

OUT="seeds/inventory-$(date +%F).json"
curl -fsS "${AUTH[@]}" "$URL" \
  | python3 -c 'import json,sys; d=json.load(sys.stdin); [d.pop(k,None) for k in ("person","slot")]; json.dump(d, sys.stdout, indent=1, sort_keys=True)' \
  > "$OUT.tmp"
mv "$OUT.tmp" "$OUT"
python3 - "$OUT" <<'EOF'
import json, sys
d = json.load(open(sys.argv[1]))
print("Snapshot:", ", ".join(f"{len(v)} {k}" for k, v in d.items() if isinstance(v, list)))
EOF

git add "$OUT"
if git diff --cached --quiet; then
    echo "No inventory changes since the last snapshot — nothing to commit."
    exit 0
fi
git commit -m "Inventory snapshot $(date +%F)"
git push origin HEAD
echo "Pushed. On the Pi: bash scripts/pi-update.sh"
