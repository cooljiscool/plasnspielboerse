# Schritt für Schritt von null bis zum laufenden Bot

Dauer: etwa 1 bis 2 Stunden, einmalig. Zeit-Ziel: fertig vor dem Spielstart am 1.10.2026 (Trockenlauf kann früher beginnen).

## Schnellstart (wenn Docker schon läuft)
```
git clone https://github.com/cooljiscool/plasnspielboerse.git
cd plasnspielboerse
sh start.sh
```
`start.sh` erzeugt ein zufälliges Dashboard-Passwort (in `.env`), baut den Container und startet das Dashboard auf http://localhost:8080. Alles Weitere (Token, Login, Liste laden, Selbsttest, Start) machst du im Dashboard, die Schritte 5 bis 13 unten.
Die Wertpapierliste (517 Titel mit Branchen) ist im Repo enthalten, ebenso alle Tests und Auswertungen (`python -m bot.lab --trefferquote`, `python scripts/test_claude_auswahl.py`, `python -m bot.shadow`).

## 0. Was du brauchst
- Einen Rechner, der dauerhaft an ist (Mini-PC, Raspberry Pi 4/5, günstiger Server oder dein PC, solange er läuft). Das Handy steuert den Bot nur im Browser.
- Dein Claude-Pro-Abo (kein API-Key nötig).
- Einen Team-Zugang zum Planspiel (Registrierungscode von Sparkasse oder Lehrkraft).

## 1. Planspiel-Team anlegen (ab 14.9.2026)
1. Registrierungscode holen, Team unter https://trading.planspiel-boerse.de/web/ registrieren.
2. Benutzername und Passwort notieren (ein neues, nur dafür genutztes Passwort).
3. Von der Sparkasse oder Lehrkraft **schriftlich bestätigen lassen**, dass automatisiertes Handeln erlaubt ist. Die Regeln erwähnen nur manuelle Eingabe.
4. Prüfen, ob der Login ein Captcha oder eine Zwei-Faktor-Abfrage hat. Dann ist Vollautomatik nicht möglich: Sparkasse fragen.

## 2. Programme auf dem Dauerrechner installieren
1. **Git** und **Docker** installieren (Docker Desktop bzw. `curl -fsSL https://get.docker.com | sh` unter Linux).
2. Claude Code installieren (nur einmal, um das Abo-Token zu holen): `curl -fsSL https://claude.ai/install.sh | bash`

## 3. Code holen
```
git clone https://github.com/cooljiscool/plasnspielboerse.git
cd plasnspielboerse
```
Dann `sh start.sh`: Es legt `.env` mit einem zufälligen Passwort fürs Handy-Dashboard an (oder setze selbst eins bei `DASHBOARD_PASSWORD`, mindestens 8 Zeichen, besser 20+).

## 4. Dashboard starten
Erledigt `sh start.sh` (nutzt `docker compose up -d --build`).
Das dauert beim ersten Mal einige Minuten. Danach läuft das Dashboard auf Port 8080 (`http://localhost:8080` auf dem Rechner). Ohne Docker: `pip install -r requirements.txt && playwright install chromium && DASHBOARD_PASSWORD=... python -m dashboard.app` (Python 3.11).

## 5. Vom Handy erreichen (ohne den Port ins offene Internet zu stellen)
1. **Tailscale** (kostenlos) auf dem Rechner und dem Handy installieren, mit demselben Konto anmelden.
2. Im Handy-Browser `http://<Rechnername>:8080` öffnen, mit dem Dashboard-Passwort anmelden.
3. Optional „Zum Startbildschirm hinzufügen“: dann ist es eine App.

## 6. Claude-Abo-Token holen
1. Auf dem Rechner (oder einem beliebigen Rechner mit Claude Code): `claude setup-token`, im Browser freigeben.
2. Das angezeigte Token (beginnt mit `sk-ant-oat01-`) kopieren. Es wird nur einmal angezeigt und gilt ein Jahr. Behandle es wie ein Passwort.
3. Im Dashboard: Tab **Einstellungen**, Feld **Claude-Abo-Token**, einfügen, speichern.
Ohne Token läuft der Bot mit der kostenlosen Regelstrategie (ohne Web-Recherche und Claude-Urteil).

## 7. Planspiel-Login eintragen
Im Dashboard, Tab Einstellungen: Benutzername und Passwort des Teams, speichern. Die Werte liegen nur auf deinem Rechner (`state/`) und werden nie wieder angezeigt.

## 8. Optional: SEC-Insiderdaten
Im Tab Einstellungen bei „Kontakt für die SEC-Insiderdaten“ deinen Namen und deine E-Mail eintragen (z. B. `Max Muster max@example.org`). Die SEC verlangt das bei automatischen Abfragen, die Adresse geht nur dorthin. Ohne Eintrag bleiben Insiderdaten aus.

## 9. Wertpapierliste laden
Tab **Steuerung**, Knopf **Wertpapierliste des Planspiels laden** (1 bis 2 Minuten, Ausgabe erscheint darunter). Wiederhole das kurz vor dem Start und gelegentlich danach, weil sich die Liste ändern kann.

