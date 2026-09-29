# Planspiel-Börse-Bot

Handelt im Planspiel Börse der Sparkassen (1.10.2026 – 25.1.2027) vollautomatisch. Pro Lauf:
Marktdaten (yfinance) → Entscheidung (Claude über dein Abo, oder Regelstrategie) → harte Risikoregeln (`bot/risk.py`) → Ausführung über die Weboberfläche
(Playwright) → Log in `logs/`, Depotstand in `data/portfolio.json`. Gesteuert wird alles über ein **Handy-Dashboard**
(Start/Stopp, Übersicht, Zugangsdaten, Zeitplan), siehe unten.

## Entscheidungsquelle: ohne API-Key, mit deinem Claude-Pro-Abo

Der Bot braucht **keinen API-Key**. Es gibt drei Quellen, im Dashboard unter Einstellungen wählbar:

| Quelle | Kosten | Voraussetzung |
|---|---|---|
| **Claude-Abo** (`claude_cli`) | keine zusätzlichen, zählt gegen das Nutzungslimit deines Abos | Pro/Max-Abo und ein Token aus `claude setup-token` |
| Regelstrategie (`rules`) | keine | nichts (Momentum mit Stopps, siehe `bot/rules.py`) |
| Anthropic-API (`api`) | pro Aufruf | API-Key, brauchst du nicht |

„Automatisch“ nimmt das Abo-Token, sonst einen API-Key, sonst die Regeln. **Fällt die KI aus** (Token abgelaufen, Limit erreicht,
Fehler, mehr als 3 Minuten ohne Antwort), handelt der Bot in diesem Lauf mit der Regelstrategie weiter und
vermerkt den Grund rot im Tab Protokoll. Er fällt also nie wegen der KI aus.

**Abo-Token holen (einmalig, ca. 2 Minuten):**
1. Auf einem Rechner mit Claude Code (`curl -fsSL https://claude.ai/install.sh | bash`) `claude setup-token` ausführen und im
   Browser freigeben. Das Token (beginnt mit `sk-ant-oat01-`) wird nur angezeigt, nicht gespeichert. Es gilt ein Jahr.
2. Im Dashboard, Tab Einstellungen, in **Claude-Abo-Token** einfügen und speichern.
3. Selbsttest im Tab Steuerung: bei „Entscheidungsquelle“ muss `claude_cli (Abo) antwortet` stehen.

Hinweise: Das Token gilt nur für Claude Code, nicht für die API. Der Bot ruft `claude -p` ohne Werkzeuge in einem leeren Ordner auf
und entfernt einen eventuell gesetzten API-Key aus der Umgebung, damit nichts über die API abgerechnet wird. Bei drei Läufen pro
Tag ist der Verbrauch für dein Abo gering. Behandle das Token wie ein Passwort.

## Wie der Bot entscheidet

Pro Lauf, in dieser Reihenfolge:
1. **Kurse und Kennzahlen** (Yahoo, 14 Monate, alle Titel plus DAX, S&P 500, VIX): Momentum über 5/20/60/120 Tage, Trend (SMA50/200),
   RSI, Schwankung (ATR, Volatilität), Abstand zum 52-Wochen-Hoch, Stärke gegen den DAX (`bot/signals.py`). Das **Marktumfeld** (fünf
   Prüfungen aus DAX, S&P und VIX) wird angezeigt und an Claude gegeben, steuert die Regeln aber nicht (siehe Backtest).
2. **Fundamentaldaten und Termine** für die engere Auswahl (Depot plus die 15 stärksten): Branche, KGV, Wachstum, Marge,
   Analystenurteil, Kursziel und Termin der nächsten Gewinnmeldung (Yahoo, einmal pro Tag zwischengespeichert).
3. **Web-Recherche** (nur mit Abo-Token, einmal pro Tag): Claude sucht im Web die Nachrichten der letzten 7 Tage zu den Titeln
   der Auswahl und der allgemeinen Marktlage. Diese Stufe liefert nur strukturierte Fakten (Stimmung, Auslöser, Risiken, Termine).
4. **Entscheidung** durch eine zweite Claude-Anfrage **ohne Werkzeuge**: Sie bekommt Kennzahlen, Fundamentaldaten, Recherche-Notizen
   und den **Vorschlag der Regelstrategie** als Ausgangspunkt und weicht nur mit benanntem Grund ab (z. B. Gewinnwarnung,
   Termin in den nächsten Tagen). Die Trennung verhindert, dass Text aus dem Web direkt Orders auslöst. Fällt Claude aus, gilt der Regelvorschlag.
5. **Risikoschicht in Code** (`bot/risk.py`, gilt für jede Quelle): max. 19 % je Titel, min. 5.000 € je Order, max. 6 Orders je Lauf,
   max. 2 Titel je Branche, Penny-Stock-Sperre, Mindesthaltedauer, Gebühren und Cash-Prüfung.
6. **Ausführung** und Kontrolle, dann Protokoll.

