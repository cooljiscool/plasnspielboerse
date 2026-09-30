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

**Verbrauch, gemessen** (Trockenlauf mit echten Daten; Rechenwert zu API-Preisen, mit Abo wird nichts abgerechnet, es zählt gegen dein Nutzungslimit): Die Recherche (5 Aufrufe, 15 Titel) brauchte
rund 2 Minuten und 0,78 $, die Entscheidung 10 Sekunden und 0,16 $. Der erste Lauf eines Tages kostet also rund 0,94 $, weitere Läufe desselben Tages nur die Entscheidung (rund 0,16 $, die Recherche
kommt aus dem Zwischenspeicher). Bei drei Läufen pro Börsentag sind das etwa 1,3 $ Rechenwert, bis Spielende grob 100 $. Wie viel davon dein Abo-Limit verbraucht, hängt vom Tarif ab; der Verbrauch
jedes Laufs steht im Protokoll (`logs/*.json`, Feld `verbrauch`). **Sparen:** Web-Recherche im Dashboard ausschalten senkt den Verbrauch um rund vier Fünftel, kostet aber Nachrichten, Ereignis-Vetos und Prognosen.
Läuft das Limit trotzdem aus, handelt der Bot mit der Regelstrategie weiter.
**Anteil am Limit, gemessen:** Claude Code meldet die Auslastung der Limit-Fenster (5 Stunden und 7 Tage). Ein kompletter erster Tageslauf (Recherche und Entscheidung, 3,4 Minuten, 0,89 $ Rechenwert) bewegte sie vorher/nachher weder im 5-Stunden- noch im Wochenfenster um einen Prozentpunkt (Auflösung 1 Punkt, also unter 1 % je Lauf). Das ist eine Obergrenze, keine genaue Zahl. Genau siehst du es bei dir in claude.ai unter Einstellungen, Nutzung (oder mit `/usage` in Claude Code), vor und nach einem Lauf.

Hinweise: Das Token gilt nur für Claude Code, nicht für die API. Der Bot ruft `claude -p` ohne Werkzeuge in einem leeren Ordner auf
und entfernt einen eventuell gesetzten API-Key aus der Umgebung, damit nichts über die API abgerechnet wird. Bei drei Läufen pro
Tag ist der Verbrauch für dein Abo gering. Behandle das Token wie ein Passwort.

## Wie der Bot entscheidet

Pro Lauf, in dieser Reihenfolge:
1. **Kurse und Kennzahlen** (Yahoo, 14 Monate, alle Titel der amtlichen Wertpapierliste plus DAX, S&P 500, VIX; **in Euro umgerechnet**, offensichtliche Datenfehler entfernt): Momentum über 5/20/60/120 Tage, Trend (SMA50/200),
   RSI, Schwankung (ATR, Volatilität), Abstand zum 52-Wochen-Hoch, Stärke gegen den DAX (`bot/signals.py`). Das **Marktumfeld** (fünf
   Prüfungen aus DAX, S&P und VIX) wird angezeigt und an Claude gegeben, steuert die Regeln aber nicht (siehe Backtest).
2. **Fundamentaldaten und Termine** für die engere Auswahl (Depot plus die 15 stärksten): Branche, KGV, Wachstum, Marge,
   Analystenurteil, Kursziel und Termin der nächsten Gewinnmeldung (Yahoo, einmal pro Tag zwischengespeichert).
3. **Web-Recherche** (nur mit Abo-Token, einmal pro Tag, in Dreier-Paketen): Claude sucht im Web die Nachrichten der letzten 7 Tage zu den Titeln
   der Auswahl und der allgemeinen Marktlage. Diese Stufe liefert nur strukturierte Fakten (Stimmung, Auslöser, Risiken, Termine, laufende Übernahmeangebote)
   und je Titel eine Szenario-Einschätzung mit Risikomatrix (Abschnitt „Prognose-Bilanz“). **Warum Pakete:** Bei 15 Titeln in einem Aufruf suchte Claude im Test nur oberflächlich
   (zu 13 von 15 Titeln „keine belastbaren Nachrichten“, auch bei AMD und Intel, und nur 1 von 15 Prognosen). In Dreier-Paketen lieferte er zu allen 15 Titeln Nachrichten und
   Prognosen, in etwa 2 Minuten. Bricht ein Paket ab (Limit, Netz), bleiben die fertigen erhalten, und der nächste Lauf am selben Tag holt nur die fehlenden Titel.
4. **Zusatzdaten für Claude** (nur mit KI, Tabelle im nächsten Abschnitt): Bilanzen, Insider-Geschäfte (SEC), Analystenschätzungen, Reddit- und StockTwits-Stimmung, Zinsen und
   Konjunktur, Risikoprofil, dazu die Bilanz früherer Prognosen. Sie steuern nicht die Regeln, sondern gehen als Information an Claude.
5. **Entscheidung** durch eine zweite Claude-Anfrage **ohne Werkzeuge**: Sie bekommt Kennzahlen, Fundamentaldaten, Recherche-Notizen
   und den **Vorschlag der Regelstrategie** als Ausgangspunkt und weicht nur mit benanntem Grund ab (z. B. Gewinnwarnung,
   Termin in den nächsten Tagen). Die Trennung verhindert, dass Text aus dem Web direkt Orders auslöst. Fällt Claude aus, gilt der Regelvorschlag.
   Ein **Schutzgeländer in Code** (`brain.guard`) prüft Claudes Antwort: Käufe außerhalb der 25 besten Titel des Rankings und Verkäufe ohne belegten
   negativen Befund werden verworfen, ein ohne Beleg gestrichener Kauf wird wiederhergestellt. Claude bekommt außerdem seine letzten Orders samt
   Ergebnis (`verlauf`) und soll zu jedem Kauf das stärkste Gegenargument nennen (`bear_case`).
6. **Risikoschicht in Code** (`bot/risk.py`, gilt für jede Quelle): max. 19 % je Titel, min. 5.000 € je Order, max. 6 Orders je Lauf,
   max. 2 Titel je Branche, Penny-Stock-Sperre, Mindesthaltedauer, Gebühren und Cash-Prüfung.
7. **Ausführung** und Kontrolle, dann Protokoll (mit Verbrauch der KI-Aufrufe).

**Regelstrategie** (`bot/rules.py`, kostenlos, auch Rückfall): Ranking nach dem Mittel aus 60-Tage-, 120-Tage- und 12-1-Monats-Rendite, 6 gleich
große Positionen, gehalten wird, solange ein Titel in den oberen 70 % des Rankings bleibt. **Volatilitäts-Skalierung:** Schwankt der Markt stark
(über 20 % pro Jahr), sinkt die investierte Quote bis auf 40 %. Kaufsperren: RSI über 85, Gewinnmeldung in den nächsten 3 Tagen. Notfall-Stopp bei 25 % Verlust.

### Wie die Strategie entstanden ist und was sie kann (`python -m bot.lab --years`, ca. 1 Minute)

Getestet wurde in **22 echten Planspiel-Zeiträumen** (jedes Jahr 1.10. bis 25.1., 2004/05 bis 2025/26, darunter 2008, 2011, 2018, 2022), zuerst mit einem **Testuniversum von 214 Titeln** aus
DAX, MDAX, Europa und USA in Heimatwährung (die Tabelle hier), danach am amtlichen Universum in Euro (nächster Abschnitt, **das ist die Zahl, die für das Spiel zählt**), mit 50.000 € und den Gebühren der Plattform. Rang = Anteil zufällig zusammengestellter 6-Titel-Depots, die die Strategie
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
- **Realistisch sind deutlich weniger als 81 %.** Im exakten Planspiel-Fenster liegt der Rang im Testuniversum bei 81 %, bei um Wochen verschobenen Fenstern und beliebigen
  Startpunkten seit 2004 nur bei 55-70 %, im Mittel 63 %. Am amtlichen Universum in Euro sind es 67 % bzw. im Mittel 61 % (nächster Abschnitt).
- **Innerhalb einzelner Märkte ist der Vorsprung klein:** DAX 51 %, Europa 43 %, MDAX 61 %, USA 66 %. Den großen Wert erreicht erst das gemischte Universum
  (wie im Spiel), weil das Ranking dort zwischen Märkten und Branchen auswählen kann.