## 10. Selektoren aufzeichnen (Schritt für Schritt, ca. 30 bis 45 Minuten)
Der Bot bedient die Planspiel-Seite wie ein Mensch. Ein **Selektor** ist die Angabe, wo er klickt oder tippt („das Feld für den Benutzernamen“). Du ermittelst sie einmal mit dem Playwright-Recorder und trägst sie in `data/selectors.json` ein.

**A. Vorbereiten (auf deinem Rechner, nicht im Docker-Container)**
1. Python 3.11 installieren, im Repo-Ordner: `pip install playwright` und `playwright install chromium`.
2. `cp data/selectors.example.json data/selectors.json` (Windows: Datei kopieren und umbenennen) und in einem Editor öffnen.

**B. Recorder starten**
3. `playwright codegen --target python https://trading.planspiel-boerse.de/web/auth/login`. Es öffnen sich zwei Fenster: der Browser und der „Playwright Inspector“ mit dem mitgeschriebenen Code.

**C. Anmeldung aufnehmen**
4. Im Browser Benutzername und Passwort eingeben und auf Anmelden klicken. Im Inspector erscheinen Zeilen wie `page.get_by_label("Benutzername").fill("…")` und `page.get_by_role("button", name="Anmelden").click()`.
5. Trage aus diesen Zeilen ein (Umrechnung siehe Tabelle unten): `user_field`, `password_field`, `login_button`. **Schreibe dein Passwort nicht in die Datei**, es kommt später ins Dashboard.
6. `logged_in_marker`: ein Element, das es nur nach der Anmeldung gibt, z. B. der Abmelden-Knopf. Zum Finden oben im Inspector auf das Zielkreuz („Pick locator“) klicken, das Element im Browser anklicken, den Selektor unten kopieren.

**D. Depot aufnehmen**
7. Im Browser die Depotansicht öffnen. Adresse aus der Adresszeile in `portfolio.url` eintragen.
8. Mit „Pick locator“ nacheinander wählen und eintragen: `cash_selector` (das verfügbare Geld, genau ein Element), `row_selector` (eine Zeile der Positionstabelle), dann innerhalb der Zeile `isin_cell`, `shares_cell`, `avg_price_cell` (Kaufkurs). Sind noch keine Positionen da, wiederholst du das nach der ersten Order (Schritt 9).

**E. Kauf-Order aufnehmen**
9. Neue Order öffnen, dann klicken und tippen in genau der Reihenfolge, wie der Bot es später machen soll: Suchfeld anklicken, einen Namen oder eine ISIN eintippen, ersten Treffer anklicken, Kaufen wählen, Stückzahl eintippen, absenden, bestätigen. Wähle dabei eine kleine Stückzahl (Spielgeld, kostet nur die virtuelle Gebühr; die Order zählt auch für die Mindestzahl von 3 Käufen).
10. Jede Zeile im Inspector wird ein Eintrag in `order.buy_steps`: `.click()` wird `{"do": "click", "selector": "…"}`, `.fill("Siemens")` wird `{"do": "fill", "selector": "…", "value": "{search}"}`. Die Stückzahl bekommt `"value": "{shares}"`. Wartet die Seite nach einem Schritt (Trefferliste lädt), füge davor `{"do": "wait", "selector": "…Trefferzeile…"}` ein.
11. Das Element der Erfolgsmeldung nach dem Absenden (Pick locator) kommt in `order.confirmation_marker`.

**F. Verkauf aufnehmen**
12. Dasselbe für eine Verkauforder (Position wählen oder Suche, Verkaufen, Stückzahl, absenden, bestätigen) in `order.sell_steps`. Die Verkauforder darfst du mit einer kleinen Position aufgeben.

**G. Umrechnung Recorder-Zeile in Selektor** (das steht im Feld `selector`):

| Recorder zeigt | Selektor |
|---|---|
| `get_by_role("button", name="Kaufen")` | `role=button[name="Kaufen"]` |
| `get_by_label("Benutzername")` | `label=Benutzername` |
| `get_by_placeholder("Suche")` | `[placeholder="Suche"]` |
| `get_by_text("Order absenden")` | `text=Order absenden` |
| `get_by_test_id("buy")` | `[data-testid="buy"]` |
| `locator("#stueck")` | `#stueck` |

Nimm bevorzugt Selektoren mit sichtbarem Text, `id` oder `name`, keine langen Klassenketten. Nimmt das Suchfeld keine ISIN an, nimm `{name}` statt `{search}`.

