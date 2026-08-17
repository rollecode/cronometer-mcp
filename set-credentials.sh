#!/usr/bin/env bash
# Writes the Cronometer login into a 0600 env file that systemd reads.
# The password is never echoed and never lands in shell history.
set -euo pipefail

CONFIG_DIR="${CONFIG_DIR:-$HOME/.config/cronometer-mcp}"
ENV_FILE="$CONFIG_DIR/env"

mkdir -p "$CONFIG_DIR"
chmod 700 "$CONFIG_DIR"

read -r -p "Cronometer email: " CRON_USER
read -r -s -p "Cronometer password: " CRON_PASS
echo
read -r -p "Account timezone [Europe/Helsinki]: " CRON_TZ
CRON_TZ="${CRON_TZ:-Europe/Helsinki}"

umask 077
cat > "$ENV_FILE" <<EOF
CRONOMETER_USERNAME=$CRON_USER
CRONOMETER_PASSWORD=$CRON_PASS
CRONOMETER_ACCOUNT_TZ=$CRON_TZ
EOF
chmod 600 "$ENV_FILE"

echo "Wrote $ENV_FILE (0600)."
