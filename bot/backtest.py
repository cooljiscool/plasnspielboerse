"""Backtest der Regelstrategie an historischen Kursen.

  python -m bot.backtest --demo-dax                  # schneller Test mit den DAX-Werten
  python -m bot.backtest --universe --years 4        # mit data/universe.json (Symbole in "yf")

Das Ergebnis misst die technische Seite (Trend, Momentum, Marktumfeld, Stopps, Gebühren). Nicht abgebildet sind
Fundamentaldaten, Gewinnmeldungen, Web-Recherche und Claudes Urteil, weil es dafür keine historischen Daten gibt.
Wichtigste Grenzen: Es werden die heutigen Indexmitglieder getestet (Survivorship-Bias, die Ergebnisse sind tendenziell
zu gut), Orders werden zum Eröffnungskurs des Folgetags ausgeführt, die Gebühr entspricht der Plattform (0,3 %, min. 15 €).
Vergangenheit ist keine Prognose."""
import argparse
import json
import math
import os

import numpy as np
import pandas as pd

from . import config, market, risk, rules, signals

DEMO_DAX = ("SAP.DE SIE.DE ALV.DE DTE.DE AIR.DE MUV2.DE DBK.DE BAS.DE BMW.DE MBG.DE VOW3.DE ADS.DE IFX.DE RWE.DE EOAN.DE "
            "HEI.DE BAYN.DE DHL.DE DB1.DE FRE.DE MRK.DE SHL.DE SY1.DE ZAL.DE CBK.DE HNR1.DE BEI.DE CON.DE PAH3.DE QIA.DE "
            "RHM.DE MTX.DE ENR.DE VNA.DE 1COV.DE P911.DE DTG.DE BNR.DE HEN3.DE SRT3.DE").split()
DEMO_US = ("AAPL MSFT AMZN GOOGL META NVDA AVGO COST NFLX ADBE PEP CSCO TMUS AMD INTC QCOM TXN AMGN HON SBUX INTU AMAT ISRG "
           "BKNG GILD MDLZ ADP LRCX REGN MU JPM V UNH JNJ WMT PG HD CVX KO MRK MCD DIS IBM CAT GS AXP MMM BA NKE CRM TRV VZ").split()
WARMUP = 200          # Handelstage Vorlauf für SMA200
WINDOW = 80           # Handelstage, ungefähr die Länge des Spiels (1.10. bis 25.1.)


def momentum_only(pf, uni, snap, total, regime=None):
    """Einfachste Vergleichsstrategie: die 6 Titel mit der besten 60-Tage-Rendite, ohne Filter."""
    ranked = sorted(snap, key=lambda i: snap[i]["ret_60d"], reverse=True)
    orders = [{"action": "sell", "isin": i, "stop": False, "reason": "Rang"} for i in pf["positions"]
              if i in snap and i not in ranked[:12]]
    kept = [i for i in pf["positions"] if i in snap and i not in {o["isin"] for o in orders}]
    for i in ranked:
        if len(kept) >= 6:
            break
        if i not in pf["positions"]:
            orders.append({"action": "buy", "isin": i, "amount_eur": round(total * 0.97 / 6), "reason": "Momentum"})
            kept.append(i)
    return {"orders": orders}


ALL_FILTERS = {"trend_filter": True, "rsi_filter": True, "hard_stop": True, "trailing": True, "trend_break": True,
               "sma50_sell": True, "vol_weight": True, "regime": True, "keep_frac": 12 / 39}


def alt_all_filters(pf, uni, snap, total, regime=None):
    """Frühere Version: Mischformel mit allen Filtern, Stopps und Marktumfeld (zum Vergleich)."""
    return rules.decide(pf, uni, snap, total, regime, params=ALL_FILTERS, score_fn=rules.score_mix)


STRATEGIES = {"rules": rules.decide, "frueher_alle_filter": alt_all_filters, "nur_momentum_60d": momentum_only}


class Data:
    """Kurshistorie plus Kennzahlen. Aus Yahoo (`Data(symbols, years)`) oder aus fertigen Tabellen (`Data.from_frames`)."""

    def __init__(self, symbols: list, years: int = 4, start: str = None):
        cols = list(symbols) + list(market.INDEX.values())
        if start:
            import yfinance as yf
            d = yf.download(cols, start=start, interval="1d", auto_adjust=True, progress=False, group_by="ticker", threads=True)
            parts = [d.xs(f, axis=1, level=1).dropna(how="all").ffill(limit=3) for f in ("Close", "High", "Low", "Open")]
        else:
            parts = market.download(cols, period=f"{years}y")
            parts = [parts[0], parts[1], parts[2], parts[3]]
        self._build(*parts, symbols)

    @classmethod
    def from_frames(cls, close, high, low, opn, symbols):
        self = object.__new__(cls)
        self._build(close, high, low, opn, symbols)
        return self

    def _build(self, close, high, low, opn, symbols):
        # Feiertage einzelner Börsen füllen (bis 5 Tage), sonst sind gleitende Durchschnitte und Schwankungen lückenhaft
        close, high, low, opn = (x.sort_index().ffill(limit=5) for x in (close, high, low, opn))
        idx_syms = {k: s for k, s in market.INDEX.items() if s in close.columns}
        self.cols = [s for s in symbols if s in close.columns and close[s].notna().sum() > WARMUP + WINDOW]
        if not self.cols:
            raise SystemExit("keine Kursdaten geladen")
        self.dates = close.index
        dax = close[market.INDEX["dax"]] if "dax" in idx_syms else None
        self.fr = signals.Frames(close[self.cols], high[self.cols], low[self.cols], dax)
        self.idx = signals.Frames(close[list(idx_syms.values())].rename(columns={s: k for k, s in idx_syms.items()}))
        self.open = opn[self.cols].reindex(close.index).to_numpy(dtype=float)
        self.uni = {c: {"name": c, "stars": 0} for c in self.cols}
        self._snaps = {}

    def snap(self, i):
        """Kennzahlen aller Titel am Tag i (zwischengespeichert, hängen nicht vom Depot ab)."""
        if i not in self._snaps:
            self._snaps[i] = {c: m for c in self.cols if (m := self.fr.at(i, c))}
        return self._snaps[i]

    def px(self, i, c):
        return self.fr.price_at(i, c)


