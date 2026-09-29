"""Marktdaten über yfinance: Kurse (Open/High/Low/Close), Kennzahlen, Marktumfeld, Schlagzeilen."""
import pandas as pd

from . import signals

INDEX = {"dax": "^GDAXI", "spx": "^GSPC", "vix": "^VIX"}
STALE_DAYS = 6   # Titel ohne Kurs der letzten Tage (Delisting, Handelsaussetzung) werden ignoriert


def download(symbols: list, period: str = "14mo", interval: str = "1d"):
    """Gibt (close, high, low, open) als DataFrames mit einer Spalte je Symbol zurück."""
    import yfinance as yf

    d = yf.download(symbols, period=period, interval=interval, auto_adjust=True, progress=False,
                    group_by="ticker", threads=True)
    if isinstance(d.columns, pd.MultiIndex):
        out = [d.xs(f, axis=1, level=1) for f in ("Close", "High", "Low", "Open")]
    else:  # ein einzelnes Symbol
        out = [d[[f]].rename(columns={f: symbols[0]}) for f in ("Close", "High", "Low", "Open")]
    return [o.dropna(how="all").ffill(limit=3) for o in out]


def load(universe: dict):
    """universe: {isin: {name, yf, stars}} -> (snap, regime).
    snap = {isin: Kennzahlen (siehe signals.Frames.at)}, regime = Marktumfeld."""
    syms = {v["yf"]: isin for isin, v in universe.items() if v.get("yf")}
    if not syms:
        return {}, signals.regime_at(signals.Frames(pd.DataFrame({"dax": [1.0]})), -1)
    close, high, low, _ = download(list(syms) + list(INDEX.values()))
    idx_cols = {k: s for k, s in INDEX.items() if s in close.columns}
    idx = signals.Frames(close[list(idx_cols.values())].rename(columns={s: k for k, s in idx_cols.items()}))
    regime = signals.regime_at(idx, -1)
    cols = [s for s in syms if s in close.columns]
    dax = close[INDEX["dax"]] if INDEX["dax"] in close.columns else None
    fr = signals.Frames(close[cols], high[cols], low[cols], dax)
    newest = close.index[-1]
    snap = {}
    for s in cols:
        if (newest - close[s].dropna().index[-1]).days > STALE_DAYS:
            continue
        m = fr.at(-1, s)
        if m:
            snap[syms[s]] = m
    return snap, regime


def headlines(universe: dict, isins: list, per: int = 3) -> dict:
    """Schlagzeilen über yfinance. Für deutsche Titel oft leer; die Web-Recherche ergänzt das."""
    import yfinance as yf

    out = {}
    for isin in isins:
        sym = universe[isin].get("yf")
        try:
            items = yf.Ticker(sym).news[:per]
            out[isin] = [(n.get("content") or n).get("title", "") for n in items]
        except Exception:
            out[isin] = []
    return out