- **Zu optimistische Grundlage:** heutige Indexmitglieder (Überlebens-Verzerrung), in dieser Tabelle Kurse in Landeswährung (Euro-Nachprüfung im nächsten Abschnitt), keine Fundamentaldaten, Termine, Web-Recherche
  und kein Urteil von Claude, weil es dafür keine historischen Daten gibt. Ob Claude besser entscheidet als die Regeln, zeigt nur der Trockenlauf.
- **Was verworfen wurde,** weil es den Rang senkte: Trendfilter, Marktumfeld-Filter (DAX unter SMA200, VIX, Ampel), Trailing-Stops, enge Stopps, Verkauf unter
  SMA50, Gewichtung nach Volatilität, Reversal-Ideen (Rücksetzer, überverkauft), Nähe zum 52-Wochen-Hoch, niedrige Volatilität, Residual-Momentum,
  Mischungen mehrerer Signale und Teildepots. Wer Gewinner länger hält, spart Gebühren und liegt vorne.
- Auf einen Fehler in meinen ersten Tests hin (Feiertagslücken in den Kursen verfälschten die Kennzahlen) wurden alle Ergebnisse neu berechnet.

### Amtliche Wertpapierliste, Euro-Umrechnung und der Test darauf (Stand 29.9.2026)

Beim Nachsehen nach Datenquellen habe ich die **amtliche Wertpapierliste des Planspiels 2026** gefunden (Stand 14.9.2026, [planspiel-boerse.de/wertpapierliste.html](https://www.planspiel-boerse.de/wertpapierliste.html)).
Bis dahin nutzte der Bot ein selbst zusammengestelltes Universum. Jetzt liest `python -m bot.universe_tool official` die Liste (im Dashboard: Tab Steuerung, **Wertpapierliste des Planspiels laden**),
ordnet jeder ISIN über die Yahoo-Suche das Börsenkürzel zu (Heimatbörse bevorzugt, US-Hauptnotiz bei Konzernen mit europäischer ISIN, Xetra statt Frankfurt) und speichert `data/universe.json`:

- **520 Aktien** aus DAX 40, MDAX 50, SDAX 70, TecDAX 30, EuroStoxx 50, Auswahl aus dem Stoxx Europe 600, Dow Jones 30, Nasdaq 100, FTSE MIB, ATX, LuxX und Global Challenges 50 mit echten ISIN
  (die Prüfziffer jeder ISIN wird kontrolliert). **517 davon sind im Universum**; drei entfallen, weil Yahoo keine aktuellen Kurse kennt (Klöckner & Co, EDF, Electronic Arts, vermutlich übernommen oder delistet).
- **50 Titel mit Nachhaltigkeits-Kennzeichen** (Global Challenges Index) bekommen den Stern für die Nachhaltigkeitswertung. Fonds, ETFs, Anleihen und ETCs stehen ebenfalls in der Liste, Kryptowerte
  und Zertifikate nur im Trainingsdepot; die Strategie handelt nur Aktien.
- Die Order sucht künftig nach der **echten ISIN** (`{isin}` bzw. `{search}` in den Selektoren) statt nach einem Namen: Der Name „Siemens“ träfe drei Unternehmen, die ISIN genau eines.
  Nimmt das Suchfeld der Plattform keine ISIN an, trägst du in `selectors.json` `{name}` ein.
- Weil die Liste sich ändern kann („Änderungen vorbehalten“), lohnt es sich, sie vor dem Start und gelegentlich danach neu zu laden. Eine Sicherung der bisherigen Liste bleibt in `data/universe_vorher.json`.

**Zwei Korrekturen, die das mit sich brachte:**
1. **Kurse in Euro.** Das Spiel handelt und wertet alles in Euro (Stuttgart), Yahoo liefert Dollar, Kronen, Franken, Pence und Yen. Bisher wurden Dollarkurse wie Euro behandelt: Signale, Stückzahlen und Depotwert
   waren bei US-Aktien um den Wechselkurs falsch. Jetzt rechnet `bot/fx.py` alles mit dem Tageskurs in Euro um (Yahoo-Reihen `EURUSD=X` usw.). Fehlt ein Wechselkurs, bleibt der Titel ohne Kurs und wird nicht gehandelt.
   Kursziele werden gegen den Kurs in derselben Währung gerechnet.
2. **Datenbereinigung.** Yahoos Historien enthalten vor allem bei Nebenwerten Fehler (in den Tests: Tagesbewegungen von +400 % und −80 % im Wechsel, negative Kurse). Solche Ausreißer täuschen Momentum vor.
   `signals.clean_prices` entfernt nicht positive Kurse und Kursspitzen, die am nächsten Tag zurückgenommen werden (Labor und Live-Lauf rechnen gleich). Live werden außerdem Titel mit einer Tagesbewegung über 50 % in den letzten
   300 Handelstagen (Übernahme, Spaltung, Datenfehler) nicht gehandelt. Auf die Testergebnisse hatte das kaum Einfluss (Rang 67 % vorher wie nachher).

**Ergebnis am amtlichen Universum** (`python -m bot.lab --official`, gleiche 22 Planspiel-Jahre, Rang gegen zufällige 6-Titel-Depots aus demselben Universum, was der Auswahl der anderen Teams entspricht):

| Universum und Kurse | Titel | Median | schlechtestes Jahr | Rang (früh / spät) |
|---|---|---|---|---|
| Testuniversum, Heimatwährung (bisherige Zahl) | 214 | +17,4 % | −9,9 % | **81 %** (76 / 86) |
| Testuniversum, in Euro | 214 | +13,9 % | −10,5 % | 77 % (76 / 78) |
| amtliches Universum, in Euro (gleiche Basisvariante wie darüber) | 511 | +10,6 % | −11,8 % | 68 % (70 / 66) |
| **amtliches Universum, in Euro (Standard-Regeln wie live)** | 511 | +13,1 % | −15,2 % | **67 %** (70 / 64) |
| amtliches Universum, nur dessen Titel aus dem alten Testuniversum | 178 | +16,3 % | −8,4 % | 76 % (73 / 79) |

Einzelne Märkte im amtlichen Universum: DAX 50 %, MDAX 54 %, SDAX 65 %, Europa 58 %, USA 63 %. Bei um Wochen verschobenen Fenstern (±20, 40 und 60 Handelstage) liegt der Rang zwischen 53 und 69 %, **im Mittel bei 61 %**.

**Was das heißt, ohne Schönfärberei:**
- Die frühere Zahl von 81 % war zu hoch: Rund 4 Punkte gehen auf die Euro-Umrechnung (der schwankende Dollar), der Rest auf das breitere und gemischtere Universum, in dem Momentum weniger sicher trägt. **Rechne mit rund zwei Dritteln zufälliger
  Depots, die die Strategie schlägt, in ungünstigen Zeiträumen mit weniger.** Das ist immer noch ein Vorsprung, aber kein sicherer Sieg: In Wendejahren (2011, 2022, 2025) landete sie ganz unten (Rang 5 %, 1,5 % und 0,5 %), in Jahren mit Trend ganz oben (2012, 2019, 2024: 98 bis 100 %).
- Ich habe geprüft, ob sich das durch Einstellungen retten lässt: Haltegrenze (30 bis 100 %), andere Bewertungsformeln (60/120 Tage, 120 Tage, 12-1, Residual-Momentum) und der Verzicht auf einzelne Teile des Universums (ohne SDAX,
  nur Großwerte, nur USA, ohne USA, nur Deutschland) ergaben alle 64 bis 70 %, bei wechselnden Vorzeichen zwischen früher und später Hälfte. **Kein Ergebnis ist verlässlich besser, deshalb bleibt alles wie es ist** (das gesamte amtliche Universum,
  die bisherigen Regeln). Ausnahme nach unten: nur Europa ohne deutsche Indizes (52 %) und nur Nasdaq 100 (60 %) sind schwächer.
- Grenzen wie zuvor: heutige Indexmitglieder (Überlebens-Verzerrung, die Zahlen sind eher zu gut), keine Fundamentaldaten, Termine und Web-Recherche im Test. Ob Claude die Ergebnisse verbessert, zeigt nur der Trockenlauf und später die Prognose-Bilanz.

**Trefferquote: Wie oft liegt die Auswahl richtig?** (`python -m bot.lab --trefferquote --years`, ca. 2 Minuten, amtliches Universum in Euro, nur die Regeln, nicht Claudes Recherche.)
„Richtig“ kann dreierlei heißen, deshalb wird jedes einzeln gemessen: (1) *Steigt der gekaufte Titel?* Anteil der Käufe (die 6 stärksten kaufbaren Titel nach dem Score) im Plus nach 10 bis 80 Handelstagen, verglichen mit einem
beliebigen Titel, und Anteil der Käufe, die besser laufen als der mittlere Titel. (2) *Wie viel steigt er?* Überrendite der Käufe gegenüber allen Titeln. (3) *Was wurde aus den Positionen im Spiel?* Alle Positionen der 22 Planspiel-Jahre von Kauf bis Verkauf.

Käufe an beliebigen Tagen seit 2004, überlappungsfrei (Startpunkte im Abstand der Haltedauer, vier Startversätze; überlappende Zeiträume würden die Sicherheit zu hoch ausweisen):

| Haltedauer | Käufe | Käufe im Plus | alle Titel im Plus | Käufe besser als mittlerer Titel | Ø Überrendite | t-Wert |
|---|---|---|---|---|---|---|
| 10 Tage | 3.483 | 54 % | 54 % | 51 % | +0,4 % | 2,3 |
| 20 Tage | 1.738 | 55 % | 56 % | 51 % | +0,9 % | 2,8 |
| 40 Tage | 866 | 57 % | 58 % | 53 % | +2,2 % | 3,2 |
| 80 Tage | 430 | 62 % | 61 % | 55 % | +5,3 % | 3,1 |

Nur zum Start der 22 Planspiel-Jahre (132 Käufe am 1.10.): im Plus 49 / 47 / 58 / 63 % nach 10 / 20 / 40 / 80 Tagen (alle Titel 52 / 52 / 59 / 66 %), besser als der mittlere Titel 46 / 49 / 48 / 52 %, Überrendite −0,4 / +0,6 / −0,3 / +3,0 % (t-Wert höchstens 1,4).
Die Positionen der Regeln in den 22 Planspiel-Jahren (154 Käufe, sonst bewertet zum Schlusskurs am 25.1.):

| Positionen | Anzahl | im Plus | Ø Gewinn | Ø Verlust | Ø je Position |
|---|---|---|---|---|---|
| alle | 154 | 64 % | +23,5 % | −15,5 % | +9,3 % |
| bis zum Ende gehalten | 130 | 75 % | +23,5 % | −9,5 % | +15,4 % |
| vorzeitig verkauft (Notfall-Stopp bei −25 % oder Rangabstieg) | 24 | 0 % | – | −23,4 % | −23,4 % |

**Was das heißt, ohne Schönfärberei:**
- **Als reine Richtungsprognose ist die Auswahl nicht besser als ein beliebiger Titel.** Von 100 Käufen liegen nach 80 Tagen rund 62 im Plus, bei einem Zufallstitel 61; den mittleren Titel schlagen 55 von 100, also knapp mehr als bei einer Münze. Nach 10 Tagen
  ist es ein Münzwurf. Die Regeln sagen nicht voraus, welche Aktie steigt, sondern kaufen Titel mit etwas höherer erwarteter Rendite.
- **Der Vorteil steckt in der Größe, nicht in der Zahl der Treffer:** im Mittel +5,3 % über 80 Tage gegenüber einem Zufallstitel, überlappungsfrei mit t-Wert um 3 (in allen vier Reihen über 2). Der Zusammenhang zwischen Score und späterer Rendite
  ist klar, aber klein (Rangkorrelation +0,02 bis +0,04): Einzelkurse lassen sich über Wochen kaum vorhersagen, ein kleiner Vorsprung im Schnitt reicht aber für einen Rang über 50 %.
- **Im echten Planspiel-Fenster ist der Vorsprung nicht abgesichert.** An den 22 Starttagen liegen die Käufe im Plus sogar seltener als ein Zufallstitel (63 gegen 66 % nach 80 Tagen); 22 Zeitpunkte sind zu wenig für einen sicheren Schluss (t-Wert 1,4),
  und in den letzten elf Jahren war es schwächer als in den ersten elf (im Plus nach 80 Tagen 67 % gegen 65 % aller Titel, dann 59 % gegen 66 %; besser als der mittlere Titel 61 %, dann nur 42 %). Passt zum Rang von 67 %, im Mittel 61 %, und zu den Tiefpunkten in Wendejahren.
- **Wenige große Treffer tragen das Ergebnis.** Die besten 10 % der Positionen machen 61 % des Gesamtergebnisses aller Positionen aus; Gewinner sind im Schnitt +23,5 %, Verlierer −15,5 %. Ohne Ausreißer nach oben ist das Ergebnis dünn. Deshalb werden Gewinner nicht vorzeitig verkauft.
- **Verkauft wird nur mit Verlust.** Alle 24 vorzeitigen Verkäufe (Notfall-Stopp, Rangabstieg) liegen im Minus; Gewinne laufen bis zum Ende. Die 130 bis zum Ende gehaltenen Positionen liegen zu 75 % im Plus, im Ganzen 64 %: Eine Trefferquote über die
  „abgeschlossenen“ Trades allein wäre irreführend (0 %). Je Jahr liegt sie zwischen 27 % (2008/09) und 100 % (2009/10, 2012/13, 2019/20).
- **Vorbehalte:** Parameter und Test nutzen dieselben 22 Jahre (Anpassung an die Vergangenheit), heutige Indexmitglieder (Überlebens-Verzerrung, die Zahlen sind eher zu gut). **Claudes eigene Prognosen** (Szenarien mit Bandbreiten je Titel) sind darin nicht enthalten und
  historisch nicht prüfbar; ihre Trefferquote zeigt erst `python -m bot.track` nach rund 4 bis 5 Wochen Betrieb (Stand jetzt: 0 gespeicherte Prognosen).

**Stil „Angriff“ für die Chance auf einen Spitzenplatz** (Dashboard, Einstellungen, „Stil“, oder `BOT_STYLE=angriff`; Standard ist „sicher“). Weil höchstens 20 % je Titel erlaubt sind, geht mehr Konzentration als 5 Titel nicht; der Stil erhöht das Risiko über die Auswahl:
5 statt 6 Titel, keine Volatilitätsbremse, auch sehr schwankende Titel (bis 150 % Volatilität), Ranking nach Momentum plus Beta. Gemessen an den 22 Planspiel-Jahren (amtliches Universum, Euro, 50.000 €, `lab.evaluate` mit den Live-Regeln):

| Stil | Ø Rang | Jahre unter den besten 10 % | Median | Ø Gewinn | schlechtestes / bestes Jahr |
|---|---|---|---|---|---|
| sicher (Standard) | 67 % (früh 70 / spät 64) | 7 von 22 | +6.553 € | +5.027 € | −6.391 € / +16.334 € |
| angriff | 72 % (früh 62 / spät 82) | 10 von 22 | +7.909 € | +10.186 € | −10.260 € / +56.478 € |

**Vorbehalte:** Es wurden sieben Varianten verglichen, eine passt leichter zufällig (Anpassung an die Vergangenheit). Der Vorteil stammt überwiegend aus den letzten elf Jahren (Tech-Boom), in den ersten elf war „sicher“ besser. Die besten Jahre sind einzelne Volltreffer
bei sehr stark gestiegenen Aktien, und die Auswahl heutiger Indexmitglieder begünstigt gerade solche Aktien. Rechne im Live-Betrieb mit einer größeren Streuung als bei „sicher“.

**Die zweite Wertung: Nachhaltigkeit.** Laut Regeln zählt dort der *Nachhaltigkeitsertrag*, die aufsummierten Kursgewinne und -verluste aller im Depot gehandelten Wertpapiere mit Stern (im amtlichen Universum die 50 Titel des
Global Challenges Index; bei Gleichstand gewinnt das Depot mit weniger Kaufaufträgen). Sie hängt also davon ab, wie viel Geld in Sterntiteln steckt, nicht vom Depot insgesamt. Bisher gab der Bot Sterntiteln nur einen Bonus von einem Punkt im Ranking, kaum
spürbar: In den Tests handelte die Strategie nur in 6 von 22 Jahren überhaupt einen Sterntitel, die Nachhaltigkeitswertung lief also praktisch ohne den Bot. **Neu ist eine Einstellung** (Dashboard, Einstellungen, „Nachhaltigkeitswertung: Plätze im Depot für Titel mit Stern“,
oder `BOT_NH_SLOTS`): Sie reserviert 0 bis 6 der 6 Depotplätze für die jeweils stärksten Sterntitel (nach Momentum). Was das kostet und bringt (`python -m bot.lab --nachhaltigkeit`, amtliches Universum in Euro, 22 Jahre, NH-Rang = Anteil zufälliger 6er-Depots aus Sterntiteln,
deren Ertrag in € die Strategie übertrifft):

| reservierte Plätze | Median | schlechtestes Jahr | Rang Gesamtwertung | Ø Nachhaltigkeitsertrag | Rang Nachhaltigkeit |
|---|---|---|---|---|---|
| **0 (Standard)** | +13,1 % | −12,8 % | **67 %** | −58 € (Sterntitel in 6 von 22 Jahren) | 26 % |
| 1 | +13,1 % | −15,6 % | 61 % | +346 € | 28 % |
| 2 | +10,0 % | −21,1 % | 59 % | +1.068 € | 34 % |
| 3 | +9,4 % | −16,0 % | 59 % | +1.856 € | 42 % |
| 4 | +10,7 % | −11,8 % | 59 % | +2.749 € | 49 % |
| 6 (alles Sterntitel) | +10,8 % | −14,4 % | 54 % | +4.013 € | 60 % |

**Ehrlich gesagt lässt sich die Nachhaltigkeitswertung nicht nebenbei mitgewinnen.** Der Ertrag wächst mit dem Geld in Sterntiteln, aber schon der erste reservierte Platz kostet 6 Punkte Rang in der Gesamtwertung, alle sechs kosten 13 Punkte, und selbst mit sechs Sterntiteln schlägt die Auswahl
nur 60 % zufälliger Sterntitel-Depots: Im kleinen Universum von 50 Titeln trägt Momentum weniger. Deshalb bleibt der **Standard bei 0** (Gesamtwertung zuerst). Wer die Nachhaltigkeitswertung bewusst angehen will, stellt auf 6, nimmt dafür etwa 13 Punkte Rang in der Gesamtwertung in Kauf und
sollte wissen, dass auch das keinen sicheren Platz in der Nachhaltigkeitswertung bringt (die Konkurrenz dort ist nicht zufällig). Ein Zwischenweg mit 1 bis 4 Plätzen hat in den Tests keinen Vorteil gezeigt.

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
- **Trading-Skills für Claude:** [tradermonty/claude-trading-skills](https://github.com/tradermonty/claude-trading-skills) (u. a. Marktbreite-Analyse, Szenario-Analyse, Steuerung der Investitionsquote),
  [quant-sentiment-ai/claude-equity-research](https://github.com/quant-sentiment-ai/claude-equity-research) (Berichtsaufbau mit Katalysator- und Risikoanalyse) und die Equity-Research-Bausteine
  von [anthropics/financial-services](https://github.com/anthropics/financial-services) (Szenarien vor Gewinnmeldungen, Katalysatorkalender, Thesen-Verfolgung). Übernommen habe ich die Ideen, die in den
  Rahmen passen: **Szenarien mit Wahrscheinlichkeiten und eine Risikomatrix** (aber mit Prognose-Bilanz, damit sich zeigt, ob sie taugen) und den Katalysatorkalender. Was sich testen ließ, habe ich getestet:
  **Marktbreite** als Signal für weniger Investition und ein **Schutzschalter** bei Depotrückgang senkten beide den Rang (Tabelle unten), sind also nicht eingebaut. Die Skill-Pakete selbst
  binde ich nicht ein: Sie sind für interaktive Analyse gebaut, viele Aufrufe kosten Abo-Limit, und ihre Ergebnisse wären wie die Modellprognosen nicht an der Vergangenheit prüfbar.
- **Planspiel-Sieger** setzten laut [Presseberichten](https://www.dsgv.de/newsroom/presse/20220131_PM_Spielende_Planspiel_Boerse_03.html) auf Trend und starke Titel (US-Großwerte, Halbleiter,
  Rüstung) und stiegen um etwa 25 bis 40 %. Das deckt sich mit der Momentum-Auswahl. Jahreszeitliche Muster (Weihnachtsrally, Januar-Effekt) sind nur schwach belegt
  und wurden nicht eingebaut.

### Weitere Daten: Zinsen, Konjunktur, Bilanzen, Insider, Analysten, Stimmung, Risiko

Der Bot betrachtet zusätzlich diese Daten. **Nur Claude sieht sie, die feste Berechnung nutzt sie nicht.** Grund: Was sich nicht an der Vergangenheit prüfen lässt, darf die Auswahl
nicht steuern. Meine erste Version mit vielen ungeprüften Zusatzregeln lag bei 46 % Rang, die einfache bei 81 % (beides im damaligen Test mit 214 Titeln; am amtlichen Universum in Euro sind es 67 %). Als Grund für ein Veto (Kauf streichen) zählt nur ein gemessener Befund:
Nachrichtenlage −1 oder −2, Termin oder Gewinnmeldung in den nächsten Tagen, festes Übernahmeangebot, schweres Bilanz-Warnsignal oder deutlich gesenkte Analystenschätzungen.
Claudes eigene Meinung (Szenarien, Risikoeinschätzung) zählt nie, sonst könnte er Vetos mit seiner eigenen Vermutung begründen.

| Daten | Quelle | Was genau | Getestet? | Wirkung |
|---|---|---|---|---|
| **Zinsen und Konjunktur** | FRED, EZB (frei, ohne Schlüssel) | Zinskurve, Kreditaufschläge (Baa), 10-jährige Rendite, Fed-Zins, EZB-Einlagesatz, Arbeitslosigkeit (Sahm-Regel), Inflation | **Ja**, über 22 Jahre | keine Verbesserung (Tabelle unten); Claude sieht die Lage und soll deswegen **nicht** in Cash gehen |
| **Bilanzen im Detail** | Yahoo (letzte Quartale) | Nettoverschuldung zu EBITDA, Zinsdeckung, Liquidität, Eigenkapital, freier Cashflow, Marge, Piotroski-Score | Nein, Yahoo hat keine Historie mit Veröffentlichungsstand | Nur ein **schweres** Warnsignal zählt als Beleg für ein Veto von Claude |
| **Insider-Geschäfte (SEC)** | SEC EDGAR, Meldung „Form 4“ (offiziell, kostenlos, nur US-Aktien) | offene Marktkäufe und -verkäufe der Führungskräfte der letzten 90 Tage, geplante Verkäufe (Rule 10b5-1) getrennt gezählt, „Cluster“ = mehrere Führungskräfte kaufen innerhalb von 30 Tagen | Nein (ein Test über 22 Jahre wäre möglich, hätte aber sehr wenige Ereignisse je Titel) | nur Information: Cluster-Käufe gelten in der Forschung als schwach positiv, Verkäufe sind kaum aussagekräftig. **Braucht deinen Namen und deine E-Mail** (verlangt die SEC im Abruf), im Dashboard unter Einstellungen; ohne sie bleibt das aus. Dazu: Yahoo-Überblick und Web-Recherche (BaFin für deutsche Titel). |
| **Analysten-Schätzungen** | Yahoo | Änderung der Gewinnschätzungen (30 und 90 Tage), Zahl der Erhöhungen und Senkungen, Heraufstufungen und Herabstufungen, Anteil der Kaufempfehlungen, Streuung der Kursziele | Nein, Yahoo liefert nur den heutigen Stand, keine Historie | Die Richtung der Schätzungsänderungen („Earnings Revisions“) zählt zu den am besten belegten Signalen der Forschung. **Nur ein deutlicher Rückgang** (Schätzung fürs laufende Jahr −5 % in 30 Tagen, mindestens 3 Senkungen, höchstens 1 Erhöhung) zählt als Beleg für ein Veto, alles andere ist Information. |
| **Social-Media-Stimmung** | StockTwits (öffentlich, ohne Schlüssel, nur US-Aktien), **Reddit-Erwähnungen über ApeWisdom** (frei, US-Aktien) und Web-Recherche über dein Abo | StockTwits: Anteil „Bullish“ zu „Bearish“ in den letzten 30 Beiträgen (nur Zahlen, kein Fremdtext). Reddit: Rang und Zahl der Erwähnungen in 24 Stunden, „auffällig“ bei Rang bis 20 oder verdoppelten Erwähnungen. Dazu Funde aus Foren und X | Nein (keine Vergangenheit abrufbar) | nur Information, weder Kauf- noch Veto-Grund (leicht manipulierbar, oft ein Gegenindikator oder zu spät; der Bullish-Anteil liegt bei fast allen Titeln über 70 %, in einer Stichprobe von 6 großen US-Titeln bei 73 bis 92 %). Reddit selbst sperrt Programme (403), das wird nicht umgangen. |
| **Risikoprofil** | eigene Rechnung aus den Kursen | Jahresschwankung, größter Rückgang der letzten 12 Monate, 10-Tage-Verlust, der in 95 % der Zeiträume nicht überschritten wurde (Value at Risk), Stufe 1 bis 5 | Teilweise: Gewichtung nach Volatilität ist getestet und senkte den Rang | nur Einordnung für Claude, kein Grund zur Abweichung; die Positionsgröße berücksichtigt die Marktschwankung schon |
| **Szenarien und Risikomatrix** | Claude über die Websuche | Aufwärts-, Basis- und Abwärtsszenario für 3 Monate mit Wahrscheinlichkeit und Rendite; die wichtigsten Risiken nach Wahrscheinlichkeit × Auswirkung. Der Code rechnet daraus die erwartete Rendite und eine Risikoeinschätzung aus | Nicht an der Vergangenheit prüfbar, **wird ab dem ersten Lauf gemessen** (nächster Abschnitt) | nur Information; erst eine positive Bilanz erlaubt Claude, sie zur Wahl zwischen ähnlich platzierten Titeln zu nutzen |
| **Quiver Quantitative** (optional, kostenpflichtig) | Quiver-Schnittstelle, US-Aktien | Kongress-Handel, Regierungsaufträge, Lobbyausgaben, Wikipedia-Aufrufe, außerbörslicher Leerverkaufsanteil | Nein; **nicht einmal die Anbindung ist gegen die echte Schnittstelle geprüft** (ohne bezahlten Schlüssel nicht möglich) | nur Information, weder Kauf- noch Veto-Grund. Abschnitt „Quiver Quantitative und Liquid“ |

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

**Zwei weitere Überlagerungen aus den Trading-Skills** (gleiche Testanlage wie oben, bei Auslösung höchstens 50 % investiert; Nachrechnen: `python -m bot.lab --overlays`):

| Überlagerung | Median | Rang | schlechtestes Jahr |
|---|---|---|---|
| **ohne (Standard, mit Volatilitäts-Skalierung)** | **+17,4 %** | **81 %** | **−9,9 %** |
| Marktbreite (Anteil der Titel über ihrer 200-Tage-Linie) unter 30 % | +16,6 % | 80 % | −9,9 % |
| … unter 40 % | +16,6 % | 76 % | −13,9 % |
| … unter 50 % | +16,6 % | 74 % | −8,9 % |
| Marktbreite (über der 50-Tage-Linie) unter 30 % | +16,9 % | 76 % | −14,1 % |
| … unter 40 % | +16,9 % | 72 % | −18,3 % |
| Schutzschalter: Depot 8 % unter dem Höchststand | +15,0 % | 74 % | −10,9 % |
| … 10 % unter dem Höchststand | +17,4 % | 76 % | −13,9 % |
| … 15 % unter dem Höchststand | +17,4 % | 80 % | −9,9 % |

Keine der beiden Überlagerungen verbessert den Rang, mehrere verschlechtern sogar das schlechteste Jahr: Wer nach einem Rückgang Positionen abbaut, verpasst die Erholung.
Der Schutzschalter mit 15 % löste nur selten aus und liegt deshalb nahe am Standard. Beide sind nicht eingebaut. Auch hier gilt: kein Beleg für einen Nutzen, nicht: sicher nutzlos.

### Prognose-Bilanz: taugen Claudes Prognosen? (`python -m bot.track`)

Die Recherche liefert je Titel ein **Aufwärts-, Basis- und Abwärtsszenario** für die nächsten 3 Monate (mit Wahrscheinlichkeit und Rendite) und eine **Risikomatrix** (die wichtigsten Risiken mit
Wahrscheinlichkeit 1 bis 5 mal Auswirkung 1 bis 5). Der Code rechnet daraus im Protokoll sichtbar die **erwartete Rendite** (Wahrscheinlichkeiten müssen zusammen 90 bis 110 ergeben, sonst
wird sie verworfen) und eine **Risikoeinschätzung** (höchstes Produkt: ab 15 von 25 „hoch“, ab 8 „mittel“) aus. Das sind Schätzungen eines Sprachmodells und an der Vergangenheit nicht prüfbar.

Damit sich trotzdem zeigt, ob sie etwas taugen, speichert der Bot **jede Prognose** (`data/forecasts.json`) und trägt nach 14, 28 und 56 Tagen ein, wie der Kurs sich entwickelt hat.
`python -m bot.track` zeigt Trefferquote der Richtung und **Rangkorrelation** (ordnet Claude die Titel in der richtigen Reihenfolge?) sowie das mittlere Ergebnis der oberen und unteren Hälfte.
Ab 30 ausgewerteten Prognosen bekommt Claude diese Bilanz in den Kontext (`prognose_bilanz`) und hat die Anweisung: Fehlt sie oder liegt die Rangkorrelation bei null oder darunter, tragen die
Prognosen keine Entscheidung; ist sie klar positiv, dürfen sie höchstens zwischen ähnlich platzierten Titeln der Top 25 entscheiden. Als Grund für ein Veto zählen sie nie.
Die ersten belastbaren Zahlen gibt es nach rund 4 bis 5 Wochen Betrieb (bis dahin fehlen 28 Tage Kursentwicklung). Richtige Erwartung: Vorhersagen einzelner Kurse über 3 Monate sind
auch für Fachleute schwer, es kann sein, dass die Bilanz „wertlos“ zeigt. Dann haben die Prognosen nichts gekostet außer Abo-Limit.

### Quiver Quantitative und Liquid (optional, beides mit Vorbehalt)

**Quiver Quantitative** ([quiverquant.com](https://www.quiverquant.com)) liefert Alternativdaten zu US-Aktien. Die Schnittstelle ist kostenpflichtig (nach meiner Recherche ab 30 $ im Monat,
welche Datensätze dabei sind, hängt vom Tarif ab). Ohne Schlüssel ruft der Bot nichts ab. Mit Schlüssel (Dashboard, Einstellungen, „Quiver-Schlüssel“, oder `QUIVER_API_TOKEN`) holt er für die
US-Titel der engeren Auswahl fünf Datensätze (Kongress-Handel, Regierungsaufträge, Lobbyausgaben, Wikipedia-Aufrufe, außerbörslicher Leerverkaufsanteil, `bot/quiver.py`), fasst sie zu
Zahlen zusammen und gibt sie als Information an Claude. **Ehrlich:** Ich konnte die Anbindung nicht gegen die echte Schnittstelle prüfen, dazu braucht es einen bezahlten Schlüssel.
Endpunkte und Anmeldung stammen aus dem öffentlichen Quellcode des Pakets `quiverquant`, die Feldnamen der Antworten werden tolerant gelesen. Sieh beim ersten Lauf ins Protokoll (Zeile
„Zusatzdaten für Claude“). **Mein Rat: sparen.** Der Kongress-Handel ist in der Forschung nach dem STOCK Act nur schwach und umstritten belegt, und die besser belegte Insider-Quelle (SEC Form 4)
ist kostenlos und schon eingebaut.

**Liquid** ([liquid.trade](https://liquid.trade)) ist eine Handelsplattform für **echtes Geld** (Perpetuals, Spot, Prognosemärkte,
nach eigener Darstellung 500+ Märkte), kein Planspiel und keine Aktien des Planspiels. Der Bot kann darüber das Planspiel nicht handeln. Die einzige programmierbare Schnittstelle ist der
„Co-Invest“-Server nach dem MCP-Standard (`https://coinvest.liquid.trade/mcp`): Anmeldung per OAuth 2.1, zwei Umfänge (`read` und `trade`), jede Änderung braucht einen Bestätigungs-Tipp von dir,
dazu ein Übungsmodus mit 10.000 $. Eine öffentliche REST-Schnittstelle gibt es laut Liquid nicht. Die Werkzeugliste holt der Server erst nach der Anmeldung aus dem Backend, ich konnte sie nicht sehen.

Was ich gebaut habe (`bot/mcp.py`), ist deshalb eine **allgemeine, optionale Nur-Lese-Anbindung** für die Recherche-Stufe: Falls Liquid Werkzeuge für Marktdaten anbietet (Preise, Finanzierungsraten,
Stimmung), kann Claude sie beim Recherchieren nachschlagen. Handeln kann der Bot darüber nie. Die Sperren, die zusammenwirken:
1. Ohne Einstellung wird **gar kein** MCP-Server geladen (`--strict-mcp-config` mit leerer Liste), auch nicht die, die du sonst für Claude eingerichtet hast. Die Entscheidungsstufe lädt nie einen.
2. Freigegeben ist nur, was du einzeln mit vollem Namen einträgst, ohne Platzhalter. Der Name muss mit `get`, `list`, `search`, `read`, `fetch`, `query` oder `describe` beginnen und darf kein Wort wie
   `place`, `buy`, `sell`, `trade`, `transfer`, `close`, `cancel`, `set`, `update`, `withdraw` enthalten. Alles andere wird abgelehnt.
3. In der Konfiguration sind nur Server über https erlaubt, keine lokalen Programme.
4. `--permission-mode dontAsk`: Alles, was nicht freigegeben ist, wird abgelehnt. **Nachgeprüft** mit einem Attrappen-Server (ein lesendes und ein „handelndes“ Werkzeug), Claude sollte beide aufrufen:
   die CLI meldete `place_order` unter `permission_denials`, der Server sah nur den lesenden Aufruf. `python scripts/check_mcp_denial.py` wiederholt das auf deinem Rechner (ein Aufruf, rund ein Cent Nutzungslimit), sinnvoll nach jedem Update der CLI.
5. **Erteile bei der Anmeldung nur den Umfang „read“.** Das ist die wichtigste Sperre, denn sie liegt außerhalb meines Codes.
Eine falsche Einstellung führt nicht zum Abbruch, sondern zu einer Recherche ohne MCP, mit Hinweis im Protokoll.

**Nicht gegen Liquid getestet**, weil dafür deine Anmeldung nötig ist: Geprüft sind die Sperren (Namensregeln in Tests, Rechteverwaltung der CLI mit der Attrappe), nicht die Verbindung zu Liquid. **Nutzen: gering**, höchstens Stimmung oder Marktlage
aus einem anderen Markt, Aktien des Planspiels sind dort nicht handelbar. Mein Rat: für das Planspiel nicht einrichten. Wenn du es doch willst:
1. `claude mcp add --transport http liquid https://coinvest.liquid.trade/mcp`, dann in Claude Code `/mcp`, „liquid“ wählen und anmelden, **nur „read“ erteilen**. (Im Docker-Container geschieht das im
   Container, `docker compose exec dashboard claude`, und geht beim Neubau verloren.)
2. Die Werkzeugnamen ansehen (`/mcp`, Form `mcp__liquid__…`) und nur **Marktdaten-Werkzeuge** wählen, keine Konto- oder Depot-Abfragen (sonst gehen deine privaten Kontodaten in die Recherche).
3. Datei `data/mcp_readonly.json`: `{"mcpServers": {"liquid": {"type": "http", "url": "https://coinvest.liquid.trade/mcp"}}}`.
4. In `.env`: `BOT_RESEARCH_MCP_CONFIG=data/mcp_readonly.json` und `BOT_RESEARCH_MCP_TOOLS=mcp__liquid__<werkzeug1>,mcp__liquid__<werkzeug2>`. Dashboard neu starten.

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
| Kronos-small, 2023–2024 (evtl. im Training) | −0,048 (10 Tage), −0,059 (20 Tage, t = −2,0) | +0,087 / +0,118 |

Beide Modelle haben damit **keine Vorhersagekraft** gezeigt. Kronos-small liegt sogar leicht im Minus (die Reihenfolge der Prognosen war eher umgekehrt zur späteren
Rendite). Neben dem Momentum bringt es keinen Zusatznutzen (Koeffizient +0,17 Prozentpunkte, t = 0,2), und als Neusortierung der 15 Momentum-Favoriten
verbessert es die Auswahl nicht (Mix 50/50: −0,22 Prozentpunkte gegenüber reinem Momentum, t = −0,6). Die Prognosen sind zudem stark verzerrt:
im Schnitt −5,4 % über 10 Tage bei tatsächlich +0,8 %, in einer Spanne von −63 % bis +55 %.

Ein Detail, das gegen voreilige Schlüsse hilft: Im früheren Zeitraum (2023–2024, evtl. im Training) hatte Kronos-small neben dem Momentum bei 20 Tagen einen positiven Zusatzbeitrag
(+2,15 Prozentpunkte, t = 2,3), in den ungesehenen Daten aber nicht (+0,07, t = 0,1), und das Vorzeichen der Neusortierung der Favoriten wechselte zwischen beiden Zeiträumen
(+0,65 gegen −0,23 Prozentpunkte). Ein Effekt, der nur dort auftritt, wo das Modell die Daten womöglich kennt, ist kein verlässliches Signal. Bei vier Zusatztests je Zeitraum
ist ein einzelner t-Wert über 2 zudem auch Zufall. Die Trainingsdaten von Kronos haben kein veröffentlichtes Enddatum. Ein fairer Test ist deshalb nur für Zeiträume nach Erscheinen des Papiers
(August 2025) möglich, das sind nur rund 13 Monate. Solange ein Test keinen Nutzen zeigt, bleibt `kronos_weight` auf 0 und Kronos ausgeschaltet.

### Werkzeug-Check: Datenquellen, Bausteine und Modelle aus dem Internet (Stand 29.9.2026)

Eine Liste bekannter Werkzeuge für Daten, Backtests, Prognosen und Hilfsmittel habe ich einzeln daraufhin geprüft, ob sie dem Bot nützen. **Getestet** heißt: im selben Labor über die 22 Planspiel-Jahre, mit der Regel, dass nur eine
belegte Verbesserung in die Strategie darf. Alles andere ist begründet, nicht getestet, und so gekennzeichnet.

| Werkzeug | Was es kann | Für den Bot |
|---|---|---|
| **yfinance** | Kurse, Kennzahlen, Schätzungen von Yahoo (inoffiziell) | Hauptquelle, bleibt. Schwäche: inoffiziell und gelegentlich gedrosselt. Fehlen Kurse, handelt der Bot in diesem Lauf nicht. |
| **FRED, EZB** | Zinsen, Konjunktur | schon eingebaut, Test: keine Verbesserung (siehe oben) |
| **OpenBB** | bündelt viele Datenquellen (Yahoo, FRED, SEC, ...) | nicht eingebaut: Die freien Quellen sind einzeln angebunden, die übrigen brauchen Schlüssel. |
| **Alpha Vantage, Finnhub, Twelve Data** | freie Tarife mit Schlüssel und Limits (25 Abrufe/Tag, 60/Minute, 800/Tag) | nicht eingebaut: Yahoo und SEC liefern dasselbe ohne Schlüssel. Finnhub wäre die erste Wahl als Zweitquelle, falls Yahoo länger ausfällt. |
| **Destatis, EZB-Portal** | deutsche und europäische Statistik | kein belegter Nutzen für die Auswahl (Makro-Test), nicht eingebaut |
| **Alpaca, CCXT, Freqtrade** | US-Broker mit Paper-Trading, Krypto-Börsen, Krypto-Bot | nicht nutzbar: Das Planspiel läuft bei der Sparkasse, Krypto gibt es dort nur im Trainingsdepot |
| **Backtrader, vectorbt, Backtesting.py, Zipline, NautilusTrader, QuantConnect LEAN** | Backtest-Gerüste | Das eigene Labor bildet das Planspiel genau nach (Fenster 1.10. bis 25.1., Gebühr 0,3 % mind. 15 €, Ausführung zum Eröffnungskurs des Folgetags, Rang gegen Zufallsdepots). Ein Wechsel brächte nichts. |
| **scikit-learn, XGBoost, LightGBM** | Vorhersagemodelle auf Tabellen | **getestet, schlechter als Momentum** (unten) |
| **Chronos, TimesFM, Lag-Llama** (Zeitreihen-Modelle) | vortrainiert, sagen Kurse voraus | **Chronos getestet, keine verlässliche Vorhersagekraft** (unten); TimesFM laut Fachliteratur ebenso ohne Nutzen (unten, nicht selbst getestet); Lag-Llama nicht geprüft |
| **PyPortfolioOpt, Riskfolio-Lib** | Portfolio-Optimierung (Minimum-Varianz, HRP, Risikoparität) | **getestet, kein Vorteil** (unten): gleiche Gewichte bleiben |
| **PyTorch, TensorFlow** | Deep Learning | keine eigene Verwendung; Kronos und Chronos laufen darauf |
| **Prophet, statsmodels, sktime, Darts** | klassische Zeitreihenprognose | nicht getestet: Trendfortschreibung ist im Kern Momentum, das der Bot schon hat |
| **FinRL, Stable-Baselines3** | Reinforcement Learning | nicht getestet: braucht sehr viele Daten und überanpasst bei 22 Zeiträumen leicht |
| **FinBERT** | Stimmung aus Finanztexten | nicht eingebaut: Claude liest die Nachrichten selbst und meldet die Stimmung; für einen Test fehlt eine Nachrichten-Historie |
| **Qlib** (Microsoft) | Forschungsplattform mit Merkmalssammlung (Alpha158) | nicht nötig: Der LightGBM-Test nutzt ähnliche Merkmale |
| **pandas-ta, TA-Lib** | technische Indikatoren | nicht nötig: Die Kennzahlen sind in `bot/signals.py` selbst berechnet und getestet |
| **Optuna** | automatische Parameter-Suche | nicht eingebaut: 22 Zeiträume reichen für eine Feinabstimmung nicht, ohne dass sie überanpasst. Die Grundeinstellungen sind flach (Haltegrenze 30 bis 100 %: Rang 67 bis 69 %). |
| **MLflow, SQLite, PostgreSQL, DuckDB** | Experimente und Daten verwalten | nicht nötig: JSON-Dateien genügen |

**Gradient-Boosting (LightGBM) gegen Momentum** (`python scripts/experiment_ml.py`, 19 Planspiel-Jahre 2007 bis 2025, Testuniversum): Für jedes Jahr wurde ein Modell nur mit Daten trainiert, deren 80-Tage-Ergebnis vor dem Start feststand
(28 Merkmale wie Renditen über 5 bis 250 Tage, Abstand zu Durchschnittslinien, Volatilität, Beta, jeweils als Rang unter allen Titeln), und dann in der Strategie eingesetzt.

| Variante | Median | schlechtestes Jahr | Rang (früh / spät) |
|---|---|---|---|
| **Momentum (Standard)** | +15,7 % | **−9,9 %** | **78 %** (70 / 86) |
| LightGBM, reiner Modell-Rang (28 Merkmale) | +12,6 % | −22,3 % | 56 % (54 / 58) |
| LightGBM, reiner Modell-Rang (8 Merkmale) | +12,9 % | −16,1 % | 66 % (63 / 69) |
| LightGBM, die 6 Besten aus den Top 15 des Momentum nach Modell | +15,0 % | −15,7 % | 73 % (67 / 78) |
| LightGBM, Top 15 des Momentum halb nach Modell neu sortiert | +11,9 % | −15,7 % | 69 % (59 / 79) |
| Ridge-Regression (linear), 28 Merkmale | +14,5 % | −18,7 % | 59 % (59 / 59) |

Die sechs besten Titel nach Modell erzielten im Mittel eine ähnliche Überrendite wie die nach Momentum (etwa +6 bis +7 Prozentpunkte über 80 Tage, überlappende Zeiträume, deshalb sind die t-Werte zu hoch), aber mit deutlich größeren
Ausschlägen nach unten: In der Strategie sinkt der Rang, und das schlechteste Jahr wird bis zu mehr als doppelt so schlecht. **Kein Beleg für einen Vorteil, dafür mehr Aufwand und Risiko: nicht eingebaut.** Auch Qlibs eigener Vergleich
für LightGBM auf 158 Merkmalen (chinesischer CSI 500) zeigt nur einen Informationskoeffizienten von etwa 0,04: ein kleiner Vorsprung für viel Aufwand.

**Chronos gegen Momentum** (`python scripts/experiment_foundation.py`, 60 zufällige Titel, Rangkorrelation der Prognose mit der tatsächlichen Rendite je Tag, Mittelwert und t-Wert):

| Modell | 10 Tage: nach Aug. 2025 | 2023-2024 | 2018-2022 | 20 Tage: nach Aug. 2025 | 2023-2024 | 2018-2022 |
|---|---|---|---|---|---|---|
| Chronos-Bolt small | +0,033 | +0,041 | +0,004 | +0,004 | +0,055 | −0,003 |
| Chronos-Bolt base | −0,013 | +0,008 | −0,011 | −0,014 | −0,007 | −0,031 |
| Chronos-2 | −0,001 | +0,003 | −0,016 | +0,011 | +0,047 | −0,029 |
| **Momentum** | **+0,070** | **+0,069** | **+0,024** | **+0,089** | **+0,106** | **+0,013** |

Keines der Modelle ist in allen Zeiträumen positiv, das größere Bolt-Modell und Chronos-2 liegen um null, und Momentum ist durchweg besser. Die einzelnen Ausschläge (Bolt small 2023-2024, Chronos-2 bei 20 Tagen 2023-2024)
können Zufall oder Kenntnis der Trainingsdaten sein; ein Effekt, der nicht in den ungesehenen Daten nach August 2025 auftaucht, gilt nicht. Zusammen mit Kronos (oben) sind damit fünf vortrainierte Zeitreihenmodelle geprüft
(Kronos mini und small, Chronos-Bolt small und base, Chronos-2), ohne Nutzen. Die Fachliteratur sagt dasselbe: [Re(Visiting) Time Series Foundation Models in Finance](https://arxiv.org/abs/2511.18578) prüfte Chronos in fünf und
TimesFM in zwei Größen an täglichen Renditen und fand für alle deutlich negative Bestimmtheitsmaße außerhalb der Stichprobe (das beste, Chronos small, −1,27 %; TimesFM schlechter), weit hinter einem einfachen CatBoost-Modell.
[Pretrained Time-Series Foundation Models for Financial Return Forecasting](https://arxiv.org/abs/2606.27100) kommt zum Schluss, solche Modelle seien nützliche Vorannahmen, aber keine verlässliche Quelle für Überrendite.

**Gewichtung der Positionen** (`python scripts/experiment_weights.py`, gleiche Anlage wie die Tabellen zum Volatilitäts-Test, gewichtet nur bei Käufen, zwischen dem 0,6- und 1,17-fachen eines gleichen Anteils):

| Gewichtung | Median | schlechtestes Jahr | Rang (früh / spät) |
|---|---|---|---|
| **gleich (Standard)** | +17,4 % | −9,9 % | **81 %** (76 / 86) |
| inverse Schwankung | +16,2 % | −9,9 % | 81 % (77 / 85) |
| Minimum-Varianz (geschrumpfte Kovarianz) | +16,6 % | −9,4 % | 82 % (77 / 86) |
| HRP (hierarchische Risikoparität) | +17,0 % | −9,3 % | 81 % (77 / 85) |
| nach Momentum | +18,8 % | −9,6 % | 81 % (75 / 86) |

Der Rang bleibt gleich, die Unterschiede liegen im Rauschen. Das deckt sich mit der Fachliteratur: In [DeMiguel, Garlappi und Uppal](https://academic.oup.com/rfs/article-abstract/22/5/1915/1592901) schlug keines von 14 Optimierungsverfahren
die gleiche Gewichtung 1/N verlässlich. **Gleiche Gewichte bleiben**, sie sind einfach, robust und kosten nichts.

## Dashboard fürs Handy

Das Dashboard ist eine kleine Web-App, die zusammen mit dem Bot auf einem Rechner läuft, der dauerhaft an ist
(Raspberry Pi, Mini-PC, günstiger Server). Ein Handy kann den Bot nicht selbst ausführen, es bedient ihn nur im Browser.

| Tab | Inhalt |
|---|---|
| Übersicht | Depotwert, Verlauf, Cash, Positionen mit Gewinn/Verlust, Zähler für die Mindest-Käufe |
| Steuerung | **Start** (Zeitplan an), **Stopp** (Notaus, bricht laufenden Lauf ab), Jetzt ausführen, Selbsttest, **Wertpapierliste des Planspiels laden**, Umschalter Trockenlauf/Live, Ausgabe |
| Protokoll | Jede Entscheidung mit Begründung, geladene Zusatzdaten, ausgeführte und abgelehnte Orders (Verbrauch der KI-Aufrufe steht im JSON-Protokoll in `logs/`) |
| Einstellungen | Planspiel-Login, Claude-Token, SEC-Kontakt, Quiver-Schlüssel (optional), Uhrzeiten, Modell, `selectors.json`, `universe.json` |

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
getestet (`pytest`, 291 Tests) und liefen mit echten Yahoo-Daten (auch mit dem amtlichen Universum: Import der Liste, Zuordnung der ISIN, Euro-Umrechnung, ein ganzer Trockenlauf). Die Aufrufe von `claude -p` (Recherche in Paketen, Entscheidung mit Schutzgeländer, Schema, Websuche) habe ich
in der Entwicklungsumgebung mit dem echten Claude Code durchgespielt, ein vollständiger Trockenlauf mit echten Daten ist gelaufen. **Nicht getestet** sind die Live-Ausführung auf der
Plattform (braucht deinen Team-Login und die aufgezeichneten Selektoren), die Anmeldung mit *deinem* Token aus `claude setup-token` (der Aufruf ist derselbe, das Token kenne ich nicht),
die SEC-Abfrage mit deinen Kontaktdaten (mit einer Attrappe getestet, früher mit echten Daten geprüft), Quiver und Liquid. Dafür gibt es den Selbsttest (Schritt 5), der ohne Order prüft,
ob alles funktioniert. Erst danach live gehen.

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
- **Optional, aber empfohlen:** Im Dashboard (Einstellungen) bei „Kontakt für die SEC-Insiderdaten“ deinen Namen und deine E-Mail-Adresse eintragen (z. B. `Max Muster max@example.org`). Die SEC verlangt
  eine solche Kennung bei automatischen Abfragen. Ohne sie ruft der Bot die kostenlosen Insider-Meldungen nicht ab (Umgebungsvariable `SEC_USER_AGENT`). Die Adresse wird nur an die SEC gesendet.

### 2. Wertpapieruniversum
**Das erledigt der Bot für dich, mit der amtlichen Liste des Planspiels:** Im Dashboard Tab Steuerung **Wertpapierliste des Planspiels laden** drücken (dauert 1 bis 2 Minuten, die Ausgabe erscheint darunter), oder auf dem Rechner
`python -m bot.universe_tool official` (im Docker-Container: `docker compose exec dashboard python -m bot.universe_tool official`). Er lädt die aktuelle Liste von planspiel-boerse.de, ordnet jeder ISIN das Yahoo-Symbol und die Währung zu und schreibt
`data/universe.json` mit echten ISIN und Nachhaltigkeits-Kennzeichen (Einzelheiten und Testergebnis im Abschnitt „Amtliche Wertpapierliste, Euro-Umrechnung ...“). Die mitgelieferte Datei ist der Stand vom 29.9.2026 (517 Aktien);
**lade die Liste vor dem Start und gelegentlich danach neu**, weil sie sich ändern kann. Die Ausgabe nennt jeden Titel, der entfällt (kein Börsenkürzel, keine aktuellen Kurse).
- Ohne Internetzugang zur Liste: PDF oder Text der Liste selbst herunterladen und angeben: `python -m bot.universe_tool official liste.pdf` (braucht `pdftotext`, Paket poppler-utils; im Docker-Image enthalten).
- Nur zum Vergleich: `python -m bot.universe_tool tested` erzeugt das frühere Testuniversum (214 Titel, ISIN teils Symbol als Platzhalter). Eigene Listen: `python -m bot.universe_tool import meine_liste.csv` (Spalten `isin,name,stars,yf`).
- Die Order sucht nach der ISIN (`{isin}` bzw. `{search}`); nimmt das Suchfeld der Plattform keine ISIN an, stelle in `selectors.json` auf `{name}` um.

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
1. **Selbsttest** (Tab Steuerung): prüft Universum (amtliche Liste?), Marktdaten samt Euro-Umrechnung, Claude, die optionalen Zusatzdaten und den Plattform-Login samt Depot-Auslesen.
   **Alles muss `[ OK ]` zeigen.** Ohne Dashboard: `python -m bot.selftest` mit gesetzten Umgebungsvariablen.
2. **Trockenlauf:** Standardmodus, bucht nur lokal. Lass ihn ein paar Tage laufen und lies die Begründungen im Tab Protokoll.
3. **Live schalten:** Tab Steuerung → Modus → „auf Live“, `LIVE` eingeben. Beobachte die ersten Läufe in der Plattform.
   Zurück oder anhalten: „auf Trockenlauf“ bzw. **Stopp**.

Alternative ohne Dashboard: GitHub Actions (`.github/workflows/trade.yml`, Secrets `ANTHROPIC_API_KEY`, `PSB_USER`,
`PSB_PASSWORD`, Variable `BOT_LIVE`; Cron-Trigger dort wieder einkommentieren, Branch in den Default-Branch mergen).

## Sicherheitsnetz
- Kann das Depot nicht gelesen werden, wird nicht gehandelt. Nach jeder Order wird das Depot neu gelesen.
- Positionsgrenze 19 %, Mindestorder 5.000 €, max. 6 Orders pro Lauf, max. 2 Titel je Branche, Mindesthaltedauer 3 Tage (Notfall-Stopps ausgenommen).
- Kurse in Euro (fehlt ein Wechselkurs, wird der Titel nicht gehandelt); Kursdaten werden von offensichtlichen Fehlern bereinigt; Titel mit einer Tagesbewegung über 50 % in den letzten 300 Handelstagen werden nicht gehandelt.
- Die KI-Aufrufe laufen ohne Werkzeuge (Entscheidung) bzw. nur mit Websuche (Recherche), in einem leeren Ordner, ohne API-Key und **ohne MCP-Server**, außer den einzeln freigegebenen Nur-Lese-Werkzeugen (siehe oben).
- Zugangsdaten nur im Dashboard-Ordner `state/` bzw. als GitHub-Secrets, nie im Repo.

## Dateien
`bot/run.py` Ablauf · `bot/signals.py` Kennzahlen · `bot/fundamentals.py` Fundamentaldaten · `bot/research.py` Web-Recherche ·
`bot/brain.py` Claude-Entscheidung mit Schutzgeländer · `bot/journal.py` Gedächtnis · `bot/rules.py` Regelstrategie ·
`bot/lab.py` Test in Planspiel-Jahren · `bot/backtest.py` Backtest-Grundlage · `bot/universes.py` Testtitel · `bot/macro.py` Zinsen und Konjunktur · `bot/statements.py` Bilanzen und Insider · `bot/social.py` Stimmung (StockTwits, Reddit) · `bot/edgar.py` Insider-Geschäfte (SEC) · `bot/analysts.py` Analystenschätzungen · `bot/quiver.py` Quiver (optional) · `bot/track.py` Prognose-Bilanz · `bot/mcp.py` Nur-Lese-MCP (optional) · `bot/kronos_signal.py` Kronos (optional) · `bot/risk.py` Risikoregeln · `bot/executor.py` Trockenlauf und Plattform ·
`bot/universe_tool.py` Universum · `bot/official.py` amtliche Wertpapierliste · `bot/fx.py` Euro-Umrechnung · `scripts/` Experimente zum Nachrechnen (ML, Chronos, Gewichtung) und die MCP-Prüfung · `bot/selftest.py` Prüfung · `.github/workflows/trade.yml` Zeitplan (Werktags 3× UTC).
