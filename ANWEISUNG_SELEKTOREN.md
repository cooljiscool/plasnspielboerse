# Prompt: Claude zeichnet die Selektoren mit `playwright codegen` auf

Diesen Text in Claude einfügen (Claude-Desktop-App mit Computer Use, oder Claude Code im Ordner des Repos auf deinem Rechner). Das Repo muss lokal liegen (`git clone https://github.com/cooljiscool/plasnspielboerse.git`).

---

Du hilfst mir, den Trading-Bot in diesem Repo (Planspiel Börse der Sparkassen) mit der Weboberfläche des Planspiels zu verbinden. Es fehlt genau eine Datei: `data/selectors.json`. Sie sagt dem Bot, welche Felder und Knöpfe er auf https://trading.planspiel-boerse.de/web/ bedienen muss. Vorlage: `data/selectors.example.json` (dort stehen `SELEKTOR_…`-Platzhalter). Arbeite Schritt für Schritt und melde dich nach jedem Schritt kurz.

**Sicherheitsregeln, ohne Ausnahme:**
- Das Passwort tippe nur ich selbst in das Browserfenster. Du fragst nie danach, tippst es nie, speicherst es nirgends und schreibst es in keine Datei, kein Log und keinen Befehl.
- Bei Captcha oder Zwei-Faktor-Abfrage: Stopp und mir sagen. Dann ist Vollautomatik nicht möglich und ich frage die Sparkasse.
- Eine echte Order (Spielgeld, kleine Stückzahl) gibst du nur auf, nachdem ich es ausdrücklich erlaubt habe, und höchstens eine Kauforder und eine Verkauforder.
- Nichts an Dritte senden. Selektoren und Seitenstruktur bleiben lokal.

**Schritt 1: Vorbereitung.** Prüfe, ob Python 3.11 und Playwright da sind (`python -m playwright --version`). Falls nicht: `pip install -r requirements.txt` und `playwright install chromium`.

**Schritt 2: Aufzeichnen.** Starte
`playwright codegen --target python -o data/codegen_aufzeichnung.py https://trading.planspiel-boerse.de/web/auth/login`.
Sag mir, dass ich mich jetzt selbst anmelden soll, und warte, bis ich „angemeldet“ schreibe. Danach klickst du (oder ich) nacheinander durch: Depotansicht (Positionen, verfügbares Geld), neue Order (Wertpapier per Suche finden, Treffer wählen, Kaufen, Stückzahl eintragen, absenden, bestätigen), und dasselbe für Verkaufen. Zwischenschritte wie eine Vorschauseite mit aufzeichnen. Nach meiner Erlaubnis darf für die Bestätigungsseite eine kleine echte Order (Spielgeld) aufgegeben werden.

**Schritt 3: `data/selectors.json` schreiben.** Kopiere die Struktur von `data/selectors.example.json` und ersetze jeden Platzhalter durch einen Selektor, den du aus der Aufzeichnung und den Seiten ableitest. Bevorzuge stabile Selektoren: `id`, `data-testid`, `name`, `aria-label`, `role`, sichtbarer Text (`button:has-text("Kaufen")`), keine langen Klassenketten oder Positionen. Die Schlüssel:
- `login_url`, `user_field`, `password_field`, `login_button`, `logged_in_marker` (ein Element, das es nur nach der Anmeldung gibt).
- `portfolio`: `url` (Adresse der Depotansicht), `cash_selector` (verfügbares Geld, genau ein Element), `row_selector` (eine Zeile der Positionstabelle), und relativ zur Zeile `isin_cell`, `shares_cell`, `avg_price_cell` (Kaufkurs). Zahlen im deutschen Format werden vom Bot gelesen (`1.234,56 €`).
- `order.buy_steps` und `order.sell_steps`: Listen aus Schritten `{"do": "click|fill|press|select|wait|goto", "selector": "…", "value": "…"}`. Platzhalter im `value`: `{search}` (bei der amtlichen Liste die ISIN, sie ist eindeutig; nimmt das Suchfeld keine ISIN an, `{name}` verwenden), `{shares}`, `{isin}`, `{name}`, `{stop}`. Reihenfolge wie beim Klicken, mit `wait`-Schritten, wo die Seite nachlädt (z. B. auf die Trefferliste).
- `depot_switch`: `test_steps` und `echt_steps` (die Klicks, mit denen man nach der Anmeldung das Test-Depot bzw. das Wettbewerbsdepot wählt) und `test_marker`/`echt_marker` (ein Element, das nur im jeweiligen Depot sichtbar ist, z. B. der Depotname). Hat die Plattform nur ein Depot: `{"skip": true}`.
- `order.stop_steps` (optional, sonst leere Liste) und `order.confirmation_marker` (Element der Erfolgsmeldung nach dem Absenden).
Prüfe jeden Selektor am geöffneten Fenster (Playwright-Inspektor oder `page.locator(...).count()`): Er muss genau das gewünschte Element treffen, bei `cash_selector`, den Login-Feldern und dem Login-Knopf genau eines.

**Schritt 4: Prüfen.** Ich setze in einem Terminal die Umgebungsvariablen `PSB_USER` und `PSB_PASSWORD` selbst. Dann führst du `python -m bot.selftest` aus. Es muss `[ OK ] Plattform-Login + Depot lesen` erscheinen. Bei einem Fehler: Meldung lesen, die betroffenen Selektoren am Fenster nachprüfen, korrigieren, wiederholen. Prüfe außerdem, dass die gelesenen Positionen zu dem passen, was ich im Depot sehe.

**Schritt 5: Abschluss.** Fasse in wenigen Zeilen zusammen, welche Selektoren du gewählt hast und wo sie unsicher sind. Lösche `data/codegen_aufzeichnung.py`, falls darin etwas Persönliches steht. Das eigentliche Kaufen und Verkaufen testen wir danach im Trockenlauf des Dashboards; live schalte ich selbst um.
