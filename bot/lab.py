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


# --- Nachhaltigkeitswertung: Ertrag der Sterntitel ---
def nh_yield(sim: dict, nh_cols) -> float:
    """Nachhaltigkeitsertrag nach den Spielregeln: aufsummierte Kursgewinne und -verluste (in €, ohne Gebühren) aller im Depot gehandelten Sterntitel
    (Verkäufe plus Wert der Bestände am Ende minus Käufe)."""
    return float(sum(f[1] + sim["held_value"].get(c, 0.0) - f[0] for c, f in sim["flows"].items() if c in nh_cols))


def random_nh_yields(h, s: int, e: int, nh_cols, n: int = 400, k: int = 6, amount: float = 8083.0, seed: int = 11) -> np.ndarray:
    """Erträge zufälliger Depots aus k Sterntiteln (Kaufen und Halten, je `amount` €): Ersatz für die Konkurrenz in der Nachhaltigkeitswertung."""
    rng = np.random.default_rng(seed)
    p0, p1 = h.fr.a["price"][s], h.fr.a["price"][e]
    idx = [h.fr.col_index[c] for c in nh_cols if c in h.fr.col_index]
    ok = [j for j in idx if not np.isnan(p0[j]) and not np.isnan(p1[j])]
    r = p1[ok] / p0[ok] - 1
    return np.array([amount * r[rng.choice(len(ok), size=min(k, len(ok)), replace=False)].sum() for _ in range(n)])


def evaluate_nh(h, windows, strat, nh_cols, step: int = 2) -> pd.DataFrame:
    """Je Planspiel-Jahr: Rang in der Gesamtwertung (wie `evaluate`) und in der Nachhaltigkeitswertung (Anteil zufälliger 6er-Depots aus Sterntiteln, deren Ertrag
    in € die Strategie übertrifft). Wer keinen Sterntitel handelt, hat Ertrag 0 (in der echten Wertung wäre er gar nicht platziert)."""
    rows = []
    for y, s, e in windows:
        sim = bt.simulate(h, s, e, strat, step)
        ret = bt.stats(sim["equity"])["return"]
        y_nh = nh_yield(sim, nh_cols)
        rows.append({"year": y, "ret": ret, "pct": float((_random(h, s, e) < ret).mean()), "nh_yield": y_nh,
                     "nh_pct": float((random_nh_yields(h, s, e, nh_cols) < y_nh).mean()), "nh_traded": any(c in nh_cols for c in sim["flows"])})
    return pd.DataFrame(rows).set_index("year")


# --- Trefferquote: Wie oft liegt die Auswahl richtig? ---
HIT_HORIZONS = (10, 20, 40, 80)   # Haltedauer in Handelstagen; 80 entspricht ungefähr einem Planspiel
SPLIT_YEAR = 2015                 # frühe gegen späte Planspiel-Jahre (wie in `split_summary`)


def forward_returns(d, i: int, h: int, k: int = 6):
    """Am Tag i: Renditen der k Käufe der Regeln (die stärksten kaufbaren Titel), Renditen aller Titel und Rangkorrelation (Spearman) von Score und Rendite,
    jeweils bis Tag i+h. None, wenn zu wenig Kurse vorliegen."""
    if i + h >= len(d.dates):
        return None
    snap = d.snap(i)
    cols = list(snap)
    ranked = sorted(cols, key=lambda c: rules.score(snap[c]), reverse=True)
    picks = [c for c in ranked if rules.can_buy(snap[c], "risk_on", rules.PARAMS)][:k]
    p, at = d.fr.a["price"], [d.fr.col_index[c] for c in cols]
    ret = pd.Series(p[i + h, at] / p[i, at] - 1, index=cols).dropna()
    pick = ret.reindex(picks).dropna()
    if pick.empty or len(ret) < 20:
        return None
    score = pd.Series({c: rules.score(snap[c]) for c in ret.index})
    return {"pick": pick.to_numpy(), "alle": ret.to_numpy(), "ic": float(score.rank().corr(ret.rank()))}


