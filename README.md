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
   Ein **Schutzgeländer in Code** (`brain.guard`) prüft Claudes Antwort: Käufe außerhalb der 25 besten Titel des Rankings und Verkäufe ohne belegten
   negativen Befund werden verworfen, ein ohne Beleg gestrichener Kauf wird wiederhergestellt. Claude bekommt außerdem seine letzten Orders samt
   Ergebnis (`verlauf`) und soll zu jedem Kauf das stärkste Gegenargument nennen (`bear_case`).
5. **Risikoschicht in Code** (`bot/risk.py`, gilt für jede Quelle): max. 19 % je Titel, min. 5.000 € je Order, max. 6 Orders je Lauf,
   max. 2 Titel je Branche, Penny-Stock-Sperre, Mindesthaltedauer, Gebühren und Cash-Prüfung.
6. **Ausführung** und Kontrolle, dann Protokoll.

**Regelstrategie** (`bot/rules.py`, kostenlos, auch Rückfall): Ranking nach dem Mittel aus 60-Tage-, 120-Tage- und 12-1-Monats-Rendite, 6 gleich
große Positionen, gehalten wird, solange ein Titel in den oberen 70 % des Rankings bleibt. **Volatilitäts-Skalierung:** Schwankt der Markt stark
(über 20 % pro Jahr), sinkt die investierte Quote bis auf 40 %. Kaufsperren: RSI über 85, Gewinnmeldung in den nächsten 3 Tagen. Notfall-Stopp bei 25 % Verlust.

### Wie die Strategie entstanden ist und was sie kann (`python -m bot.lab --years`, ca. 1 Minute)

Getestet wurde in **22 echten Planspiel-Zeiträumen** (jedes Jahr 1.10. bis 25.1., 2004/05 bis 2025/26, darunter 2008, 2011, 2018, 2022) mit 214 Titeln aus
DAX, MDAX, Europa und USA, 50.000 € und den Gebühren der Plattform. Rang = Anteil zufällig zusammengestellter 6-Titel-Depots, die die Strategie
im selben Zeitraum schlägt (50 % = Durchschnitt). Rund 20 Signale und Filter wurden verglichen, nach früher/später Zeit und nach Markt getrennt.

| Ergebnis | Regelstrategie (jetzt) | meine erste Version (alle Filter) |
|---|---|---|
| Median je Planspiel-Jahr | **+17,4 %** | +6,3 % |
| Jahre im Plus | **19 von 22** | 16 von 22 |
| schlechtestes Jahr | −11,1 % | −21,1 % |
| Rang gegenüber Zufallsdepots (alle Titel) | **81 %** (2004-14: 75 %, 2015-25: 86 %) | 46 % |
| Gebühren je Jahr (Median) | 145 € | 692 € |

Krisenjahre gegenüber dem Durchschnitt aller Titel: 2008 −9,5 % gegen −30,9 %, 2007 −11,1 % gegen −15,5 %, 2018 −3,0 % gegen −7,3 %. Schwach: 2011, 2014 und 2022 (Trendwenden).

**Was gilt und was nicht, ohne Schönfärberei:**
- **Realistisch sind eher 63 % als 81 %.** Im exakten Planspiel-Fenster liegt der Rang bei 81 %, bei um Wochen verschobenen Fenstern und beliebigen
  Startpunkten seit 2004 nur bei 55-70 %, im Mittel 63 % (Vorsprung gegenüber dem Durchschnitt aller Titel im Mittel +3,9 %).
- **Innerhalb einzelner Märkte ist der Vorsprung klein:** DAX 51 %, Europa 43 %, MDAX 61 %, USA 66 %. Den großen Wert erreicht erst das gemischte Universum
  (wie im Spiel), weil das Ranking dort zwischen Märkten und Branchen auswählen kann.
- **Zu optimistische Grundlage:** heutige Indexmitglieder (Überlebens-Verzerrung), Kurse in Landeswährung, keine Fundamentaldaten, Termine, Web-Recherche
  und kein Urteil von Claude, weil es dafür keine historischen Daten gibt. Ob Claude besser entscheidet als die Regeln, zeigt nur der Trockenlauf.
