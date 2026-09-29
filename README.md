# Planspiel-Börse-Bot

Handelt im Planspiel Börse der Sparkassen (1.10.2026 – 25.1.2027) vollautomatisch. Pro Lauf:
Marktdaten (yfinance) → Claude wählt Orders → harte Risikoregeln (`bot/risk.py`) → Ausführung über die Weboberfläche
(Playwright) → Log in `logs/`, Depotstand in `data/portfolio.json`. Läuft per GitHub Actions ohne deinen Rechner.

**Ehrlicher Stand:** Entscheidungslogik, Risikoregeln, Trockenlauf und Zeitplan sind getestet (`pytest`, 11 Tests).
Die **Live-Ausführung auf der Plattform ist nicht getestet**, weil sie nur mit einem echten Team-Login geprüft werden
kann. Dafür gibt es den Selbsttest (Schritt 5), der ohne Order prüft, ob alles funktioniert. Erst danach live gehen.

## Regeln, auf denen der Code beruht (planspiel-boerse.de/regeln.html)
0,3 % Gebühr (mind. 15 €) · max. 20 % pro Wertpapier · kein Leerverkauf, keine Hebelprodukte, Penny Stocks < 1 € gesperrt ·
mind. 3 ausgeführte Käufe bis 22.1.2027 · Wertungen: Depotgesamtwert und Nachhaltigkeit (Sterntitel) ·
Handel über Stuttgart, Luxemburg, Wien · Stop-Orders bis 14 Tage.

## Einrichtung (ca. 1 Stunde, einmalig)

### 1. Vorbereitung
- **Team anmelden** (ab 14.9.2026): Registrierungscode bei der Sparkasse oder Lehrkraft holen, Team unter
  https://trading.planspiel-boerse.de/web/ registrieren. Benutzername und Passwort notieren.
- **Automatisierung schriftlich bestätigen lassen.** Die Regeln erwähnen nur manuelle Eingabe, weder Erlaubnis noch Verbot.
- **Anthropic-API-Key** unter console.anthropic.com anlegen (die Läufe kosten pro Aufruf wenige Cent).
- Python 3.11 und Git lokal installieren; dann `pip install -r requirements.txt && playwright install chromium`.

### 2. Wertpapieruniversum
Die Aktien der Plattform kommen aus Indizes (DAX, MDAX, SDAX, TecDAX, EuroStoxx 50, Dow Jones, Nasdaq 100, FTSE MIB,
Global Challenges Index) plus Fonds/ETFs/Anleihen (offizielle Liste: planspiel-boerse.de, Bereich Wertpapiere).
- Schnellstart: `python -m bot.universe_tool build` erzeugt `data/universe.json` für DAX/MDAX/TecDAX/SDAX.
  Die Zuordnung Name → Börsensymbol ist eine Heuristik. Prüfe die Ausgabe, besonders Zeilen mit „KEIN SYMBOL“.
- Genauer: eigene CSV (`isin,name,stars,yf`) aus der Instrumentensuche der Plattform, dann
  `python -m bot.universe_tool import meine_liste.csv`. **Sterne** (1 = Deka-Kriterien, 2 = GCX) übernimmst du aus der Plattform,
  sonst wird die Nachhaltigkeitswertung nicht bedient.
- Ohne ISIN (Build-Modus) suchst du in der Order-Klickfolge nach `{name}` statt `{isin}`.

### 3. Selektoren aufzeichnen (der einzige manuelle Teil)
1. `playwright codegen https://trading.planspiel-boerse.de/web/auth/login` öffnen.
2. Nacheinander aufzeichnen: Login → Depotansicht → eine Kauforder bis zur Bestätigung → eine Verkauforder.
   (Vorher im Übungsdepot, falls vorhanden, sonst mit einer kleinen Order.)
3. `cp data/selectors.example.json data/selectors.json` und jeden `SELEKTOR_…`-Eintrag durch die aufgezeichneten Selektoren
   ersetzen. Die Order-Schritte sind eine Liste aus `click`/`fill`/`press`/`select`/`wait`/`goto`; `{isin}`, `{name}`,
   `{shares}` werden eingesetzt. Zahlen im Depot werden im deutschen Format gelesen (`1.234,56 €`).
4. Hat der Login Captcha oder 2-Faktor, ist Vollautomatik nicht möglich. Dann Sparkasse fragen.

### 4. GitHub einrichten
1. Repository → Settings → Secrets and variables → Actions → **Secrets**: `ANTHROPIC_API_KEY`, `PSB_USER`, `PSB_PASSWORD`.
2. Diesen Branch in den **Default-Branch mergen** (GitHub führt Zeitpläne nur dort aus).
3. Settings → Actions → General → Workflow permissions: **Read and write** (für das Speichern von Logs und Depotstand).

### 5. Erst testen, dann live
1. Lokal: `export ANTHROPIC_API_KEY=… PSB_USER=… PSB_PASSWORD=…` und `python -m bot.selftest`.
   Es prüft Universum, Marktdaten, Claude und (mit Login) das Auslesen des Depots. **Alles muss `[ OK ]` zeigen.**
2. Trockenlauf: `python -m bot.run` (ohne `BOT_LIVE`) bucht nur lokal. Lauf ein paar Tage über Actions
   (Actions → trade → Run workflow) und lies die Begründungen in `logs/`.
3. **Live schalten:** Repository-Variable `BOT_LIVE` = `1` (Settings → Variables). Ab dann gehen Orders wirklich raus.
   Beobachte die ersten Läufe in Actions und in der Plattform. Stoppen: Variable auf `0` oder Workflow deaktivieren.

## Sicherheitsnetz
- Kann das Depot nicht gelesen werden, wird nicht gehandelt. Nach jeder Order wird das Depot neu gelesen.
- Positionsgrenze 19 %, Mindestorder 5.000 €, max. 4 Orders pro Lauf, Mindesthaltedauer 3 Tage (Stop-Verkäufe ausgenommen).
- Zugangsdaten nur als GitHub-Secrets, nie im Repo.

## Dateien
`bot/run.py` Ablauf · `bot/brain.py` Claude-Entscheidung · `bot/risk.py` Regeln · `bot/executor.py` Trockenlauf und Plattform ·
`bot/universe_tool.py` Universum · `bot/selftest.py` Prüfung · `.github/workflows/trade.yml` Zeitplan (Werktags 3× UTC).
