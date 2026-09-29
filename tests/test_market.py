import numpy as np
import pandas as pd
import pytest

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


# --- Euro-Umrechnung ---
def test_load_converts_prices_to_euro_and_drops_unknown_currencies(monkeypatch):
    from bot import fx
    idx = pd.bdate_range(end="2026-09-29", periods=320)

    def dl(symbols, period="14mo", interval="1d"):
        close = pd.DataFrame({s: 100.0 * np.cumprod(1 + 0.001 + 0.004 * np.random.default_rng(len(s)).standard_normal(len(idx))) for s in symbols}, index=idx)
        return close, close * 1.01, close * 0.99, close
    monkeypatch.setattr(market, "download", dl)
    monkeypatch.setattr(fx, "download_rates", lambda ccys, period=None, **k: pd.DataFrame({"USD": 1.25}, index=idx) if "USD" in ccys else pd.DataFrame())
    uni = {"A": {"name": "A", "yf": "AAPL"}, "B": {"name": "B", "yf": "SAP.DE"}, "C": {"name": "C", "yf": "XYZ.ZZ"},
           "D": {"name": "D", "yf": "NESN.SW", "currency": "USD"}}                         # Währung im Universum überschreibt die Endung
    snap, _ = market.load(uni)
    raw, _, _, _ = dl(["AAPL", "SAP.DE"])
    assert snap["A"]["price"] == pytest.approx(raw["AAPL"].iloc[-1] / 1.25, rel=1e-3)        # Dollar-Kurs durch Kurs Dollar je Euro
    assert snap["B"]["price"] == pytest.approx(raw["SAP.DE"].iloc[-1], rel=1e-3)             # Euro-Titel unverändert
    assert "C" not in snap                                                                    # unbekannte Endung: kein Kurs statt falschem Kurs
    assert "D" in snap


def test_load_skips_symbols_with_event_jumps_and_repairs_data_glitches(monkeypatch):
    idx = pd.bdate_range(end="2026-09-29", periods=320)
    rng = np.random.default_rng(5)

    def dl(symbols, period="14mo", interval="1d"):
        close = pd.DataFrame({s: 100 * np.cumprod(1 + 0.001 + 0.008 * rng.standard_normal(len(idx))) for s in symbols}, index=idx)
        close.loc[idx[-100:], "JUMP.DE"] = close["JUMP.DE"].iloc[-100:] * 1.9                       # Sprung um 90 % ohne Gegenbewegung (Übernahmeangebot)
        base = close["GLITCH.DE"].iloc[-150]
        close.iloc[-150, close.columns.get_loc("GLITCH.DE")] = base * 6                              # Datenfehler: eine Kursspitze, am Folgetag zurück
        return close, close * 1.01, close * 0.99, close
    monkeypatch.setattr(market, "download", dl)
    uni = {s: {"name": s, "yf": s} for s in ("OK.DE", "JUMP.DE", "GLITCH.DE")}
    snap, _ = market.load(uni)
    assert "JUMP.DE" not in snap                                                                     # Ereignissprung: nicht handeln
    assert "OK.DE" in snap and "GLITCH.DE" in snap and snap["GLITCH.DE"]["mom_12_1"] < 3            # Datenfehler entfernt: kein Scheinmomentum