- **Was verworfen wurde,** weil es den Rang senkte: Trendfilter, Marktumfeld-Filter (DAX unter SMA200, VIX, Ampel), Trailing-Stops, enge Stopps, Verkauf unter
  SMA50, Gewichtung nach Volatilität, Reversal-Ideen (Rücksetzer, überverkauft), Nähe zum 52-Wochen-Hoch, niedrige Volatilität, Residual-Momentum,
  Mischungen mehrerer Signale und Teildepots. Wer Gewinner länger hält, spart Gebühren und liegt vorne.
- Auf einen Fehler in meinen ersten Tests hin (Feiertagslücken in den Kursen verfälschten die Kennzahlen) wurden alle Ergebnisse neu berechnet.

### Was ich von anderen übernommen habe (Recherche)

- **Momentum** ist der am besten belegte Faktor, mit 3 bis 12 Monaten als bestem Zeitraum und Umkehr bei einem Monat
  ([Jegadeesh/Titman](https://www.nber.org/system/files/working_papers/w7159/w7159.pdf)). Schutz vor Momentum-Einbrüchen durch Volatilitäts-Skalierung
  ([Daniel/Moskowitz](https://www.nber.org/system/files/working_papers/w20439/w20439.pdf), [Übersicht](https://quantpedia.com/three-methods-to-fix-momentum-crashes/)):
  übernommen und im Test bestätigt (schlechtester Fall −12,8 % auf −9,9 %, kein Rangverlust). Residual-Momentum brachte im Test keinen Vorteil.
- **Sprachmodelle als Händler:** [FINSABER](https://arxiv.org/html/2505.07078v4) fand über 20 Jahre, dass sie den Markt nicht schlagen, im Aufschwung zu vorsichtig
  und im Abschwung zu aggressiv sind und dass mehr Komplexität nur Rauschen bringt. [StockBench](https://arxiv.org/abs/2510.02209) fand dasselbe.
  Konsequenz: Claude bekommt eine enge Rolle (prüfen und begründet abweichen) und das Schutzgeländer, keine freie Handelsvollmacht.
- **[TradingAgents](https://github.com/TauricResearch/TradingAgents):** Gegenargument-Prüfung (`bear_case`), Erinnerung an frühere Entscheidungen samt Ergebnis (`verlauf`).
  **[Anthropics Finanz-Werkzeuge](https://github.com/anthropics/financial-services):** Katalysatorkalender und Vorab-Analyse vor Gewinnmeldungen
  (Feld `next_event` in der Recherche). Mehrere Analysten-Agenten mit Debatte habe ich nicht übernommen: mehr Aufrufe des Abo-Limits ohne Beleg für Nutzen.
- **Planspiel-Sieger** setzten laut [Presseberichten](https://www.dsgv.de/newsroom/presse/20220131_PM_Spielende_Planspiel_Boerse_03.html) auf Trend und starke Titel (US-Großwerte, Halbleiter,
  Rüstung) und stiegen um etwa 25 bis 40 %. Das deckt sich mit der Momentum-Auswahl. Jahreszeitliche Muster (Weihnachtsrally, Januar-Effekt) sind nur schwach belegt
  und wurden nicht eingebaut.

### Weitere Daten: Zinsen, Konjunktur, Bilanzen, Insider, Social Media

Der Bot betrachtet zusätzlich diese Daten. **Nur Claude sieht sie, die feste Berechnung nutzt sie nicht.** Grund: Was sich nicht an der Vergangenheit prüfen lässt, darf die Auswahl
nicht steuern. Meine erste Version mit vielen ungeprüften Zusatzregeln lag bei 46 % Rang, die einfache bei 81 %.

| Daten | Quelle | Was genau | Getestet? | Wirkung |
|---|---|---|---|---|
| **Zinsen und Konjunktur** | FRED, EZB (frei, ohne Schlüssel) | Zinskurve, Kreditaufschläge (Baa), 10-jährige Rendite, Fed-Zins, EZB-Einlagesatz, Arbeitslosigkeit (Sahm-Regel), Inflation | **Ja**, über 22 Jahre | keine Verbesserung (Tabelle unten); Claude sieht die Lage und soll deswegen **nicht** in Cash gehen |
| **Bilanzen im Detail** | Yahoo (letzte Quartale) | Nettoverschuldung zu EBITDA, Zinsdeckung, Liquidität, Eigenkapital, freier Cashflow, Marge, Piotroski-Score | Nein, Yahoo hat keine Historie mit Veröffentlichungsstand | Nur ein **schweres** Warnsignal zählt als Beleg für ein Veto von Claude |
| **Insider-Käufe** | Yahoo (nur US-Aktien), Web-Recherche (BaFin, SEC) | Käufe und Verkäufe der Führungskräfte der letzten 6 bzw. 3 Monate | Nein | nur Information (Verkäufe sind oft planmäßig) |
| **Social-Media-Stimmung** | StockTwits (öffentlich, ohne Schlüssel, nur US-Aktien) und Web-Recherche über dein Abo | Anteil „Bullish“ zu „Bearish“ in den letzten 30 Beiträgen (nur Zahlen, kein Fremdtext), dazu Funde aus Foren, Reddit und X | Nein (die Schnittstelle liefert keine Vergangenheit) | nur Information, weder Kauf- noch Veto-Grund (leicht manipulierbar, teils Gegenindikator; der Bullish-Anteil liegt bei fast allen Titeln über 70 %, in einer Stichprobe von 6 großen US-Titeln bei 73 bis 92 %, ein hoher Wert allein sagt also nichts). Reddit sperrt Programme direkt (403), das wird nicht umgangen. |

Fehlt etwas (Banken haben kein EBITDA, Yahoo kennt keine deutschen Insider-Geschäfte, französische Firmen melden halbjährlich), bleibt das Feld leer, geschätzt wird nichts.

**Test der Makrodaten** (Zinsen, Konjunktur; Warnsignal aktiv: höchstens 50 % investiert, sonst wie im Standard; 22 Planspiel-Jahre, Markt „alle“; nur zum Spielstart aktive Jahre gezählt):

| Warnsignal | Jahre aktiv | Median | Rang | schlechtestes Jahr |
|---|---|---|---|---|
| **ohne Makro (Standard)** | – | **+17,4 %** | **81 %** | −9,9 % |
| Zinskurve invers (10 Jahre unter 2 Jahren) | 3 von 22 | +15,0 % | 77 % | −9,9 % |
| Kreditaufschläge weiten sich aus | 4 von 22 | +16,6 % | 74 % | −9,1 % |
| Anleiherenditen steigen schnell | 2 von 22 | +16,3 % | 79 % | −9,9 % |
| Fed strafft | 1 von 22 | +16,6 % | 79 % | −9,3 % |
| Sahm-Regel (Arbeitsmarkt) | 4 von 22 | +17,0 % | 77 % | −8,7 % |
| Inflation über 4 % | 3 von 22 | +16,6 % | 78 % | −6,0 % |
| mindestens 2 von 4 Warnsignalen | 2 von 22 | +16,3 % | 79 % | −9,3 % |

Jede Makro-Warnung kostet Rendite und Rang und hilft im schlechtesten Jahr nur wenig (am meisten die Inflationswarnung, −9,9 % auf −6,0 %). Die Aussagekraft ist begrenzt: Die Signale waren nur
in 1 bis 4 von 22 Jahren aktiv. Richtig ist also: **kein Beleg für einen Nutzen**, nicht: sicher nutzlos. Wer das Risiko im schlechtesten Fall senken will und dafür etwas Rendite opfert,
kann in `bot/lab.py` (`macro_exposure`) eine Überlagerung einschalten. Nachrechnen: `python -m bot.lab --macro`.

### Kronos (optional, standardmäßig aus)

[Kronos](https://github.com/shiyu-coder/Kronos) ist ein quelloffenes Basismodell (MIT-Lizenz) für Kerzendaten, trainiert auf über 12 Milliarden Kerzen von 45 Börsen
([Paper](https://arxiv.org/abs/2508.02739)). Der Bot kann es als zweite Meinung nutzen: Für die engere Auswahl berechnet Kronos eine Prognose über 10 Handelstage
(`kronos_ret`), sie geht an Claude und kann (`rules.PARAMS["kronos_weight"]`) die Reihenfolge der 15 Momentum-Favoriten verändern. Die Auswahl selbst bleibt beim Momentum.

**Einrichten:** `sh scripts/setup_kronos.sh` (PyTorch nur für CPU, Kronos-Code nach `vendor/Kronos`), dann im Dashboard „Kronos-Prognose“ einschalten
oder `BOT_KRONOS=1` setzen. Docker: `docker compose build --build-arg WITH_KRONOS=1`. Die Gewichte lädt der Bot beim ersten Lauf von Hugging Face.
Rechenzeit ohne Grafikkarte: Kronos-small etwa 0,7 s je Titel, Kronos-mini etwa 0,14 s.

**Ergebnis der Messung (60 Titel, 10 Tage voraus, Rangkorrelation zwischen Prognose und tatsächlicher Rendite):**

| Modell und Zeitraum | Kronos | Momentum zum Vergleich |
|---|---|---|
| Kronos-mini, ungesehene Daten (ab Sept. 2025) | +0,008 (nicht von null verschieden) | +0,066 (klar positiv) |
| Kronos-mini, 2023–2024 (evtl. im Training) | −0,005 | +0,087 |
| Kronos-small, ungesehene Daten (ab Sept. 2025) | −0,037 (10 Tage), −0,050 (20 Tage, t = −2,1) | +0,066 / +0,071 |
| Kronos-small, 2023–2024 (evtl. im Training) | Messung läuft noch | |

Beide Modelle haben damit **keine Vorhersagekraft** gezeigt. Kronos-small liegt sogar leicht im Minus (die Reihenfolge der Prognosen war eher umgekehrt zur späteren
Rendite). Neben dem Momentum bringt es keinen Zusatznutzen (Koeffizient +0,17 Prozentpunkte, t = 0,2), und als Neusortierung der 15 Momentum-Favoriten
verbessert es die Auswahl nicht (Mix 50/50: −0,22 Prozentpunkte gegenüber reinem Momentum, t = −0,6). Die Prognosen sind zudem stark verzerrt:
im Schnitt −5,4 % über 10 Tage bei tatsächlich +0,8 %, in einer Spanne von −63 % bis +55 %. Die Trainingsdaten von Kronos haben kein veröffentlichtes Enddatum. Ein fairer Test ist deshalb nur für Zeiträume nach Erscheinen des Papiers
(August 2025) möglich, das sind nur rund 13 Monate. Solange ein Test keinen Nutzen zeigt, bleibt `kronos_weight` auf 0 und Kronos ausgeschaltet.

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
getestet (`pytest`, 101 Tests) und liefen mit echten Yahoo-Daten. **Nicht getestet** sind die Live-Ausführung auf der
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
- **Schon dabei:** `data/universe.json` enthält das Universum, an dem die Strategie getestet wurde (rund 210 Titel aus DAX, MDAX, Europa und USA,
  mit Namen und ISINs von Yahoo). Neu erzeugen: `python -m bot.universe_tool tested`. Die Strategie wählt zwischen Märkten aus,
  ein größeres, gemischtes Universum passt also besser als ein einzelner Index.
- **Abgleich mit der Plattform (wichtig):** Nicht jeder Titel ist im Spiel handelbar (Mindestkurs 1 €, nur die Werte der Indizes und Fonds). Tausche
  `data/universe.json` gegen die Liste der Plattform aus, sobald du sie hast: eigene CSV mit den Spalten `isin,name,stars,yf`
  (`yf` = Yahoo-Symbol für die Kurse), dann `python -m bot.universe_tool import meine_liste.csv`. Titel, die die Plattform nicht kennt, würden bei der
  Order scheitern. **Sterne** (1 = Deka-Kriterien, 2 = GCX) übernimmst du aus der Plattform, sonst wird die Nachhaltigkeitswertung nicht bedient.
- Ohne echte ISIN steht das Yahoo-Symbol im Feld `isin`. Dann suchst du in der Order-Klickfolge nach `{name}` statt `{isin}`.

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
`bot/brain.py` Claude-Entscheidung mit Schutzgeländer · `bot/journal.py` Gedächtnis · `bot/rules.py` Regelstrategie ·
`bot/lab.py` Test in Planspiel-Jahren · `bot/backtest.py` Backtest-Grundlage · `bot/universes.py` Testtitel · `bot/macro.py` Zinsen und Konjunktur · `bot/statements.py` Bilanzen und Insider · `bot/social.py` Stimmung · `bot/kronos_signal.py` Kronos (optional) · `bot/risk.py` Risikoregeln · `bot/executor.py` Trockenlauf und Plattform ·
`bot/universe_tool.py` Universum · `bot/selftest.py` Prüfung · `.github/workflows/trade.yml` Zeitplan (Werktags 3× UTC).
