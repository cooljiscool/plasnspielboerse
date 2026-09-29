import numpy as np
import pandas as pd

from bot import market


def fake_download(symbols, period="14mo", interval="1d"):
    idx = pd.bdate_range(end="2026-09-29", periods=320)
    rng = np.random.default_rng(3)
    close = pd.DataFrame({s: 100 * np.cumprod(1 + 0.001 + 0.01 * rng.standard_normal(len(idx))) for s in symbols}, index=idx)
    close["DEAD.DE"] = np.nan                       # delistetes Symbol: leere Spalte
    close.loc[:"2026-06-01", "OLD.DE"] = 50.0       # Kurs seit Monaten eingefroren: zu alt
    close.loc["2026-06-02":, "OLD.DE"] = np.nan
    return close, close * 1.01, close * 0.99, close


def test_load_skips_dead_and_stale_symbols(monkeypatch):
    monkeypatch.setattr(market, "download", fake_download)
    uni = {s: {"name": s, "yf": s} for s in ("A.DE", "B.DE", "C.DE", "DEAD.DE", "OLD.DE")}
    snap, regime = market.load(uni)
    assert set(snap) == {"A.DE", "B.DE", "C.DE"}
    assert regime["mkt_vol_60d"] and regime["label"] in ("risk_on", "neutral", "risk_off")
    assert {"ret_60d", "ret_120d", "mom_12_1", "vol_20d"} <= set(snap["A.DE"])


def test_load_without_symbols():
    snap, regime = market.load({"X": {"name": "X"}})
    assert snap == {} and regime["label"] == "neutral"
