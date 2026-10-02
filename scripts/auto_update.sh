#!/bin/sh
# Automatisches Update für den Server. Per Cron alle paar Minuten aufrufen (siehe SERVER_ANLEITUNG.md, Abschnitt "Automatisches Update").
# 1. Holt neue Commits vom aktuellen Branch (nur "fast-forward": Gibt es lokale Änderungen, die dazwischenfunken, bricht es ab und meldet das).
# 2. Baut den Container neu. Erst wenn gerade kein Lauf des Bots arbeitet, wird der Container ausgetauscht (ein Neustart würde den Lauf abbrechen).
# 3. Merkt sich in state/deployed_commit, was läuft. Wurde nur gebaut, aber noch nicht ausgetauscht, passiert das beim nächsten Aufruf.
cd "$(dirname "$0")/.." || exit 1
mkdir -p state
log() { echo "$(date '+%F %T') $*"; }

running() {   # 0 = ein Vorgang läuft (Start vor weniger als 60 Minuten, noch ohne Ende)
  [ -f state/last_run.json ] || return 1
  python3 - <<'PY'
import json, sys
from datetime import datetime, timezone
try:
    d = json.load(open("state/last_run.json"))
    if d.get("end") is None and d.get("start"):
        age = (datetime.now(timezone.utc) - datetime.fromisoformat(d["start"])).total_seconds()
        sys.exit(0 if age < 3600 else 1)
except Exception:
    pass
sys.exit(1)
PY
}

BRANCH=$(git rev-parse --abbrev-ref HEAD)
if git fetch -q origin "$BRANCH"; then
  if [ "$(git rev-parse HEAD)" != "$(git rev-parse FETCH_HEAD)" ]; then
    git merge -q --ff-only FETCH_HEAD || { log "Update nicht möglich: lokale Änderungen im Weg (git status prüfen)"; exit 1; }
    log "Neuer Stand $(git rev-parse --short HEAD): $(git log -1 --format=%s)"
  fi
else
  log "git fetch fehlgeschlagen (Netzwerk?)"
fi

NOW=$(git rev-parse HEAD)
[ "$(cat state/deployed_commit 2>/dev/null)" = "$NOW" ] && exit 0

log "Baue Container für $(git rev-parse --short HEAD)"
docker compose build -q || { log "Build fehlgeschlagen, der alte Container läuft weiter"; exit 1; }
if running; then
  log "Es läuft gerade ein Vorgang, Austausch beim nächsten Aufruf"
  exit 0
fi
docker compose up -d && echo "$NOW" > state/deployed_commit && log "Aktualisiert auf $(git rev-parse --short HEAD)"
