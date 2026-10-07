#!/bin/sh
# Ein Befehl bis zum laufenden Dashboard:  sh start.sh
# Legt .env mit einem zufälligen Dashboard-Passwort an (falls es fehlt), baut den Container und startet ihn. Braucht Docker (Docker Desktop oder Docker Engine mit Compose).
set -e
cd "$(dirname "$0")"
command -v docker >/dev/null 2>&1 || { echo "Docker fehlt. Installieren: https://docs.docker.com/get-docker/ (Linux: curl -fsSL https://get.docker.com | sh), dann sh start.sh erneut."; exit 1; }
if [ ! -f .env ]; then
  cp .env.example .env
  PW=$( (openssl rand -hex 16 2>/dev/null) || (head -c 16 /dev/urandom | od -An -tx1 | tr -d ' \n') )
  sed "s/^DASHBOARD_PASSWORD=.*/DASHBOARD_PASSWORD=$PW/" .env > .env.tmp && mv .env.tmp .env
  echo "Dashboard-Passwort erzeugt und in .env gespeichert:  $PW"
else
  echo ".env vorhanden, das Passwort bleibt wie es ist."
fi
mkdir -p state data logs
git log -1 --format='%h %s (%cd)' --date=short > state/version.txt 2>/dev/null || true   # Stand der Software für den Statusbericht im Dashboard
docker compose up -d --build
echo
echo "Fertig. Das Dashboard läuft auf http://localhost:8080 (vom Handy: Tailscale, siehe ANLEITUNG.md Schritt 5)."
echo "Weiter im Dashboard, Tab Einstellungen: Claude-Token (claude setup-token), Planspiel-Login, dann Tab Steuerung: Wertpapierliste laden, Selbsttest, Start."
