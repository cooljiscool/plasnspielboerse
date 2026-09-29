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
MAX_ORDERS_PER_RUN = 4
MIN_HOLD_DAYS = 3           # verhindert Hin-und-Her-Handel (jede Runde kostet ~0,6 %)

# --- Laufzeit ---
MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-5-5")
PROVIDER = os.environ.get("BOT_PROVIDER", "auto")   # auto | claude_cli | api | rules
CLI_TIMEOUT = int(os.environ.get("BOT_CLI_TIMEOUT", "180"))
LIVE = os.environ.get("BOT_LIVE", "0") == "1"   # ohne BOT_LIVE=1 wird nur simuliert
DATA_DIR = os.environ.get("BOT_DATA_DIR", "data")
LOG_DIR = os.environ.get("BOT_LOG_DIR", "logs")


def fee(value_eur: float) -> float:
    return max(FEE_MIN_EUR, FEE_RATE * value_eur)
