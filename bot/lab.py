"""Strategie-Labor: testet Strategien in den Planspiel-Zeiträumen der Vergangenheit.

Ein Szenario ist ein Planspiel-Jahr: vom 1. Oktober bis zum 25. Januar des Folgejahres (rund 80 Handelstage), mit 50.000 €,
den Gebühren der Plattform (0,3 %, min. 15 €) und Ausführung zum Eröffnungskurs des Folgetags. Bewertet wird, wie im Spiel,
der Rang: Anteil zufälliger 6-Titel-Depots (Kaufen und Halten), die die Strategie im selben Zeitraum schlägt.

Ehrlichkeit vor Ergebnis: Es gibt nur ein Szenario pro Jahr, und je mehr Varianten man probiert, desto wahrscheinlicher passt eine
zufällig. Darum wird nach Zeit (frühe/späte Jahre) und nach Markt (DAX, MDAX, Europa, USA) getrennt geprüft, und eine Variante zählt nur,
wenn sie in beiden Hälften und in mehreren Märkten trägt."""
import numpy as np
import pandas as pd

from . import backtest as bt
from . import rules

# --- Bewertungsformeln (Ranking der Kandidaten) ---
SCORES = {
    "mom60_120": lambda m, s=0: 0.5 * m["ret_60d"] + 0.5 * m.get("ret_120d", m["ret_60d"]) + 0.01 * s,
    "mom120": lambda m, s=0: m.get("ret_120d", m["ret_60d"]),
    "mom60": lambda m, s=0: m["ret_60d"],
    "mom_12_1": lambda m, s=0: m.get("mom_12_1", m.get("ret_120d", m["ret_60d"])),
    "mom_blend": lambda m, s=0: (m["ret_60d"] + m.get("ret_120d", m["ret_60d"]) + m.get("mom_12_1", m.get("ret_120d", m["ret_60d"]))) / 3,
    "hi52": lambda m, s=0: m.get("dist_hi", -1.0),
    "mom_hi52": lambda m, s=0: 0.5 * (0.5 * m["ret_60d"] + 0.5 * m.get("ret_120d", m["ret_60d"])) + 0.5 * m.get("dist_hi", -1.0),
    "mom_lowvol": lambda m, s=0: (0.5 * m["ret_60d"] + 0.5 * m.get("ret_120d", m["ret_60d"])) / max(m.get("vol_60d", 0.3), 0.12),
    "mom_highbeta": lambda m, s=0: 0.5 * m["ret_60d"] + 0.5 * m.get("ret_120d", m["ret_60d"]) + 0.03 * m.get("beta", 1.0),
    "resid_blend": lambda m, s=0: 0.5 * m.get("resid_60d", m["ret_60d"]) + 0.5 * m.get("resid_120d", m.get("ret_120d", m["ret_60d"])),
    "resid120": lambda m, s=0: m.get("resid_120d", m.get("ret_120d", m["ret_60d"])),
    "resid_std": lambda m, s=0: m.get("resid_120d", m.get("ret_120d", m["ret_60d"])) / max(m.get("vol_60d", 0.3), 0.12),
    "mix_resid_raw": lambda m, s=0: 0.5 * (0.5 * m["ret_60d"] + 0.5 * m.get("ret_120d", m["ret_60d"]))
                                     + 0.5 * (0.5 * m.get("resid_60d", m["ret_60d"]) + 0.5 * m.get("resid_120d", m["ret_60d"])),
    "lowvol": lambda m, s=0: -m.get("vol_60d", 0.3),
    "lowvol_uptrend": lambda m, s=0: (-m.get("vol_60d", 0.3) if m.get("above_sma200") and m.get("ret_120d", 0) > 0 else -9.0),
    "pullback": lambda m, s=0: (-m["ret_20d"] if m.get("trend_up") and m.get("above_sma200") and m.get("ret_120d", 0) > 0.05 else -9.0),
    "oversold_uptrend": lambda m, s=0: ((50 - m.get("rsi14", 50)) if m.get("above_sma200") and m.get("ret_120d", 0) > 0 else -99.0),
}