def simulate(d: Data, start: int, end: int, strategy, step: int = 2, capital: float = 50000.0) -> dict:
    pf = {"cash": capital, "positions": {}, "buy_orders_executed": 0}
    pending, equity, fees, trades = [], [], 0.0, 0
    for i in range(start, end + 1):
        today = d.dates[i].date()
        # 1. Orders von gestern zum heutigen Eröffnungskurs
        for o in pending:
            j = d.fr.col_index[o["isin"]]
            px = d.open[i, j] if not np.isnan(d.open[i, j]) else d.px(i - 1, o["isin"])
            if o["action"] == "buy":
                sh = o["shares"]
                while sh > 0 and sh * px + config.fee(sh * px) > pf["cash"]:
                    sh -= 1
                if sh <= 0:
                    continue
                fee = config.fee(sh * px)
                pf["cash"] -= sh * px + fee
                fees, trades = fees + fee, trades + 1
                pos = pf["positions"].get(o["isin"])
                if pos:
                    pos["avg_price"] = (pos["avg_price"] * pos["shares"] + sh * px) / (pos["shares"] + sh)
                    pos["shares"] += sh
                else:
                    pf["positions"][o["isin"]] = {"shares": sh, "avg_price": px, "bought": today.isoformat(), "peak": px}
            else:
                pos = pf["positions"].get(o["isin"])
                if not pos:
                    continue
                sh = min(o["shares"], pos["shares"])
                fee = config.fee(sh * px)
                pf["cash"] += sh * px - fee
                fees, trades = fees + fee, trades + 1
                pos["shares"] -= sh
                if pos["shares"] == 0:
                    del pf["positions"][o["isin"]]
        pending = []
        # 2. Bewerten zum Schlusskurs
        prices = {c: d.px(i, c) for c in d.cols if not math.isnan(d.px(i, c))}
        for isin, pos in pf["positions"].items():
            pos["peak"] = max(pos.get("peak") or pos["avg_price"], prices.get(isin, pos["avg_price"]))
        total = risk.portfolio_value(pf, prices)
        equity.append(total)
        # 3. Entscheiden (nur mit Daten bis heute) und für morgen vormerken
        if (i - start) % step == 0 and i < end:
            snap = d.snap(i)
            regime = signals.regime_at(d.idx, i)
            regime["mkt_vol_60d"] = d.fr.market_at(i)["vol_60d"]
            out = strategy(pf, d.uni, snap, total, regime)
            pending, _ = risk.validate(out["orders"], pf, prices, d.uni, today)
    return {"equity": equity, "fees": fees, "trades": trades}


def stats(equity: list) -> dict:
    e = np.array(equity)
    rets = e[1:] / e[:-1] - 1
    dd = (e / np.maximum.accumulate(e) - 1).min()
    sharpe = float(rets.mean() / rets.std() * math.sqrt(252)) if rets.std() > 0 else 0.0
    return {"return": float(e[-1] / e[0] - 1), "max_drawdown": float(dd), "sharpe": sharpe}


def random_portfolios(d: Data, start: int, end: int, n: int = 300, k: int = 6, seed: int = 7) -> np.ndarray:
    """Renditen zufälliger Depots aus k Titeln (Kaufen und Halten): Ersatz für die Konkurrenz im Planspiel."""
    rng = np.random.default_rng(seed)
    p0, p1 = d.fr.a["price"][start], d.fr.a["price"][end]
    ok = np.where(~np.isnan(p0) & ~np.isnan(p1))[0]
    r = p1[ok] / p0[ok] - 1
    return np.array([r[rng.choice(len(ok), size=min(k, len(ok)), replace=False)].mean() for _ in range(n)])


