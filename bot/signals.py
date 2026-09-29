"""Kennzahlen aus gängigen Handelsmethoden, vektorisiert über alle Titel.

Trend (SMA50/200), Momentum (5/20/60/120 Tage), relative Stärke gegen den Index, RSI (überkauft), ATR (Schwankung für
Stopps), Abstand zum 52-Wochen-Hoch, Volatilität. Live und im Backtest wird dieselbe Klasse benutzt, damit beide
dasselbe rechnen. Alles nutzt nur Daten bis zum jeweiligen Tag (kein Blick in die Zukunft)."""
import math

import numpy as np
import pandas as pd


def _rsi(close: pd.DataFrame, n: int = 14) -> pd.DataFrame:
    d = close.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    with np.errstate(divide="ignore", invalid="ignore"):
        return 100 - 100 / (1 + up / dn)


def _atr_pct(high, low, close, n: int = 14) -> pd.DataFrame:
    pc = close.shift(1)
    tr = np.maximum(high - low, np.maximum((high - pc).abs(), (low - pc).abs()))
    return tr.ewm(alpha=1 / n, adjust=False, min_periods=n).mean() / close


class Frames:
    """Alle Kennzahlen als Arrays (Zeilen = Handelstage, Spalten = Titel)."""

    ROUND = {"ret_5d": 4, "ret_20d": 4, "ret_60d": 4, "ret_120d": 4, "mom_12_1": 4, "vol_20d": 3, "vol_60d": 3,
             "rsi14": 1, "atr_pct": 4, "dist_hi": 3, "rel_60d": 4, "beta": 2, "beta_mkt": 2,
             "resid_60d": 4, "resid_120d": 4}

    def __init__(self, close: pd.DataFrame, high: pd.DataFrame = None, low: pd.DataFrame = None,
                 index_close: pd.Series = None):
        high = close if high is None else high
        low = close if low is None else low
        self.cols, self.dates = list(close.columns), close.index
        f = {"price": close}
        for n in (5, 20, 60, 120):
            f[f"ret_{n}d"] = close / close.shift(n) - 1
        daily = close / close.shift(1) - 1
        f["mom_12_1"] = close.shift(21) / close.shift(252) - 1    # 12-Monats-Momentum ohne den letzten Monat
        f["vol_20d"] = daily.rolling(20).std() * math.sqrt(252)
        f["vol_60d"] = daily.rolling(60).std() * math.sqrt(252)
        f["sma50"], f["sma200"] = close.rolling(50).mean(), close.rolling(200).mean()
        f["rsi14"] = _rsi(close)
        f["atr_pct"] = _atr_pct(high, low, close)
        f["dist_hi"] = close / close.rolling(252, min_periods=120).max() - 1
        if index_close is not None:
            idx = index_close.reindex(close.index).ffill()
            f["rel_60d"] = f["ret_60d"].sub(idx / idx.shift(60) - 1, axis=0)
            idx_d = idx / idx.shift(1) - 1
            f["beta"] = daily.rolling(120).cov(idx_d).div(idx_d.rolling(120).var(), axis=0)
        # Eigener "Markt" aus dem Durchschnitt aller Titel dieser Gruppe: Beta, Residual-Momentum und Marktschwankung
        mkt = daily.mean(axis=1)
        f["beta_mkt"] = daily.rolling(120).cov(mkt).div(mkt.rolling(120).var(), axis=0)
        logm = np.log1p(mkt.fillna(0.0))
        self.mkt = {"vol_60d": (mkt.rolling(60).std() * math.sqrt(252)).to_numpy(dtype=float)}
        for n in (60, 120):
            m_n = np.expm1(logm.rolling(n).sum())
            self.mkt[f"ret_{n}d"] = m_n.to_numpy(dtype=float)
            f[f"resid_{n}d"] = f[f"ret_{n}d"].sub(f["beta_mkt"].mul(m_n, axis=0))   # Rendite ohne Marktanteil
        self.a = {k: v.to_numpy(dtype=float) for k, v in f.items()}
        self.col_index = {c: j for j, c in enumerate(self.cols)}

    def __len__(self):
        return len(self.dates)

    def at(self, pos: int, col) -> dict | None:
        """Kennzahlen eines Titels am Tag `pos` (negativ = von hinten). None, wenn zu wenig Historie."""
        j = self.col_index[col]
        price = self.a["price"][pos, j]
        core = (price, self.a["ret_5d"][pos, j], self.a["ret_20d"][pos, j], self.a["ret_60d"][pos, j], self.a["vol_20d"][pos, j])
        if any(np.isnan(v) for v in core):   # Kerndaten unvollständig (Datenlücke, zu kurze Historie): Titel auslassen
            return None
        out = {"price": round(float(price), 3)}
        for k, nd in self.ROUND.items():
            if k in self.a:
                v = self.a[k][pos, j]
                if not np.isnan(v):
                    out[k] = round(float(v), nd)
        s50, s200 = self.a["sma50"][pos, j], self.a["sma200"][pos, j]
        if not np.isnan(s50):
            out["above_sma50"] = bool(price > s50)
        if not np.isnan(s200):
            out["above_sma200"] = bool(price > s200)
        if not (np.isnan(s50) or np.isnan(s200)):
            out["trend_up"] = bool(s50 > s200)
        return out

    def market_at(self, pos: int) -> dict:
        """Eigener Marktdurchschnitt der Gruppe: Rendite 60/120 Tage und Schwankung."""
        return {k: (None if np.isnan(v[pos]) else float(v[pos])) for k, v in self.mkt.items()}

    def price_at(self, pos: int, col) -> float:
        return float(self.a["price"][pos, self.col_index[col]])


# Marktumfeld: (Anteil des Depots, der investiert sein soll, Anzahl Positionen)
REGIME_TABLE = {"risk_on": (0.97, 6), "neutral": (0.80, 5), "risk_off": (0.50, 4)}


def regime_at(idx: Frames, pos: int) -> dict:
    """Marktumfeld aus DAX, S&P 500 und VIX. Fünf einfache Prüfungen; fehlende Daten zählen nicht mit."""
    checks = {}

    def get(name, key):
        if name not in idx.col_index:
            return None
        v = idx.a[key][pos, idx.col_index[name]]
        return None if np.isnan(v) else float(v)

    for name in ("dax", "spx"):
        p, s200, s50, r20 = get(name, "price"), get(name, "sma200"), get(name, "sma50"), get(name, "ret_20d")
        if p is not None and s200 is not None:
            checks[f"{name} über SMA200"] = p > s200
        if name == "dax" and p is not None and s50 is not None:
            checks["dax über SMA50"] = p > s50
        if name == "dax" and r20 is not None:
            checks["dax 20 Tage positiv"] = r20 > 0
    vix = get("vix", "price")
    if vix is not None:
        checks["VIX unter 22"] = vix < 22
    score, n = sum(checks.values()), len(checks)
    if n < 3:
        label = "neutral"  # zu wenig Daten: weder aggressiv noch defensiv
    else:
        share = score / n
        label = "risk_on" if share >= 0.8 else "neutral" if share >= 0.4 else "risk_off"
    exposure, positions = REGIME_TABLE[label]
    return {"label": label, "score": f"{score}/{n}", "exposure": exposure, "positions": positions,
            "checks": {k: bool(v) for k, v in checks.items()}, "vix": vix,
            "dax_ret_20d": get("dax", "ret_20d"), "spx_ret_20d": get("spx", "ret_20d")}