def planspiel_windows(dates: pd.DatetimeIndex, min_bar: int = 260):
    """[(Jahr, Startbar, Endbar)]: erster Handelstag ab 1.10. bis letzter Handelstag bis 25.1. des Folgejahres."""
    out = []
    for y in range(dates[0].year, dates[-1].year):
        s = int(dates.searchsorted(pd.Timestamp(y, 10, 1)))
        e = int(dates.searchsorted(pd.Timestamp(y + 1, 1, 25), side="right")) - 1
        if s >= min_bar and e < len(dates) and dates[e] >= pd.Timestamp(y + 1, 1, 20):
            out.append((y, s, e))
    return out


# --- Strategien aus Bausteinen ---
NO_FILTERS = {"trend_filter": False, "rsi_filter": False, "hard_stop": False, "trailing": False, "trend_break": False,
              "sma50_sell": False, "vol_weight": False, "regime": False, "earnings_blackout": False,
              "vol_scale": False, "keep_frac": 0.5, "n_positions": None, "min_score": None}


def make(score="mom60_120", n=6, keep_frac=0.5, exposure=None, **flags):
    """Regelstrategie mit frei wählbarer Bewertung. `exposure(regime) -> (Anteil investiert, Positionen)` steuert
    das Marktumfeld (None = immer voll). flags überschreiben die Bausteine aus rules.PARAMS (z. B. trend_filter=True)."""
    multi = isinstance(score, (list, tuple))
    fn = (lambda m, s=0: m["_score"]) if multi else (SCORES[score] if isinstance(score, str) else score)
    params = {**NO_FILTERS, "keep_frac": keep_frac, "n_positions": n, **flags}

    def strat(pf, uni, snap, total, regime=None):
        if multi:   # Signal-Mischung: Mittel der Rangplätze (0..1) mehrerer Bewertungen, ein gemeinsames Depot
            ids = list(snap)
            avg = np.zeros(len(ids))
            for name in score:
                vals = np.array([SCORES[name](snap[i], 0) for i in ids])
                avg += vals.argsort().argsort() / max(len(ids) - 1, 1)
            snap = {i: {**snap[i], "_score": a / len(score)} for i, a in zip(ids, avg)}
        if exposure is None:
            return rules.decide(pf, uni, snap, total, None, params=params, score_fn=fn)
        exp, pos = exposure(regime or {})
        reg = {"label": "custom", "score": "-", "exposure": exp, "positions": pos}
        return rules.decide(pf, uni, snap, total, reg, params={**params, "regime": True, "n_positions": None}, score_fn=fn)

    return strat


def dax_trend_exposure(off_exposure=0.5, off_positions=3):
    """Halbe Position, wenn der DAX unter der 200-Tage-Linie schließt."""
    def f(regime):
        below = regime.get("checks", {}).get("dax über SMA200") is False
        return (off_exposure, off_positions) if below else (0.97, 6)
    return f


def _scaled(exp, n=6, capital=50000.0):
    """Anteil investiert -> passende Positionszahl (jede Order mindestens 5.500 €, damit die 5.000-€-Grenze hält)."""
    return exp, max(2, min(n, int(exp * capital / 5500)))


def mktvol_exposure(target=0.20, floor=0.4, n=6):
    """Volatilitäts-Skalierung (Daniel/Moskowitz-Idee): weniger investieren, wenn der Markt stark schwankt."""
    def f(regime):
        v = regime.get("mkt_vol_60d")
        if not v:
            return 0.97, n
        return _scaled(min(0.97, max(floor, target / v)), n)
    return f


