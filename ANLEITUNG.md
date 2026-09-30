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

## 10. Selektoren aufzeichnen (der einzige manuelle Teil)
Der Bot bedient die Weboberfläche des Planspiels. Dafür muss einmal aufgezeichnet werden, wo geklickt wird.
1. Auf dem Rechner: `pip install playwright && playwright install chromium`, dann `playwright codegen https://trading.planspiel-boerse.de/web/auth/login`.
2. Im geöffneten Browser nacheinander ausführen: Login, Depotansicht, eine Kauforder bis zur Bestätigung, eine Verkauforder (mit einer kleinen Order oder im Übungsdepot).
3. `cp data/selectors.example.json data/selectors.json` und jeden `SELEKTOR_…`-Eintrag durch die aufgezeichneten Selektoren ersetzen. Order-Schritte sind eine Liste aus `click`/`fill`/`press`/`select`/`wait`/`goto`; `{isin}`, `{name}`, `{shares}` werden eingesetzt. Nimmt das Suchfeld keine ISIN an, nutze `{name}`.
4. Alternativ den Inhalt von `selectors.json` im Dashboard (Einstellungen) einfügen.
Oder gib Claude (Desktop-App oder Claude Code auf deinem Rechner) den fertigen Prompt aus `ANWEISUNG_SELEKTOREN.md`: Er zeichnet auf, schreibt die Datei und prüft sie mit dem Selbsttest; das Passwort tippst du dabei selbst.
Hilfe: Schick mir Screenshots der Seiten (ohne persönliche Daten), dann schreibe ich die Selektoren.

## 11. Selbsttest
Tab Steuerung, **Selbsttest**. Alles muss `[ OK ]` zeigen: Universum (amtliche Liste), Marktdaten, Entscheidungsquelle (`claude_cli (Abo) antwortet`), Plattform-Login samt Depot-Auslesen. Zeile mit `[FAIL]`: Meldung lesen oder an mich schicken. `[WARN]` bei Zusatzdaten ist unkritisch.

## 12. Trockenlauf (mindestens einige Tage)
1. Modus bleibt **Trockenlauf** (bucht nur lokal, keine echten Orders).
2. Uhrzeiten im Tab Einstellungen prüfen, dann **Start** drücken.
3. Im Tab Protokoll die Begründungen jeder Entscheidung lesen. Bricht etwas ab, sagt das Protokoll warum.
4. Nach 4 bis 5 Wochen zeigt `python -m bot.track` (bzw. im Container `docker compose exec dashboard python -m bot.track`), ob Claudes Prognosen etwas taugen.

## 13. Live schalten
1. Erst wenn der Selbsttest sauber ist und der Trockenlauf plausibel aussieht.
2. Tab Steuerung, Modus **auf Live**, `LIVE` eingeben. Die ersten Läufe direkt in der Plattform beobachten.
3. **Stopp** beendet sofort. Zurück: „auf Trockenlauf“.

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
