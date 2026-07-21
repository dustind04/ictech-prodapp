#!/usr/bin/env bash
# Turn this Pi's HDMI output into the main-TV wall display. Run ON the
# Pi (Pi OS Bookworm, desktop autologin enabled):
#
#   bash scripts/pi-kiosk.sh [url]     # default: http://localhost/
#
# Chromium full-screen kiosk on whatever compositor Bookworm is using
# (labwc, wayfire, or X11/LXDE), screen blanking off. Re-run any time
# to change the URL. Takes effect on next login/reboot.
set -euo pipefail
URL="${1:-http://localhost/}"

BROWSER=$(command -v chromium-browser || command -v chromium || true)
[ -n "$BROWSER" ] || { echo "Chromium not found: sudo apt install -y chromium-browser"; exit 1; }

KIOSK="$BROWSER --kiosk --noerrdialogs --disable-infobars --disable-session-crashed-bubble --check-for-update-interval=31536000 $URL"

# labwc (Bookworm default on Pi 5)
mkdir -p ~/.config/labwc
touch ~/.config/labwc/autostart
sed -i '\|--kiosk|d' ~/.config/labwc/autostart
echo "$KIOSK &" >> ~/.config/labwc/autostart

# wayfire (earlier Bookworm images)
if [ -f ~/.config/wayfire.ini ]; then
    python3 - "$KIOSK" <<'EOF'
import configparser, os, sys
p = os.path.expanduser("~/.config/wayfire.ini")
c = configparser.ConfigParser(); c.optionxform = str; c.read(p)
if "autostart" not in c: c["autostart"] = {}
c["autostart"]["kiosk"] = sys.argv[1]
with open(p, "w") as f: c.write(f)
EOF
fi

# X11/LXDE fallback
mkdir -p ~/.config/lxsession/LXDE-pi
AUTO=~/.config/lxsession/LXDE-pi/autostart
touch "$AUTO"
sed -i '\|--kiosk|d; \|xset s off|d; \|xset -dpms|d' "$AUTO"
printf '@xset s off\n@xset -dpms\n@%s\n' "$KIOSK" >> "$AUTO"

echo "Kiosk configured -> $URL   (reboot to take effect: sudo reboot)"
