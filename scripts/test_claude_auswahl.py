"""Wählt Claude besser als die Regeln?  python scripts/test_claude_auswahl.py   (ca. 1 Minute, braucht ein angemeldetes Claude Code, Verbrauch rund 0,8 $ Rechenwert)

Zu jedem der 22 Planspiel-Starts (1.10. seit 2004, amtliches Universum, Euro) bekommt Claude die 40 stärksten Kandidaten nach Momentum, anonymisiert ("Titel 01" bis "Titel 40", gemischt), nur mit
Kurskennzahlen, ohne Namen, Datum und Nachrichten (sonst könnte er sein Wissen über die Vergangenheit ausnutzen). Er wählt 6. Verglichen wird das Kaufen und Halten über 80 Handelstage mit der Auswahl
der Regeln, dem Durchschnitt der 40 Kandidaten und dem Durchschnitt aller Titel; dazu der Rang gegen zufällige 6-Titel-Depots. Prüft nur die Kurs-Auswahl, nicht Claudes Recherche und Nachrichtenkenntnis:
dafür gibt es keine historischen Daten, das misst der Bot im Betrieb selbst (bot/shadow.py).
Zwei Läufe (Claudes Antworten schwanken von Lauf zu Lauf): Claude +10,9 % und +13,3 %, Regeln +10,2 %, Ø 40 Kandidaten +11,0 %, Ø alle Titel +6,7 %; Rang 63 % und 61 % gegen 67 %;
Vorsprung +0,6 % (t = 0,24) und +3,0 % (t = 0,89): in beiden Läufen kein sicherer Unterschied. Der Mehrertrag von Claude im zweiten Lauf kommt fast nur aus einem Jahr (2024/25: +67,6 % statt +22,2 %)."""
import os
import random
import sys
import time
import warnings
from concurrent.futures import ThreadPoolExecutor

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from bot import backtest as bt, brain, lab, rules  # noqa: E402

warnings.filterwarnings("ignore")
SYSTEM = """Du wählst für ein Papierdepot 6 von 40 anonymisierten Aktien ("kandidaten"), die in den nächsten rund 16 Wochen (80 Handelstage) am besten abschneiden sollen, gemessen an der Rendite gegenüber dem Durchschnitt aller Aktien.
Du siehst nur Kurskennzahlen (Renditen über 5/20/60/120 Tage und 12-1 Monate, Schwankung, RSI, Abstand zum 52-Wochen-Hoch, Stärke gegen den Markt, Beta, Trend). Namen, Datum und Nachrichten sind nicht bekannt.
Es gibt keinen Vorschlag einer Regel. Höchstens 6 Titel, verschieden. Nenne zu jedem in "reason" den wichtigsten Grund. Antworte ausschließlich im Schema."""
KEYS = ("ret_5d", "ret_20d", "ret_60d", "ret_120d", "mom_12_1", "vol_20d", "vol_60d", "rsi14", "atr_pct", "dist_hi", "rel_60d", "beta", "above_sma50", "above_sma200", "trend_up")


def main():
    rows = lab._official_rows()
    hist = lab._official_history(rows, False)   # lädt die Kurshistorie beim ersten Mal (einige Minuten) und speichert sie in data/cache
    d = bt.Data.from_frames(hist["close"], hist["high"], hist["low"], hist["open"], [r["yf"] for r in rows])
    windows, price = lab.planspiel_windows(d.dates), d.fr.a["price"]

    def ask(job):
        year, s, _ = job
        snap = d.snap(s)
        cands = sorted(snap, key=lambda c: rules.score(snap[c]), reverse=True)[:40]
        order = cands[:]
        random.Random(year).shuffle(order)
        ids = {c: f"Titel {k + 1:02d}" for k, c in enumerate(order)}
        back = {v: k for k, v in ids.items()}
        payload = {"kandidaten": {ids[c]: {k: (round(snap[c][k], 3) if isinstance(snap[c].get(k), float) else snap[c].get(k)) for k in KEYS if k in snap[c]} for c in order}}
        err = ""
        for _ in range(2):
            try:
                out, used = brain._claude_json("Wähle anhand der Daten auf stdin 6 Titel und gib sie im Schema zurück.", brain.SHADOW_SCHEMA, SYSTEM, payload)
                picks = []
                for p in out.get("picks") or []:
                    c = back.get(p.get("isin"))
                    if c and c not in picks and len(picks) < 6:
                        picks.append(c)
                if len(picks) >= 4:
                    return picks, used["kosten_usd"]
            except Exception as e:  # noqa: BLE001
                err = str(e)[:80]
        print(f"{year}: kein Ergebnis ({err})")
        return None, 0.0

    t0 = time.time()
    with ThreadPoolExecutor(4) as ex:
        res = list(ex.map(ask, windows))
    print(f"{len(res)} Aufrufe in {time.time() - t0:.0f} s, Rechenwert {sum(c for _, c in res):.2f} $\n")

    def hold(cols, s, e):
        idx = [d.fr.col_index[c] for c in cols]
        return float(np.nanmean(price[e, idx] / price[s, idx] - 1))

    def rank(ret, s, e):
        return float((lab._random(d, s, e) < ret).mean())
    print(f"{'Zeitraum':9}{'Claude':>9}{'Regeln':>9}{'Ø 40 Kand.':>12}{'Ø alle':>9}{'Rang Claude':>13}{'Rang Regeln':>13}")
    tab = []
    for (year, s, e), (picks, _) in zip(windows, res):
        if not picks:
            continue
        snap = d.snap(s)
        ranked = sorted(snap, key=lambda c: rules.score(snap[c]), reverse=True)
        rule_picks = [c for c in ranked if rules.can_buy(snap[c], "risk_on", rules.PARAMS)][:6]
        allc = [d.fr.col_index[c] for c in snap]
        every = float(np.nanmean(price[e, allc] / price[s, allc] - 1))
        cl, ru, k40 = hold(picks, s, e), hold(rule_picks, s, e), hold(ranked[:40], s, e)
        tab.append((cl, ru, k40, every, rank(cl, s, e), rank(ru, s, e)))
        print(f"{year}/{str(year + 1)[2:]:2}   {cl * 100:>+7.1f}%{ru * 100:>+8.1f}%{k40 * 100:>+11.1f}%{every * 100:>+8.1f}%{tab[-1][4] * 100:>12.0f}%{tab[-1][5] * 100:>12.0f}%")
    if len(tab) < 3:
        return print("Zu wenige Ergebnisse (Anmeldung bei Claude Code prüfen: `claude` im Terminal starten).")
    t = np.array(tab)
    diff = t[:, 0] - t[:, 1]
    print(f"\nMittel über {len(t)} Zeiträume: Claude {t[:, 0].mean() * 100:+.1f} %, Regeln {t[:, 1].mean() * 100:+.1f} %, Ø 40 Kandidaten {t[:, 2].mean() * 100:+.1f} %, Ø alle Titel {t[:, 3].mean() * 100:+.1f} %")
    print(f"Rang gegen Zufallsdepots: Claude {t[:, 4].mean() * 100:.0f} %, Regeln {t[:, 5].mean() * 100:.0f} %. Claude schlägt die Regeln in {(diff > 0).sum()} von {len(t)} Jahren, "
          f"Vorsprung {diff.mean() * 100:+.1f} % (t = {diff.mean() / (diff.std(ddof=1) / np.sqrt(len(diff))):.2f}).")


if __name__ == "__main__":
    main()