**Regelstrategie** (`bot/rules.py`, kostenlos, auch Rückfall): Ranking nach dem Mittel aus 60- und 120-Tage-Rendite, 6 gleich große
Positionen, gehalten wird, solange ein Titel in der oberen Hälfte des Rankings bleibt. Kaufsperren: Kurs unter der 50-Tage-Linie bzw. SMA50 unter SMA200,
RSI über 85, Termin der Gewinnmeldung in den nächsten 3 Tagen. Notfall-Stopp bei 25 % Verlust.

### Was der Backtest zeigt (`python -m bot.backtest --demo-dax`, ca. 20 Sekunden)

Getestet wird an echten Kursen von 2022 bis 2026 in Zeiträumen von 80 Handelstagen (Länge des Spiels), jeweils mit 50.000 € und den Gebühren
der Plattform. Als Ersatz für die Konkurrenz dient der Anteil zufällig zusammengestellter 6-Titel-Depots, die die Strategie schlägt (50 % = Durchschnitt).

| Strategie | DAX-Werte (dort abgestimmt) | US-Aktien (Gegenprobe) |
|---|---|---|
| **Regelstrategie (jetzt)** | **64 %**, Median +10,0 %, Gebühren 311 € | **48 %**, Median +7,3 %, Gebühren 288 € |
| meine frühere Version (alle Filter, Stopps, Marktumfeld) | 49 %, Median +1,7 %, Gebühren 846 € | 41 % |
| nur 60-Tage-Momentum, keine Filter | 61 % | 45 % |

**Was daraus folgt, ohne Schönfärberei:**
- Meine erste, aufwendigere Version war **schlechter** als eine einfache. Marktumfeld-Filter, Trailing-Stops, Verkauf unter der 50-Tage-Linie,
  Trendbruch-Verkäufe und Volatilitätsgewichtung senkten den Rang. Kurzfristige Rendite (5/20 Tage) schadete (Umkehreffekt), häufiges Umschichten
  kostet Gebühren. Diese Bausteine sind deshalb aus, aber über `rules.PARAMS` schaltbar.
- Der Vorsprung gilt **nur am DAX**, wo ich abgestimmt habe. An US-Aktien liegt die Strategie im Durchschnitt, also ohne Vorsprung gegenüber Zufallsdepots.
  Ein echter Vorteil ist damit **nicht belegt**.
- Grenzen: heutige Indexmitglieder (zu optimistisch), nur 4 Jahre mit überwiegend steigenden Märkten, kein Test der Fundamentaldaten, der Termine,
  der Web-Recherche und von Claudes Urteil, weil es dafür keine historischen Daten gibt. Ob Claude besser entscheidet als die Regeln, zeigt erst der
  Trockenlauf über einige Wochen. Vergangenheit ist keine Prognose.

## Dashboard fürs Handy

Das Dashboard ist eine kleine Web-App, die zusammen mit dem Bot auf einem Rechner läuft, der dauerhaft an ist
(Raspberry Pi, Mini-PC, günstiger Server). Ein Handy kann den Bot nicht selbst ausführen, es bedient ihn nur im Browser.

| Tab | Inhalt |
|---|---|
| Übersicht | Depotwert, Verlauf, Cash, Positionen mit Gewinn/Verlust, Zähler für die Mindest-Käufe |
| Steuerung | **Start** (Zeitplan an), **Stopp** (Notaus, bricht laufenden Lauf ab), Jetzt ausführen, Selbsttest, Umschalter Trockenlauf/Live, Ausgabe |
| Protokoll | Jede Entscheidung mit Begründung, ausgeführte und abgelehnte Orders |
| Einstellungen | Planspiel-Login, Anthropic-Key, Uhrzeiten, Modell, `selectors.json`, `universe.json` |

**Starten (Docker):**
1. Auf dem Dauerrechner Docker installieren, Repository klonen, `cp .env.example .env` und in `.env` ein langes
   `DASHBOARD_PASSWORD` setzen.
2. `docker compose up -d --build`. Das Dashboard läuft auf Port 8080.
   Ohne Docker: `pip install -r requirements.txt && playwright install chromium && DASHBOARD_PASSWORD=… python -m dashboard.app`.
3. **Vom Handy erreichen, ohne den Port ins offene Internet zu stellen:** Tailscale (kostenlos) auf dem Rechner und dem Handy
   installieren und anmelden, dann `http://<Rechnername>:8080` im Handy-Browser öffnen. Alternative: ein Cloudflare Tunnel
   oder ein Reverse Proxy mit https, dann `DASHBOARD_HTTPS=1` in `.env`. Im Browser „Zum Startbildschirm hinzufügen“ macht daraus eine App.
4. Im Tab **Einstellungen** Zugangsdaten eintragen (gespeicherte Werte werden nie wieder angezeigt, leere Felder ändern nichts),
   Uhrzeiten prüfen, `selectors.json` und `universe.json` einfügen, dann **Selbsttest** im Tab Steuerung.