def hit_stats(results: list) -> dict:
    """Kennzahlen aus den Ergebnissen von `forward_returns` (eines je Startpunkt): Anteil der Käufe im Plus, Anteil aller Titel im Plus, Anteil der Käufe über dem
    mittleren Titel, mittlere Überrendite der Käufe gegenüber allen Titeln (t-Wert über die Startpunkte) und mittlere Rangkorrelation. None ohne Ergebnisse."""
    if not results:
        return None
    plus = np.concatenate([r["pick"] > 0 for r in results])
    above = np.concatenate([r["pick"] > np.median(r["alle"]) for r in results])
    ex = np.array([r["pick"].mean() - r["alle"].mean() for r in results])
    sd = ex.std(ddof=1) if len(ex) > 1 else 0.0
    return {"kaeufe": len(plus), "starts": len(ex), "plus": float(plus.mean()), "alle_plus": float(np.mean([(r["alle"] > 0).mean() for r in results])),
            "ueber_median": float(above.mean()), "ueberrendite": float(ex.mean()), "t": float(ex.mean() / (sd / np.sqrt(len(ex)))) if sd > 0 else 0.0,
            "ic": float(np.nanmean([r["ic"] for r in results]))}


def position_outcomes(d, windows, strat, step: int = 2) -> pd.DataFrame:
    """Was aus den Positionen der Strategie wurde: eine Zeile je gekaufter Position mit Einstand, Ausstieg (Verkaufskurs, sonst Schlusskurs am letzten Tag des
    Zeitraums), Haltedauer in Tagen und offen (am Ende noch gehalten). Verkäufe zählen zum Eröffnungskurs des Tages nach der Entscheidung, wie in `simulate`."""
    rows = []
    for y, s, e in windows:
        held, calls = {}, [0]

        def watch(pf, uni, snap, total, regime=None):
            i = s + step * calls[0]   # simulate ruft die Strategie am Starttag und dann alle `step` Tage auf
            calls[0] += 1
            now = {c: (p["avg_price"], p["bought"]) for c, p in pf["positions"].items()}
            for c, (price, bought) in held.items():
                if c not in now:   # seit dem letzten Aufruf verkauft
                    rows.append(_exit(d, y, c, price, bought, i - step + 1, False))
            held.clear()
            held.update(now)
            return strat(pf, uni, snap, total, regime)

        sim = bt.simulate(d, s, e, watch, step)
        last = s + step * (calls[0] - 1)
        for c, (price, bought) in held.items():   # Stand nach dem letzten Aufruf: entweder bis zum Ende gehalten oder danach noch verkauft
            rows.append(_exit(d, y, c, price, bought, e, True) if c in sim["held_value"] else _exit(d, y, c, price, bought, last + 1, False))
    return pd.DataFrame(rows, columns=["jahr", "isin", "einstand", "ausstieg", "tage", "offen"])


def _exit(d, year: int, c: str, price: float, bought: str, bar: int, still_open: bool) -> tuple:
    """Ausstieg einer Position an Handelstag `bar`: offene Positionen zum Schlusskurs, verkaufte zum Eröffnungskurs (fehlt er, zum Schlusskurs des Vortags)."""
    if still_open:
        out = d.px(bar, c)
    else:
        out = d.open[bar, d.fr.col_index[c]]
        out = d.px(bar - 1, c) if np.isnan(out) else out
    return (year, c, price, float(out), (d.dates[bar].date() - pd.Timestamp(bought).date()).days, still_open)


