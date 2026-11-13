#!/bin/bash
# macOS only: install the launchd agent so the bot starts at login and
# restarts on crash. Fills the absolute path into the plist template.
#   ./install-autostart.sh
set -e
cd "$(dirname "$0")"
DIR="$(pwd)"
PLIST="$HOME/Library/LaunchAgents/com.wohnungsbot.goettingen.plist"

mkdir -p "$DIR/data" "$HOME/Library/LaunchAgents"
sed "s#__BOT_DIR__#$DIR#g" com.wohnungsbot.goettingen.plist.template > "$PLIST"
launchctl unload "$PLIST" 2>/dev/null || true
launchctl load "$PLIST"

echo "✓ Autostart installed and running: $PLIST"
echo "  Stop with:  launchctl unload \"$PLIST\""