**G2. Depot umschalten (wichtig)**
Die Plattform hat ein Test-Depot (zählt nicht) und das Wettbewerbsdepot (zählt für den Rang). Der Bot muss nach der Anmeldung das richtige wählen. Zeichne dafür auf, wie man zwischen beiden wechselt, und trage es in `selectors.json` unter `depot_switch` ein: `test_steps` (Klicks für das Test-Depot), `echt_steps` (Klicks für das Wettbewerbsdepot) und je ein `test_marker` und `echt_marker`, das ist ein Element, das nur im jeweiligen Depot zu sehen ist (z. B. der Depotname oben). Der Bot prüft nach dem Umschalten den Marker und handelt nicht, wenn das falsche Depot aktiv ist. Ohne den Abschnitt `depot_switch` handelt der Bot gar nicht (hat die Plattform bei dir nur ein Depot: `"depot_switch": {"skip": true}`).

**H. Prüfen**
13. Im Dashboard, Tab Einstellungen, `selectors.json` einfügen (oder Datei im Ordner `data/` lassen). Trage dort auch Benutzername und Passwort ein.
14. Tab Steuerung, **Selbsttest**. Es muss `[ OK ] Plattform-Login + Depot lesen` erscheinen, mit der richtigen Zahl Positionen. Bei einem Fehler zeigt die Meldung, welcher Selektor nicht gefunden wurde: Im Recorder erneut mit „Pick locator“ prüfen und korrigieren.
15. Zum Schluss den Trockenlauf starten (Schritt 12 unten). Live erst nach einigen sauberen Trockenläufen.

**Hilfe:** Schick mir Screenshots von Login, Depot und Orderformular (ohne persönliche Daten) oder den Inhalt der Recorder-Zeilen, dann schreibe ich die `selectors.json`. Oder gib Claude auf deinem Rechner den Prompt aus `ANWEISUNG_SELEKTOREN.md`.

## 11. Selbsttest
Tab Steuerung, **Selbsttest**. Alles muss `[ OK ]` zeigen: Universum (amtliche Liste), Marktdaten, Entscheidungsquelle (`claude_cli (Abo) antwortet`), Plattform-Login samt Depot-Auslesen. Zeile mit `[FAIL]`: Meldung lesen oder an mich schicken. `[WARN]` bei Zusatzdaten ist unkritisch.

## 12. Trockenlauf (mindestens einige Tage)
1. Modus bleibt **Trockenlauf** (bucht nur lokal, keine echten Orders).
2. Uhrzeiten im Tab Einstellungen prüfen, dann **Start** drücken.
3. Im Tab Protokoll die Begründungen jeder Entscheidung lesen. Bricht etwas ab, sagt das Protokoll warum.
4. Nach 4 bis 5 Wochen zeigt `python -m bot.track` (bzw. im Container `docker compose exec dashboard python -m bot.track`), ob Claudes Prognosen etwas taugen.

## 13. Live schalten
1. Erst wenn der Selbsttest sauber ist und der Trockenlauf plausibel aussieht.
2. Tab Steuerung, Modus **auf Live**, `LIVE` eingeben. Das Depot steht standardmäßig auf **Test-Depot**: Der Bot klickt dann wirklich auf der Plattform, aber die Orders zählen nicht für den Rang. Beobachte einige Läufe, ob Anmelden, Depot lesen, Kauf und Verkauf sauber laufen.
3. Erst dann im selben Bereich **auf Wettbewerbsdepot** wechseln (Bestätigung `ECHT`). Ab dem nächsten Lauf zählen die Orders. Depotstand und Startwert von Test-Depot und Wettbewerbsdepot werden getrennt gespeichert.
4. **Stopp** beendet sofort. Zurück: „auf Trockenlauf“ bzw. „auf Test-Depot“.

## 14. Einstellungen, die du kennen solltest
- **Strategie und Risiko** (Einstellungen): fünf Stile von „sicher“ (Standard) bis „jackpot“, mit Risikostufe 1 bis 5 und den gemessenen Werten. Wirkt ab dem nächsten Lauf.
- **Nachhaltigkeit** (Einstellungen): reserviert 0 bis 6 der 6 Depotplätze für Sterntitel. Standard 0 (schont die Gesamtwertung).
- **Web-Recherche aus** senkt den Claude-Verbrauch um etwa vier Fünftel, kostet aber Nachrichten, Ereignis-Vetos und Prognosen.
- Ist das Claude-Limit erreicht, handelt der Bot in diesem Lauf mit der Regelstrategie weiter.

## 15. Wenn etwas nicht klappt
- Dashboard nicht erreichbar: `docker compose ps` und `docker compose logs dashboard`.
- Login schlägt fehl: Passwort im Dashboard neu eintragen, Captcha/2FA prüfen.
- Selbsttest scheitert bei Marktdaten: Internetverbindung, Yahoo zeitweise nicht erreichbar, später wiederholen. Ohne Kurse handelt der Bot nicht.
- Nach Updates: `git pull`, dann `docker compose up -d --build`.

## Ehrliche Erwartung
Die Strategie schlägt im Test im Mittel 61 bis 67 % zufälliger Vergleichsdepots, kein sicherer Sieg. Live-Orders auf der Plattform, dein Token und die Selektoren sind noch ungetestet: deshalb erst Selbsttest und Trockenlauf.
