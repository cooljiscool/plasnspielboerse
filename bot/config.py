"""Spielregeln (Planspiel Börse 2026, planspiel-boerse.de/regeln.html) und Laufzeit-Konfiguration."""
import os
from datetime import date

# --- Spielregeln ---
FEE_RATE = 0.003            # 0,3 % vom Kurswert
FEE_MIN_EUR = 15.0          # mindestens 15 € pro Order
MAX_POSITION_SHARE = 0.20   # max. 20 % des Gesamtdepotwerts pro Wertpapier
MIN_PRICE_EUR = 1.0         # Penny Stocks (< 1 €) nicht kaufbar
MIN_BUY_ORDERS = 3          # Disqualifikation bei weniger als 3 ausgeführten Käufen
GAME_START = date(2026, 10, 1)
INTERIM_EVAL = date(2026, 11, 11)
BUY_DEADLINE = date(2027, 1, 22)
GAME_END = date(2027, 1, 25)

# --- Eigene Risikoregeln (bewusst konservativer als das Limit, damit Kursbewegungen
# zwischen zwei Läufen das 20-%-Limit nicht reißen) ---
POSITION_CAP = 0.19
MIN_ORDER_EUR = 5000.0      # darunter frisst die 15-€-Mindestgebühr überproportional
MAX_ORDERS_PER_RUN = 6
MAX_PER_SECTOR = 2          # höchstens 2 Positionen je Branche (Streuung)
MIN_HOLD_DAYS = 3           # verhindert Hin-und-Her-Handel (jede Runde kostet ~0,6 %)

# --- Laufzeit ---
MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-5-5")
PROVIDER = os.environ.get("BOT_PROVIDER", "auto")   # auto | claude_cli | api | rules
CLI_TIMEOUT = int(os.environ.get("BOT_CLI_TIMEOUT", "180"))
RESEARCH = os.environ.get("BOT_RESEARCH", "1") == "1"   # Web-Recherche (nur Quelle claude_cli)
RESEARCH_TIMEOUT = int(os.environ.get("BOT_RESEARCH_TIMEOUT", "480"))
KRONOS = os.environ.get("BOT_KRONOS", "0") == "1"       # Kronos-Prognose (optional, braucht PyTorch, siehe scripts/setup_kronos.sh)
KRONOS_SIZE = os.environ.get("BOT_KRONOS_SIZE", "small")   # mini | small | base
KRONOS_DIR = os.environ.get("KRONOS_DIR", "vendor/Kronos")
KRONOS_HORIZON = int(os.environ.get("BOT_KRONOS_HORIZON", "10"))
KRONOS_CONTEXT = int(os.environ.get("BOT_KRONOS_CONTEXT", "256"))
KRONOS_SAMPLES = int(os.environ.get("BOT_KRONOS_SAMPLES", "1"))
SHORTLIST = 15              # so viele Titel bekommen Fundamentaldaten und Web-Recherche
LLM_CANDIDATES = 40         # so viele Kandidaten sieht Claude bei der Entscheidung
LIVE = os.environ.get("BOT_LIVE", "0") == "1"   # ohne BOT_LIVE=1 wird nur simuliert
DATA_DIR = os.environ.get("BOT_DATA_DIR", "data")
LOG_DIR = os.environ.get("BOT_LOG_DIR", "logs")


def fee(value_eur: float) -> float:
    return max(FEE_MIN_EUR, FEE_RATE * value_eur)
