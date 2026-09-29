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
- Positionsgrenze 19 %, Mindestorder 5.000 €, max. 4 Orders pro Lauf, Mindesthaltedauer 3 Tage (Stop-Verkäufe ausgenommen).
- Zugangsdaten nur im Dashboard-Ordner `state/` bzw. als GitHub-Secrets, nie im Repo.

## Dateien
`bot/run.py` Ablauf · `bot/brain.py` Claude-Entscheidung · `bot/risk.py` Regeln · `bot/executor.py` Trockenlauf und Plattform ·
`bot/universe_tool.py` Universum · `bot/selftest.py` Prüfung · `.github/workflows/trade.yml` Zeitplan (Werktags 3× UTC).