5. **Start** drücken. Live schaltest du erst nach erfolgreichem Selbsttest und ein paar Tagen Trockenlauf um (Eingabe von `LIVE` nötig).

**Sicherheit:** Passwortschutz mit Sperre nach 5 Fehlversuchen, Zugangsdaten nur im Ordner `state/` (Dateirechte 600,
nicht im Repo, in der Ausgabe geschwärzt). Das Dashboard steuert echte Zugangsdaten und Orders: Passwort lang wählen,
den Port nicht offen ins Internet stellen. Stopp beendet einen laufenden Lauf sofort. Trifft das mitten in einer Order,
liest der nächste Lauf das Depot neu und arbeitet vom tatsächlichen Stand weiter.

Der GitHub-Workflow ist jetzt nur noch manuell startbar, damit nicht zwei Zeitpläne gleichzeitig handeln.

**Ehrlicher Stand:** Datenabruf, Kennzahlen, Regelstrategie, Risikoschicht, Backtest, Trockenlauf, Dashboard und Zeitplan sind
getestet (`pytest`, 54 Tests) und liefen mit echten Yahoo-Daten. **Nicht getestet** sind die Live-Ausführung auf der
Plattform (braucht deinen Team-Login) und die Aufrufe über dein Claude-Abo samt Web-Recherche (braucht dein Token). Dafür gibt es
den Selbsttest (Schritt 5), der ohne Order prüft, ob alles funktioniert. Erst danach live gehen.

Regeln, auf denen der Code beruht (planspiel-boerse.de/regeln.html)
0,3 % Gebühr (mind. 15 €) · max. 20 % pro Wertpapier · kein Leerverkauf, keine Hebelprodukte, Penny Stocks < 1 € gesperrt ·
mind. 3 ausgeführte Käufe bis 22.1.2027 · Wertungen: Depotgesamtwert und Nachhaltigkeit (Sterntitel) ·
Handel über Stuttgart, Luxemburg, Wien · Stop-Orders bis 14 Tage.

## Einrichtung (ca. 1 Stunde, einmalig)

### 1. Vorbereitung
- **Team anmelden** (ab 14.9.2026): Registrierungscode bei der Sparkasse oder Lehrkraft holen, Team unter
  https://trading.planspiel-boerse.de/web/ registrieren. Benutzername und Passwort notieren.
- **Automatisierung schriftlich bestätigen lassen.** Die Regeln erwähnen nur manuelle Eingabe, weder Erlaubnis noch Verbot.
- **Kein API-Key nötig:** Für die KI nutzt du dein Claude-Abo (Abschnitt oben). Ohne Abo läuft die kostenlose Regelstrategie.
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

### 4. Dashboard einrichten
Siehe Abschnitt „Dashboard fürs Handy“ oben. Zugangsdaten trägst du dort im Tab Einstellungen ein.

### 5. Erst testen, dann live
1. **Selbsttest** (Tab Steuerung): prüft Universum, Marktdaten, Claude und Plattform-Login samt Depot-Auslesen.
   **Alles muss `[ OK ]` zeigen.** Ohne Dashboard: `python -m bot.selftest` mit gesetzten Umgebungsvariablen.
2. **Trockenlauf:** Standardmodus, bucht nur lokal. Lass ihn ein paar Tage laufen und lies die Begründungen im Tab Protokoll.
3. **Live schalten:** Tab Steuerung → Modus → „auf Live“, `LIVE` eingeben. Beobachte die ersten Läufe in der Plattform.
   Zurück oder anhalten: „auf Trockenlauf“ bzw. **Stopp**.

Alternative ohne Dashboard: GitHub Actions (`.github/workflows/trade.yml`, Secrets `ANTHROPIC_API_KEY`, `PSB_USER`,
`PSB_PASSWORD`, Variable `BOT_LIVE`; Cron-Trigger dort wieder einkommentieren, Branch in den Default-Branch mergen).

## Sicherheitsnetz
- Kann das Depot nicht gelesen werden, wird nicht gehandelt. Nach jeder Order wird das Depot neu gelesen.
- Positionsgrenze 19 %, Mindestorder 5.000 €, max. 6 Orders pro Lauf, max. 2 Titel je Branche, Mindesthaltedauer 3 Tage (Notfall-Stopps ausgenommen).
- Zugangsdaten nur im Dashboard-Ordner `state/` bzw. als GitHub-Secrets, nie im Repo.

## Dateien
`bot/run.py` Ablauf · `bot/signals.py` Kennzahlen · `bot/fundamentals.py` Fundamentaldaten · `bot/research.py` Web-Recherche ·
`bot/brain.py` Claude-Entscheidung · `bot/rules.py` Regelstrategie · `bot/backtest.py` Backtest · `bot/risk.py` Risikoregeln · `bot/executor.py` Trockenlauf und Plattform ·
`bot/universe_tool.py` Universum · `bot/selftest.py` Prüfung · `.github/workflows/trade.yml` Zeitplan (Werktags 3× UTC).
