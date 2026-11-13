#!/bin/bash
# Establish / refresh the Kleinanzeigen session (or unlock ImmoScout24), safely.
# Stops the running bot (so it doesn't hold the browser profile), opens the
# login window, then restarts the bot. Use this instead of `bot.login` directly.
#   ./login.sh               Kleinanzeigen login
#   ./login.sh immoscout24   solve ImmoScout24's captcha once
cd "$(dirname "$0")"
PLIST="$HOME/Library/LaunchAgents/com.wohnungsbot.goettingen.plist"

echo "==> Stopping the bot so it releases the browser profile..."
launchctl unload "$PLIST" 2>/dev/null
pkill -f "bot.main" 2>/dev/null
sleep 2

source .venv/bin/activate
python -m bot.login "$@"

echo "==> Restarting the bot..."
if [ -f "$PLIST" ]; then
  launchctl load "$PLIST"
  echo "Bot restarted via launchd."
else
  echo "No launch agent installed — start the bot yourself with ./run.sh"
fi