def run(d: Data, step: int, window: int, hop: int = 10) -> dict:
    n = len(d.dates)
    starts = list(range(WARMUP, n - window - 1, hop))
    res = {}
    for name, strat in STRATEGIES.items():
        rows = []
        for s in starts:
            e = s + window
            sim = simulate(d, s, e, strat, step)
            r = stats(sim["equity"])["return"]
            rand = random_portfolios(d, s, e)
            ew = float(np.nanmean(d.fr.a["price"][e] / d.fr.a["price"][s] - 1))
            dax = float(d.idx.a["price"][e, d.idx.col_index["dax"]] / d.idx.a["price"][s, d.idx.col_index["dax"]] - 1)
            rows.append({"start": str(d.dates[s].date()), "ret": r, "ew": ew, "dax": dax,
                         "pct_vs_random": float((rand < r).mean()), "fees": sim["fees"], "trades": sim["trades"]})
        df = pd.DataFrame(rows)
        res[name] = {"windows": len(df), "median_return": float(df.ret.median()), "mean_return": float(df.ret.mean()),
                     "worst": float(df.ret.min()), "best": float(df.ret.max()),
                     "beat_equal_weight": float((df.ret > df.ew).mean()), "beat_dax": float((df.ret > df.dax).mean()),
                     "mean_percentile_vs_random": float(df.pct_vs_random.mean()),
                     "share_top25pct": float((df.pct_vs_random >= 0.75).mean()),
                     "median_fees_eur": float(df.fees.median()), "median_trades": float(df.trades.median())}
        if name == "rules":
            res["_benchmarks"] = {"median_equal_weight": float(df.ew.median()), "median_dax": float(df.dax.median())}
    full = simulate(d, WARMUP, n - 1, rules.decide, step)
    res["_full_period_rules"] = {**stats(full["equity"]), "fees": full["fees"], "trades": full["trades"],
                                 "from": str(d.dates[WARMUP].date()), "to": str(d.dates[-1].date())}
    return res


def report(res: dict, window: int) -> str:
    pct = lambda x: f"{x * 100:+.1f} %"
    lines = [f"Backtest über Zeiträume von {window} Handelstagen (Länge des Spiels), Start alle 10 Tage", ""]
    lines.append(f"{'Strategie':26}{'Zeiträume':>10}{'Median':>9}{'Mittel':>9}{'Schlechtester':>15}{'> Ø aller Titel':>17}"
                 f"{'> DAX':>8}{'Ø Rang vs. Zufall':>19}{'Top 25 %':>10}{'Gebühren':>10}")
    for name in STRATEGIES:
        r = res[name]
        lines.append(f"{name:26}{r['windows']:>10}{pct(r['median_return']):>9}{pct(r['mean_return']):>9}{pct(r['worst']):>15}"
                     f"{r['beat_equal_weight'] * 100:>16.0f} %{r['beat_dax'] * 100:>7.0f} %"
                     f"{r['mean_percentile_vs_random'] * 100:>18.0f} %{r['share_top25pct'] * 100:>9.0f} %{r['median_fees_eur']:>8.0f} €")
    b, f = res["_benchmarks"], res["_full_period_rules"]
    lines += ["", f"Vergleich (Median je Zeitraum): alle Titel gleich gewichtet {pct(b['median_equal_weight'])}, DAX {pct(b['median_dax'])}",
              f"Gesamter Zeitraum {f['from']} bis {f['to']} (Regelstrategie): Rendite {pct(f['return'])}, "
              f"größter Rückgang {pct(f['max_drawdown'])}, Sharpe {f['sharpe']:.2f}, {f['trades']} Orders, {f['fees']:.0f} € Gebühren", "",
              "'Ø Rang vs. Zufall' = Anteil zufälliger 6-Titel-Depots, die die Strategie im selben Zeitraum schlägt (Ersatz für den Rang unter",
              "anderen Teams). Grenzen: heutige Indexmitglieder (zu optimistisch), keine Fundamentaldaten/News/KI, Vergangenheit ist keine Prognose."]
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--demo-dax", action="store_true")
    ap.add_argument("--demo-us", action="store_true", help="US-Aktien als Gegenprobe (nicht zum Abstimmen benutzt)")
    ap.add_argument("--universe", action="store_true")
    ap.add_argument("--symbols", help="kommagetrennte Yahoo-Symbole")
    ap.add_argument("--years", type=int, default=4)
    ap.add_argument("--step", type=int, default=2, help="Entscheidung alle N Handelstage")
    ap.add_argument("--window", type=int, default=WINDOW)
    a = ap.parse_args()
    if a.symbols:
        symbols = a.symbols.split(",")
    elif a.universe:
        symbols = [u["yf"] for u in json.load(open(os.path.join(config.DATA_DIR, "universe.json"))) if u.get("yf")]
    elif a.demo_us:
        symbols = DEMO_US
    else:
        symbols = DEMO_DAX
    d = Data(symbols, a.years)
    print(f"{len(d.cols)} Titel, {len(d.dates)} Handelstage ({d.dates[0].date()} bis {d.dates[-1].date()})")
    res = run(d, a.step, a.window)
    os.makedirs(config.DATA_DIR, exist_ok=True)
    json.dump(res, open(os.path.join(config.DATA_DIR, "backtest.json"), "w"), indent=2)
    print(report(res, a.window))


if __name__ == "__main__":
    main()