def summarize_positions(df: pd.DataFrame) -> dict:
    """Kennzahlen zu den Positionen aus `position_outcomes`: Anteil im Plus, mittlerer Gewinn und Verlust, Ergebnis je Position und Anteil der besten 10 % am gesamten Gewinn."""
    r = (df.ausstieg / df.einstand - 1).to_numpy()
    win, loss = r[r > 0], r[r <= 0]
    best = np.sort(r)[::-1][:max(1, len(r) // 10)]
    return {"n": len(r), "plus": float((r > 0).mean()), "gewinn": float(win.mean()) if len(win) else 0.0, "verlust": float(loss.mean()) if len(loss) else 0.0,
            "mittel": float(r.mean()), "median": float(np.median(r)), "tage": float(df.tage.mean()),
            "anteil_beste": float(best.sum() / r.sum()) if r.sum() > 0 else float("nan")}


def summarize(df: pd.DataFrame) -> dict:
    return {"n": len(df), "median": df.ret.median(), "mean": df.ret.mean(), "positive": (df.ret > 0).mean(),
            "worst": df.ret.min(), "excess_ew": (df.ret - df.ew).mean(), "beat_ew": (df.ret > df.ew).mean(),
            "pct": df.pct.mean(), "top10": (df.pct >= 0.9).mean(), "fees": df.fees.median()}


def split_summary(df: pd.DataFrame, split_year: int = SPLIT_YEAR) -> dict:
    return {"alle": summarize(df), "früh": summarize(df[df.index < split_year]), "spät": summarize(df[df.index >= split_year])}


# --- Kommandozeile: python -m bot.lab -------------------------------------------------------------------------------
def load_history(cache: str, refresh: bool = False, symbols: list = None, currencies: dict = None):
    """Kurshistorie ab 2003, wird zwischengespeichert (Download dauert ca. 40 s je 200 Titel). Ohne `symbols`: die Titel aus bot/universes.py in Heimatwährung.
    Mit `currencies` ({Symbol: Währung}) werden alle Kurse in Euro umgerechnet (bot/fx.py), so wie der Bot live rechnet."""
    import os
    import pickle

    from . import universes
    if os.path.exists(cache) and not refresh:
        return pickle.load(open(cache, "rb"))
    import yfinance as yf
    syms = list(dict.fromkeys(symbols or universes.ALL)) + ["^GDAXI", "^GSPC", "^VIX", "^STOXX50E"]
    d = yf.download(syms, start="2003-06-01", interval="1d", auto_adjust=True, progress=False, group_by="ticker", threads=True)
    hist = {k: d.xs(k.capitalize(), axis=1, level=1) for k in ("close", "high", "low", "open")}
    if currencies:
        from . import fx
        rates = fx.download_rates(set(currencies.values()) - {"EUR"}, start="2003-06-01")
        hist = {k: fx.convert(v.sort_index().ffill(limit=5), currencies, rates) for k, v in hist.items()}
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


def _official_rows() -> list:
    """Das amtliche Universum aus data/universe.json. Ohne die Felder markt und currency (Import mit `python -m bot.universe_tool official`) bricht der Test ab."""
    import json
    import os

    from . import config
    rows = json.load(open(os.path.join(config.DATA_DIR, "universe.json")))
    if not all(r.get("markt") and r.get("currency") for r in rows):
        raise SystemExit("data/universe.json stammt nicht aus `python -m bot.universe_tool official` (Felder markt und currency fehlen)")
    return rows


def _official_history(rows: list, refresh: bool):
    import os

    from . import config
    return load_history(os.path.join(config.DATA_DIR, "cache", "history_official.pkl"), refresh, [r["yf"] for r in rows], {r["yf"]: r["currency"] for r in rows})


def _official_report(refresh: bool, years: bool):
    """Die Strategien auf dem amtlichen Universum (data/universe.json aus `python -m bot.universe_tool official`), Kurse in Euro, gruppiert nach Markt."""
    rows = _official_rows()
    hist = _official_history(rows, refresh)
    groups = {g: [r["yf"] for r in rows if r["markt"] == g] for g in ("dax", "mdax", "sdax", "europa", "us")}
    groups["alle"] = [r["yf"] for r in rows]
    _run_groups(hist, groups, years, f"Amtliches Universum ({len(rows)} Titel), Kurse in Euro")


def _hit_report(refresh: bool, years: bool):
    """Wie oft liegt die Auswahl richtig? Trefferquote der Käufe und Ergebnis der tatsächlichen Positionen am amtlichen Universum in Euro (nur Auswertung der Regeln)."""
    rows = _official_rows()
    hist = _official_history(rows, refresh)
    d = bt.Data.from_frames(hist["close"], hist["high"], hist["low"], hist["open"], [r["yf"] for r in rows])
    n, w = len(d.dates), planspiel_windows(d.dates)
    head = f"{'Haltedauer':>11}{'Käufe':>8}{'Startpunkte':>13}{'im Plus':>9}{'alle Titel':>12}{'über Median':>13}{'Überrendite':>13}{'t-Wert':>8}{'Rangkorr.':>11}"

    def hits(starts, h):
        return hit_stats([r for r in (forward_returns(d, i, h) for i in starts) if r])

    def row(h, s, extra=""):
        if s is None:
            return f"{h:>6} Tage   zu wenig Kursdaten{extra}"
        return (f"{h:>6} Tage{s['kaeufe']:>8.0f}{s['starts']:>13.0f}{s['plus'] * 100:>8.0f}%{s['alle_plus'] * 100:>11.0f}%{s['ueber_median'] * 100:>12.0f}%"
                f"{s['ueberrendite'] * 100:>+12.1f}%{s['t']:>8.1f}{s['ic']:>+11.3f}{extra}")
    print(f"Amtliches Universum ({len(d.cols)} Titel), Kurse in Euro, Käufe = die 6 stärksten kaufbaren Titel nach dem Score der Regeln. „im Plus“: Anteil der Käufe mit Kursgewinn nach der\n"
          f"Haltedauer; „alle Titel“: dasselbe für alle Titel (Vergleich: ein Zufallstitel); „über Median“: Anteil der Käufe, die besser laufen als der mittlere Titel; Überrendite: Ø Käufe minus Ø alle Titel.\n")
    print(f"A) Käufe zum Start der {len(w)} Planspiel-Zeiträume (1.10.)\n{head}")
    for h in HIT_HORIZONS:
        print(row(h, hits([s for _, s, _ in w], h)), flush=True)
    last = HIT_HORIZONS[-1]
    for name, part in ((f"bis {SPLIT_YEAR - 1}", [x for x in w if x[0] < SPLIT_YEAR]), (f"ab {SPLIT_YEAR}", [x for x in w if x[0] >= SPLIT_YEAR])):
        print(row(last, hits([s for _, s, _ in part], last), f"   (nur Jahre {name})"))
    print(f"\nB) Käufe an beliebigen Tagen seit {d.dates[260].year}, überlappungsfrei (Startpunkte im Abstand der Haltedauer, gemittelt über 4 Startversätze)\n{head}")
    for h in HIT_HORIZONS:
        runs = [x for x in (hits(range(o, n - h - 1, h), h) for o in list(range(260, 260 + h, max(1, h // 4)))[:4]) if x]
        mean = {k: float(np.mean([x[k] for x in runs])) for k in runs[0]} if runs else None
        print(row(h, mean, f"   (t über 2 in {sum(x['t'] > 2 for x in runs)} von {len(runs)} Reihen)" if runs else ""), flush=True)
    out = position_outcomes(d, w, rules.decide)
    print(f"\nC) Was aus den Positionen der Regeln in den {len(w)} Planspiel-Zeiträumen wurde (Kauf bis Verkauf, sonst bewertet zum Schlusskurs am 25.1.)")
    if out.empty:
        return print("  keine Positionen")
    for label, df in (("alle Positionen", out), ("bis zum Ende gehalten", out[out.offen]), ("vorzeitig verkauft", out[~out.offen])):
        if df.empty:
            continue
        s = summarize_positions(df)
        print(f"  {label:24}{s['n']:>4} Positionen | im Plus {s['plus'] * 100:3.0f}% | Ø Gewinn {s['gewinn'] * 100:+5.1f}%, Ø Verlust {s['verlust'] * 100:+6.1f}% | "
              f"Ø je Position {s['mittel'] * 100:+5.1f}% (Median {s['median'] * 100:+5.1f}%) | Ø Haltedauer {s['tage']:.0f} Tage")
    best = summarize_positions(out)["anteil_beste"]
    if best == best:
        print(f"  Die besten 10 % der Positionen machen {best * 100:.0f} % des Gesamtergebnisses aller Positionen aus: wenige große Treffer tragen es.")
    if years:
        print("\n  je Planspiel-Jahr (Positionen | im Plus | Ø je Position):")
        for y, df in out.groupby("jahr"):
            s = summarize_positions(df)
            print(f"  {y}/{str(y + 1)[2:]}: {s['n']:>3} | {s['plus'] * 100:>3.0f}% | {s['mittel'] * 100:>+6.1f}%")


def _nh_report(refresh: bool):
    """Gesamtwertung gegen Nachhaltigkeitswertung: Wie viele Plätze für Sterntitel reserviert werden (nh_slots), am amtlichen Universum in Euro."""
    rows = _official_rows()
    hist = _official_history(rows, refresh)
    d = bt.Data.from_frames(hist["close"], hist["high"], hist["low"], hist["open"], [r["yf"] for r in rows])
    stars = {r["yf"]: r["stars"] for r in rows}
    for c in d.cols:
        d.uni[c]["stars"] = stars.get(c, 0)
    nh_cols = {c for c in d.cols if stars.get(c)}
    w = planspiel_windows(d.dates)
    print(f"Nachhaltigkeit: {len(nh_cols)} Sterntitel von {len(d.cols)}, {len(w)} Planspiel-Jahre. Gesamtrang wie bisher; NH-Rang = Anteil zufälliger 6er-Depots aus Sterntiteln,\n"
          f"deren Ertrag (aufsummierte Kursgewinne der Sterntitel in €) übertroffen wird.\n")
    print(f"{'reservierte Plätze':>18}{'Median':>9}{'schlechtestes':>15}{'Gesamtrang':>12}{'NH-Ertrag Ø':>13}{'NH-Ertrag Median':>18}{'NH-Rang':>9}{'Jahre mit NH-Handel':>21}")
    for k in (0, 1, 2, 3, 4, 6):
        df = evaluate_nh(d, w, make("mom_blend", n=6, keep_frac=0.7, exposure=mktvol_exposure(0.20, 0.4), rsi_filter=True, hard_stop=True, nh_slots=k), nh_cols)
        print(f"{k:>18}{df.ret.median() * 100:>+8.1f}%{df.ret.min() * 100:>+14.1f}%{df.pct.mean() * 100:>11.0f}%{df.nh_yield.mean():>12,.0f} €{df.nh_yield.median():>16,.0f} €"
              f"{df.nh_pct.mean() * 100:>8.0f}%{int(df.nh_traded.sum()):>17} von {len(df)}", flush=True)


def _run_groups(hist, groups: dict, years: bool, title: str):
    strategies = {"rules (Standard, jetzt)": rules.decide, "frühere Version (alle Filter)": bt.alt_all_filters, "nur 60-Tage-Momentum": bt.momentum_only}
    pct = lambda x: f"{x * 100:+5.1f}%"
    print(f"{title}. Planspiel-Jahre: 1.10. bis 25.1., je 50.000 €, Gebühren der Plattform. Rang = Anteil zufälliger 6-Titel-Depots, die geschlagen werden.\n")
    for g, syms in groups.items():
        d = bt.Data.from_frames(hist["close"], hist["high"], hist["low"], hist["open"], syms)
        w = planspiel_windows(d.dates)
        print(f"== {g}: {len(d.cols)} Titel, {len(w)} Jahre ({w[0][0]}-{w[-1][0]}) ==")
        for name, st in strategies.items():
            df = evaluate(d, w, st)
            s = split_summary(df)
            print(f"  {name:32} Median {pct(s['alle']['median'])}  im Plus {s['alle']['positive'] * 100:3.0f}%  schlechtestes Jahr {pct(s['alle']['worst'])}  "
                  f"Rang {s['alle']['pct'] * 100:3.0f}% (2004-14: {s['früh']['pct'] * 100:3.0f}%, 2015-25: {s['spät']['pct'] * 100:3.0f}%)", flush=True)
            if years and g == "alle" and name.startswith("rules"):
                out = (df[["ret", "ew", "dax", "pct"]] * 100).round(1)
                out.columns = ["Strategie %", "Ø alle Titel %", "DAX %", "Rang %"]
                print(out.to_string())
        print()


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
    ap.add_argument("--official", action="store_true", help="Strategien auf dem amtlichen Universum (data/universe.json) testen, Kurse in Euro")
    ap.add_argument("--nachhaltigkeit", action="store_true", help="Gesamtwertung gegen Nachhaltigkeitswertung bei reservierten Plätzen für Sterntitel (amtliches Universum, Euro)")
    ap.add_argument("--overlays", action="store_true", help="Marktbreite und Schutzschalter bei Depotrückgang als Überlagerung testen (Markt alle)")
    ap.add_argument("--trefferquote", action="store_true", help="Wie oft liegt die Auswahl richtig? Trefferquote der Käufe und Ergebnis der Positionen (amtliches Universum, Euro)")
    a = ap.parse_args()
    if a.trefferquote:
        return _hit_report(a.refresh, a.years)
    if a.official:
        return _official_report(a.refresh, a.years)
    if a.nachhaltigkeit:
        return _nh_report(a.refresh)
    hist = load_history(os.path.join(config.DATA_DIR, "cache", "history.pkl"), a.refresh)
    if a.macro:
        return _macro_report(hist)
    if a.overlays:
        return _overlay_report(hist)
    groups = {**universes.GROUPS, "alle": list(dict.fromkeys(universes.ALL))}
    _run_groups(hist, groups, a.years, "Getestetes Universum (Kurse in Heimatwährung)")


if __name__ == "__main__":
    main()
