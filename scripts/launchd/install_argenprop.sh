#!/bin/bash
# Instala (o reinstala) la tarea diaria de Argenprop en esta Mac — ver
# ingest/argenprop_local.py para el por qué. Corre todos los días a las
# 08:30 (hora de la Mac), antes de la ingesta de Actions (10:00 ARG). Si la
# Mac está dormida a esa hora, launchd la corre al despertar; si está
# apagada, ese día se saltea (Actions usa el archivo de ayer, hasta
# scraping.argenprop_local_max_dias).
#
#   scripts/launchd/install_argenprop.sh            # instalar
#   scripts/launchd/install_argenprop.sh --uninstall
#   launchctl kickstart gui/$(id -u)/com.radar-inmobiliario.argenprop   # correr ya
#   tail -f ~/Library/Logs/radar-argenprop.log
set -euo pipefail

LABEL="com.radar-inmobiliario.argenprop"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
REPO="$(cd "$(dirname "$0")/../.." && pwd)"
LOG="$HOME/Library/Logs/radar-argenprop.log"
UV="$(command -v uv || true)"

launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true

if [[ "${1:-}" == "--uninstall" ]]; then
  rm -f "$PLIST"
  echo "Desinstalado."
  exit 0
fi

if [[ -z "$UV" ]]; then
  echo "No encuentro uv en el PATH." >&2
  exit 1
fi

mkdir -p "$HOME/Library/LaunchAgents" "$HOME/Library/Logs"
cat > "$PLIST" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>$UV</string><string>run</string><string>python</string>
    <string>-m</string><string>ingest.argenprop_local</string><string>--push</string>
  </array>
  <key>WorkingDirectory</key><string>$REPO</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>PATH</key><string>$(dirname "$UV"):/usr/bin:/bin:/usr/sbin:/sbin</string>
  </dict>
  <key>StartCalendarInterval</key>
  <dict><key>Hour</key><integer>8</integer><key>Minute</key><integer>30</integer></dict>
  <key>StandardOutPath</key><string>$LOG</string>
  <key>StandardErrorPath</key><string>$LOG</string>
</dict>
</plist>
PLIST

launchctl bootstrap "gui/$(id -u)" "$PLIST"
echo "Instalado: $PLIST"
echo "Corre todos los días a las 08:30. Log: $LOG"
