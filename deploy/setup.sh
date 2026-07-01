#!/usr/bin/env bash
#
# One-shot setup for running ClaudeMarket as a systemd service on a Linux
# VM (e.g. Google Cloud e2-micro). Run it from the cloned repo:
#
#     bash deploy/setup.sh
#
# Prereqs: the repo is cloned, and .env exists next to bot.py with your
# DISCORD_BOT_TOKEN, DISCORD_WEBHOOK_URL, and (optional) ODDS_API_KEY.

set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
USER_NAME="$(whoami)"
SERVICE_NAME="claudemarket"
SERVICE_PATH="/etc/systemd/system/${SERVICE_NAME}.service"

echo "==> App directory: $APP_DIR"

if [ ! -f "$APP_DIR/.env" ]; then
  echo "ERROR: $APP_DIR/.env not found."
  echo "Copy the template and fill it in first:"
  echo "    cp \"$APP_DIR/.env.example\" \"$APP_DIR/.env\" && nano \"$APP_DIR/.env\""
  exit 1
fi

echo "==> Installing python3-venv if needed (may prompt for sudo)"
if ! python3 -c "import venv" 2>/dev/null; then
  sudo apt-get update -qq
  sudo apt-get install -y -qq python3-venv
fi

echo "==> Creating virtualenv and installing dependencies"
python3 -m venv "$APP_DIR/.venv"
"$APP_DIR/.venv/bin/pip" install --upgrade pip -q
"$APP_DIR/.venv/bin/pip" install -r "$APP_DIR/requirements.txt" -q

echo "==> Writing systemd unit to $SERVICE_PATH"
sudo tee "$SERVICE_PATH" >/dev/null <<UNIT
[Unit]
Description=ClaudeMarket Discord bot
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=${USER_NAME}
WorkingDirectory=${APP_DIR}
ExecStart=${APP_DIR}/.venv/bin/python bot.py
Restart=always
RestartSec=5
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
UNIT

echo "==> Enabling and starting the service"
sudo systemctl daemon-reload
sudo systemctl enable --now "$SERVICE_NAME"

sleep 2
echo "==> Status:"
sudo systemctl --no-pager --full status "$SERVICE_NAME" | head -n 12 || true

cat <<TIPS

Done. Useful commands:
  sudo systemctl status claudemarket      # is it running?
  journalctl -u claudemarket -f           # live logs
  sudo systemctl restart claudemarket     # after editing .env
  sudo systemctl stop claudemarket        # stop it
TIPS