MACRO_TRIGGERS = {   # Warnsignale aus Zins- und Konjunkturdaten (bot/macro.py), jeweils mit dem Stand des Tages
    "Zinskurve invers (10J-2J < 0)": lambda m: m.get("curve") is not None and m["curve"] < 0,
    "Zinskurve invers (10J-3M < 0)": lambda m: m.get("curve3m") is not None and m["curve3m"] < 0,
    "Kreditaufschläge +0,5 in 120 Tagen": lambda m: (m.get("credit_widening") or 0) > 0.5,
    "10J-Rendite +0,75 in 3 Monaten": lambda m: (m.get("y10_chg63") or 0) > 0.75,
    "Fed strafft (+1,0 in 6 Monaten)": lambda m: (m.get("dff_chg126") or 0) > 1.0,
    "Sahm-Regel >= 0,5": lambda m: (m.get("sahm") or 0) >= 0.5,
    "Inflation > 4 %": lambda m: (m.get("cpi_yoy") or 0) > 4.0,
}


def n_warnings(m: dict) -> int:
    keys = ("Zinskurve invers (10J-2J < 0)", "Kreditaufschläge +0,5 in 120 Tagen", "10J-Rendite +0,75 in 3 Monaten", "Fed strafft (+1,0 in 6 Monaten)")
    return sum(bool(MACRO_TRIGGERS[k](m)) for k in keys)


def macro_exposure(trigger, off_exposure=0.5, target=0.20, floor=0.4, n=6):
    """Volatilitäts-Skalierung wie im Standard, zusätzlich höchstens `off_exposure` investiert, solange das Makro-Warnsignal aktiv ist."""
    base = mktvol_exposure(target, floor, n)

    def f(regime):
        exp, pos = base(regime)
        if trigger(regime.get("macro") or {}):
            exp, pos = _scaled(min(exp, off_exposure), n)
        return exp, pos
    return f


def breadth_exposure(threshold=0.40, off_exposure=0.5, target=0.20, floor=0.4, n=6, key="breadth200"):
    """Marktbreite (Skill "Market Breadth Analyzer"): sind weniger als `threshold` der Titel über ihrer Durchschnittslinie, höchstens `off_exposure` investiert."""
    base = mktvol_exposure(target, floor, n)

    def f(regime):
        exp, pos = base(regime)
        b = regime.get(key)
        if b is not None and b == b and b < threshold:
            exp, pos = _scaled(min(exp, off_exposure), n)
        return exp, pos
    return f


def drawdown_exposure(dd=0.10, off_exposure=0.5, target=0.20, floor=0.4, n=6):
    """Schutzschalter (übliche Risikomanagement-Regel): liegt das Depot mehr als `dd` unter seinem Höchststand, höchstens `off_exposure` investiert."""
    base = mktvol_exposure(target, floor, n)

    def f(regime):
        exp, pos = base(regime)
        if regime.get("drawdown", 0.0) <= -dd:
            exp, pos = _scaled(min(exp, off_exposure), n)
        return exp, pos
    return f


def vix_exposure(level=28.0, off_exposure=0.5, off_positions=3):
    def f(regime):
        v = regime.get("vix")
        return (off_exposure, off_positions) if v is not None and v > level else (0.97, 6)
    return f


def regime_exposure(off_exposure=0.5, off_positions=3):
    def f(regime):
        return (off_exposure, off_positions) if regime.get("label") == "risk_off" else (0.97, 6)
    return f


# --- Bewertung ---
_random_cache = {}


def _random(h, s, e):
    key = (id(h), s, e)
    if key not in _random_cache:
        _random_cache[key] = bt.random_portfolios(h, s, e, n=400)
    return _random_cache[key]


def run_window(h, s, e, strat, step=2):
    sim = bt.simulate(h, s, e, strat, step)
    st = bt.stats(sim["equity"])
    return {"ret": st["return"], "dd": st["max_drawdown"], "fees": sim["fees"], "equity": np.array(sim["equity"])}


def ensemble_window(h, s, e, parts, step=2):
    """parts = [(Strategie, Anteil am Kapital)]: getrennte Teildepots, Summe der Wertverläufe."""
    total, fees = None, 0.0
    for strat, w in parts:
        sim = bt.simulate(h, s, e, strat, step, capital=50000.0 * w)
        eq = np.array(sim["equity"])
        total = eq if total is None else total + eq
        fees += sim["fees"]
    st = bt.stats(list(total))
    return {"ret": st["return"], "dd": st["max_drawdown"], "fees": fees, "equity": total}


