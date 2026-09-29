# Planspiel-Börse-Bot

Vollautomatischer Handel im Planspiel Börse der Sparkassen (Spielzeit 1.10.2026 – 25.1.2027).
Ablauf pro Lauf: Marktdaten (yfinance) → Claude entscheidet (strukturierte Orders) → harte Risikoregeln
in Code (`bot/risk.py`) → Ausführung → Log in `logs/`, Depotstand in `data/`.

Regeln, auf denen der Code beruht (planspiel-boerse.de/regeln.html): 0,3 % Gebühr (mind. 15 €), max. 20 %
pro Wertpapier, kein Leerverkauf/Hebel, mind. 3 Käufe bis 22.1.2027, Sterntitel für die Nachhaltigkeitswertung.

## Einrichtung

1. **Team anmelden** (ab 14.9.2026, Registrierungscode von der Sparkasse). Automatisierung vorab schriftlich
   von der Sparkasse bestätigen lassen; die Regeln erwähnen nur manuelle Eingabe.
2. **Selektoren ermitteln:** `playwright codegen <Login-URL>` – Login, Depotansicht, Wertpapierliste und eine Test-Order
   aufzeichnen; daraus `data/selectors.json` bauen und die beiden `NotImplementedError`-Methoden in
   `bot/executor.py` ausfüllen.
3. **Wertpapierliste** der Plattform (ISIN, Name, Sterne) samt yfinance-Symbol in `data/universe.json` eintragen
   (die drei Einträge dort sind nur Beispiele).
4. **GitHub Secrets:** `ANTHROPIC_API_KEY`, `PSB_USER`, `PSB_PASSWORD`. Die Zeitpläne laufen nur auf dem
   Default-Branch, also den Code dorthin mergen.
5. **Erst simulieren:** Ohne `BOT_LIVE=1` wird nur im lokalen Dry-Run gebucht. Nach ein paar Tagen Logs prüfen,
   dann die Repository-Variable `BOT_LIVE=1` setzen.

Lokal: `pip install -r requirements.txt && python -m bot.run`, Tests: `pytest`.
