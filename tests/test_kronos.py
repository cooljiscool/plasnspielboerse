import json
from datetime import date

import numpy as np
import pandas as pd
import pytest

from bot import config, kronos_signal, rules
from bot.kronos_signal import KronosSignal


class FakePredictor:
    """Ersatz für KronosPredictor: sagt für jeden Titel +5 % voraus, wenn der letzte Kurs gerade ist, sonst -5 %."""
    calls = []

    def predict_batch(self, dfs, xts, yts, pred_len, T, top_p, sample_count, verbose):
        FakePredictor.calls.append((len(dfs), pred_len, sample_count))
        out = []
        for df, y in zip(dfs, yts):
            last = df["close"].iloc[-1]
            assert len(df) == 256 and len(y) == pred_len and not df.isna().any().any()
            factor = 1.05 if int(round(last)) % 2 == 0 else 0.95
            out.append(pd.DataFrame({"close": [last * factor] * pred_len}, index=y))
        return out


def frame(n=300, start=100.0, nan_at=None):
    idx = pd.bdate_range(end="2026-09-29", periods=n)
    f = pd.DataFrame({"open": start, "high": start * 1.01, "low": start * 0.99, "close": start, "volume": 1000.0}, index=idx)
    if nan_at is not None:
        f.iloc[nan_at, f.columns.get_loc("close")] = np.nan
    return f


def test_forecast_returns_predicted_return_and_skips_bad_series():
    sig = KronosSignal(predictor=FakePredictor(), horizon=10, context=256)
    frames = {"gerade": frame(start=100.0), "ungerade": frame(start=101.0), "kurz": frame(n=100), "lücke": frame(nan_at=-5)}
    out = sig.forecast(frames)
    assert out == {"gerade": 0.05, "ungerade": -0.05}   # zu kurze und lückenhafte Historien fehlen


def test_forecast_fills_missing_volume_and_chunks(monkeypatch):
    monkeypatch.setattr(kronos_signal, "CHUNK", 2)
    FakePredictor.calls = []
    f = frame(start=100.0); f["volume"] = np.nan
    out = KronosSignal(predictor=FakePredictor()).forecast({f"S{i}": f for i in range(5)})
    assert len(out) == 5 and [c[0] for c in FakePredictor.calls] == [2, 2, 1]


def test_get_caches_per_day_and_model(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", str(tmp_path))
    uni = {"A": {"yf": "A.DE"}, "B": {"yf": "B.DE"}, "C": {}}
    downloads = []
    dl = lambda syms, period: downloads.append(list(syms)) or {s: frame(start=100.0) for s in syms}
    sig = KronosSignal(predictor=FakePredictor())
    out = kronos_signal.get(uni, ["A", "B", "C"], date(2026, 9, 29), sig, dl)
    assert out == {"A": 0.05, "B": 0.05} and downloads == [["A.DE", "B.DE"]]
    kronos_signal.get(uni, ["A", "B"], date(2026, 9, 29), sig, dl)
    assert len(downloads) == 1                                        # zweiter Aufruf am selben Tag: Cache
    kronos_signal.get(uni, ["A", "B"], date(2026, 9, 30), sig, dl)
    assert len(downloads) == 2                                        # neuer Tag: neu berechnen
    assert json.load(open(tmp_path / "kronos.json"))["tag"].startswith("2026-09-30")


def test_available_reports_missing_setup(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "KRONOS_DIR", str(tmp_path / "gibt-es-nicht"))
    ok, why = kronos_signal.available()
    assert not ok and ("PyTorch" in why or "Kronos-Code" in why)
    with pytest.raises(RuntimeError):
        KronosSignal().forecast({"A": frame()})


# --- Neusortierung der Momentum-Favoriten ---
UNI = {f"S{i:02d}": {"name": f"T{i}", "stars": 0} for i in range(30)}


def snap(kronos=True):
    s = {i: {"price": 100.0, "ret_5d": 0.0, "ret_20d": 0.02, "ret_60d": 0.01 * k, "vol_20d": 0.25} for k, i in enumerate(UNI)}
    if kronos:   # Kronos mag genau die schwächeren der Top 15 (S15..S19 hoch, S25..S29 niedrig)
        for k, i in enumerate(UNI):
            if 15 <= k:
                s[i]["kronos_ret"] = 0.01 * (k - 15) + (0.3 if k < 20 else 0.0)
    return s


def test_kronos_weight_zero_changes_nothing():
    s = snap()
    for i in list(UNI)[15:]:
        s[i]["kronos_ret"] = 0.5
    base = rules.decide({"cash": 50000.0, "positions": {}}, UNI, s, 50000.0)
    with_k = rules.decide({"cash": 50000.0, "positions": {}}, UNI, s, 50000.0, params={"kronos_weight": 0.0})
    assert base == with_k


def test_kronos_reorders_only_within_top15():
    s = {i: {"price": 100.0, "ret_5d": 0.0, "ret_20d": 0.02, "ret_60d": 0.01 * k, "vol_20d": 0.25, "kronos_ret": float(-k)}
         for k, i in enumerate(UNI)}   # Kronos bevorzugt genau die schwächsten
    ranked = sorted(s, key=lambda i: s[i]["ret_60d"], reverse=True)
    out = rules.kronos_reorder(ranked, s, 1.0, k=15)
    assert set(out[:15]) == set(ranked[:15]) and out[15:] == ranked[15:]     # Auswahl bleibt, nur Reihenfolge ändert sich
    assert out[:15] == ranked[:15][::-1]                                     # Gewicht 1: Kronos entscheidet allein
    assert rules.kronos_reorder(ranked, s, 0.0) == ranked
    s2 = {i: {k: v for k, v in m.items() if k != "kronos_ret"} for i, m in s.items()}
    assert rules.kronos_reorder(ranked, s2, 1.0) == ranked                   # ohne Prognosen unverändert


def test_kronos_changes_buys_when_weighted():
    s = snap()
    plain = {o["isin"] for o in rules.decide({"cash": 50000.0, "positions": {}}, UNI, s, 50000.0)["orders"]}
    weighted = {o["isin"] for o in rules.decide({"cash": 50000.0, "positions": {}}, UNI, s, 50000.0, params={"kronos_weight": 0.5})["orders"]}
    assert plain and weighted and plain <= set(list(UNI)[10:])