def evaluate(h, windows, strat=None, parts=None, step=2):
    """Eine Zeile je Planspiel-Jahr."""
    rows = []
    for y, s, e in windows:
        r = ensemble_window(h, s, e, parts, step) if parts else run_window(h, s, e, strat, step)
        rand = _random(h, s, e)
        p0, p1 = h.fr.a["price"][s], h.fr.a["price"][e]
        ew = float(np.nanmean(p1 / p0 - 1))
        dax = float(h.idx.a["price"][e, h.idx.col_index["dax"]] / h.idx.a["price"][s, h.idx.col_index["dax"]] - 1)
        rows.append({"year": y, "ret": r["ret"], "ew": ew, "dax": dax, "pct": float((rand < r["ret"]).mean()),
                     "dd": r["dd"], "fees": r["fees"], "rand_med": float(np.median(rand))})
    return pd.DataFrame(rows).set_index("year")


def summarize(df: pd.DataFrame) -> dict:
    return {"n": len(df), "median": df.ret.median(), "mean": df.ret.mean(), "positive": (df.ret > 0).mean(),
            "worst": df.ret.min(), "excess_ew": (df.ret - df.ew).mean(), "beat_ew": (df.ret > df.ew).mean(),
            "pct": df.pct.mean(), "top10": (df.pct >= 0.9).mean(), "fees": df.fees.median()}


def split_summary(df: pd.DataFrame, split_year: int = 2015) -> dict:
    return {"alle": summarize(df), "früh": summarize(df[df.index < split_year]), "spät": summarize(df[df.index >= split_year])}


# --- Kommandozeile: python -m bot.lab -------------------------------------------------------------------------------
def load_history(cache: str, refresh: bool = False):
    """Kurshistorie ab 2003 für alle Titel aus bot/universes.py; wird zwischengespeichert (Download dauert ca. 40 s)."""
    import os
    import pickle

    from . import universes
    if os.path.exists(cache) and not refresh:
        return pickle.load(open(cache, "rb"))
    import yfinance as yf
    syms = list(dict.fromkeys(universes.ALL)) + ["^GDAXI", "^GSPC", "^VIX", "^STOXX50E"]
    d = yf.download(syms, start="2003-06-01", interval="1d", auto_adjust=True, progress=False, group_by="ticker", threads=True)
    hist = {k: d.xs(k.capitalize(), axis=1, level=1) for k in ("close", "high", "low", "open")}
    os.makedirs(os.path.dirname(cache), exist_ok=True)
    pickle.dump(hist, open(cache, "wb"))
    return hist


def _macro_report(hist):
    from . import macro, universes
    d = bt.Data.from_frames(hist["close"], hist["high"], hist["low"], hist["open"], list(dict.fromkeys(universes.ALL)))
    d.attach_macro(macro.frame(d.dates))
    w = planspiel_windows(d.dates)
    print(f"Makro-Warnsignale als Überlagerung (bei Signal höchstens 50 % investiert), {len(w)} Planspiel-Jahre, Markt alle\n")
    print(f"{'Warnsignal':46}{'Jahre aktiv':>12}{'Median':>9}{'Rang':>7}{'schlechtestes Jahr':>20}")
    cases = [("ohne Makro (Standard)", lambda m: False)] + list(MACRO_TRIGGERS.items()) + [("mindestens 2 von 4 Warnsignalen", lambda m: n_warnings(m) >= 2)]
    for name, trig in cases:
        active = sum(bool(trig(d.macro_at(s))) for _, s, _ in w)
        df = evaluate(d, w, make("mom_blend", keep_frac=0.7, exposure=macro_exposure(trig)))
        s = summarize(df)
        print(f"{name:46}{active:>9} von {len(w)}{s['median'] * 100:>+8.1f}%{s['pct'] * 100:>6.0f}%{s['worst'] * 100:>+19.1f}%")


def _overlay_report(hist):
    from . import universes
    d = bt.Data.from_frames(hist["close"], hist["high"], hist["low"], hist["open"], list(dict.fromkeys(universes.ALL)))
    w = planspiel_windows(d.dates)
    print(f"Überlagerungen (bei Auslösung höchstens 50 % investiert), {len(w)} Planspiel-Jahre, Markt alle\n")
    print(f"{'Überlagerung':52}{'Median':>9}{'Rang':>7}{'schlechtestes Jahr':>20}")
    cases = [("ohne (Standard, mit Volatilitäts-Skalierung)", mktvol_exposure(0.20, 0.4))]
    cases += [(f"Marktbreite (Anteil über SMA200) unter {t:.0%}", breadth_exposure(t)) for t in (0.30, 0.40, 0.50)]
    cases += [(f"Marktbreite (Anteil über SMA50) unter {t:.0%}", breadth_exposure(t, key="breadth50")) for t in (0.30, 0.40)]
    cases += [(f"Schutzschalter: Depot {t:.0%} unter Höchststand", drawdown_exposure(t)) for t in (0.08, 0.10, 0.15)]
    for name, exposure in cases:
        s = summarize(evaluate(d, w, make("mom_blend", keep_frac=0.7, exposure=exposure)))
        print(f"{name:52}{s['median'] * 100:>+8.1f}%{s['pct'] * 100:>6.0f}%{s['worst'] * 100:>+19.1f}%")


def main():
    import argparse
    import os
    import warnings

    from . import config, universes
    warnings.filterwarnings("ignore")
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--refresh", action="store_true", help="Kurshistorie neu laden")
    ap.add_argument("--years", action="store_true", help="Ergebnis je Planspiel-Jahr ausgeben")
    ap.add_argument("--macro", action="store_true", help="Zins- und Konjunktur-Warnsignale als Überlagerung testen (Markt alle)")
    ap.add_argument("--overlays", action="store_true", help="Marktbreite und Schutzschalter bei Depotrückgang als Überlagerung testen (Markt alle)")
    a = ap.parse_args()
    hist = load_history(os.path.join(config.DATA_DIR, "cache", "history.pkl"), a.refresh)
    if a.macro:
        return _macro_report(hist)
    if a.overlays:
        return _overlay_report(hist)
    groups = {**universes.GROUPS, "alle": list(dict.fromkeys(universes.ALL))}
    strategies = {"rules (Standard, jetzt)": rules.decide, "frühere Version (alle Filter)": bt.alt_all_filters,
                  "nur 60-Tage-Momentum": bt.momentum_only}
    pct = lambda x: f"{x * 100:+5.1f}%"
    print("Planspiel-Jahre: 1.10. bis 25.1., je 50.000 €, Gebühren der Plattform. Rang = Anteil zufälliger 6-Titel-Depots, die geschlagen werden.\n")
    for g, syms in groups.items():
        d = bt.Data.from_frames(hist["close"], hist["high"], hist["low"], hist["open"], syms)
        w = planspiel_windows(d.dates)
        print(f"== {g}: {len(d.cols)} Titel, {len(w)} Jahre ({w[0][0]}-{w[-1][0]}) ==")
        for name, st in strategies.items():
            df = evaluate(d, w, st)
            s = split_summary(df)
            print(f"  {name:32} Median {pct(s['alle']['median'])}  im Plus {s['alle']['positive'] * 100:3.0f}%  schlechtestes Jahr {pct(s['alle']['worst'])}  "
                  f"Rang {s['alle']['pct'] * 100:3.0f}% (2004-14: {s['früh']['pct'] * 100:3.0f}%, 2015-25: {s['spät']['pct'] * 100:3.0f}%)")
            if a.years and g == "alle" and name.startswith("rules"):
                out = (df[["ret", "ew", "dax", "pct"]] * 100).round(1)
                out.columns = ["Strategie %", "Ø alle Titel %", "DAX %", "Rang %"]
                print(out.to_string())
        print()


if __name__ == "__main__":
    main()
