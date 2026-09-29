import json
import os
import stat
from datetime import date

import numpy as np
import pandas as pd

from bot import brain, config, fundamentals, research, risk, rules, signals


def series(n=300, start=100.0, drift=0.001, noise=0.01, seed=1):
    rng = np.random.default_rng(seed)
    return pd.Series(start * np.cumprod(1 + drift + noise * rng.standard_normal(n)),
                     index=pd.bdate_range("2025-01-01", periods=n))


def test_frames_uptrend_metrics():
    c = pd.DataFrame({"A": series(drift=0.004, noise=0.004), "B": series(drift=-0.003, noise=0.004, seed=2)})
    idx = c["A"] * 0 + 100.0
    m = signals.Frames(c, index_close=idx).at(-1, "A")
    assert m["trend_up"] is True and m["above_sma50"] is True and m["ret_60d"] > 0 and "rel_60d" in m
    assert 0 <= m["rsi14"] <= 100 and m["atr_pct"] > 0 and m["dist_hi"] <= 0
    b = signals.Frames(c, index_close=idx).at(-1, "B")
    assert b["trend_up"] is False and b["ret_60d"] < 0


def test_frames_needs_history():
    c = pd.DataFrame({"A": series(n=40)})
    assert signals.Frames(c).at(-1, "A") is None


def test_no_lookahead():
    c = pd.DataFrame({"A": series(n=300)})
    full = signals.Frames(c)
    cut = signals.Frames(c.iloc[:250])
    assert full.at(249, "A") == cut.at(-1, "A")   # Kennzahlen am Tag 249 hängen nur von Daten bis Tag 249 ab


def idx_frames(dax_drift, vix):
    c = pd.DataFrame({"dax": series(drift=dax_drift, noise=0.003), "spx": series(drift=dax_drift, noise=0.003, seed=3),
                      "vix": pd.Series(vix, index=pd.bdate_range("2025-01-01", periods=300))})
    return signals.Frames(c)


def test_regime_labels():
    assert signals.regime_at(idx_frames(0.003, 14.0), -1)["label"] == "risk_on"
    assert signals.regime_at(idx_frames(-0.003, 35.0), -1)["label"] == "risk_off"
    r = signals.regime_at(signals.Frames(pd.DataFrame({"dax": series()})), -1)
    assert r["label"] in ("neutral", "risk_on", "risk_off")


# --- Regeln mit den neuen Kennzahlen ---
def m(**kw):
    base = {"price": 100.0, "ret_5d": 0.01, "ret_20d": 0.05, "ret_60d": 0.10, "vol_20d": 0.25,
            "above_sma50": True, "trend_up": True, "rsi14": 60.0, "atr_pct": 0.02}
    return {**base, **kw}


def test_can_buy_filters():
    assert rules.can_buy(m(), "risk_on")
    trend = {**rules.PARAMS, "trend_filter": True}   # im Backtest schadete der Trendfilter, ist daher standardmäßig aus
    assert rules.can_buy(m(above_sma50=False), "risk_on")
    assert not rules.can_buy(m(above_sma50=False), "risk_on", trend)
    assert not rules.can_buy(m(trend_up=False), "risk_on", trend)
    assert not rules.can_buy(m(rsi14=90.0), "risk_on")
    assert not rules.can_buy(m(days_to_earnings=2), "risk_on")
    assert not rules.can_buy(m(event_soon=True), "risk_on")
    assert rules.can_buy(m(days_to_earnings=10), "risk_on")
    on = {**rules.PARAMS, "regime": True}
    assert not rules.can_buy(m(rel_60d=-0.02), "risk_off", on) and rules.can_buy(m(rel_60d=0.03), "risk_off", on)


def test_overbought_lowers_score():
    assert rules.score_mix(m(rsi14=90.0)) < rules.score_mix(m(rsi14=60.0))


UNI = {i: {"name": i, "stars": 0} for i in "ABCDEFGH"}


def held(isin="A", avg=100.0, peak=None):
    return {"cash": 20000.0, "positions": {isin: {"shares": 100, "avg_price": avg, "bought": "2026-10-01",
                                                  **({"peak": peak} if peak else {})}}}


def test_trailing_stop_triggers_from_peak():
    snap = {"A": m(price=112.0, atr_pct=0.02), **{i: m(ret_60d=0.05) for i in "BCDEFGH"}}
    out = rules.decide(held(peak=135.0), UNI, snap, 50000.0, params={"trailing": True})
    sell = next(o for o in out["orders"] if o["action"] == "sell")
    assert sell["stop"] is True and "Trailing" in sell["reason"]


def test_no_trailing_stop_without_profit():
    snap = {"A": m(price=97.0), **{i: m(ret_60d=0.05) for i in "BCDEFGH"}}
    out = rules.decide(held(peak=100.0), UNI, snap, 50000.0, params={"trailing": True})
    assert not [o for o in out["orders"] if o["action"] == "sell"]


def test_risk_off_reduces_positions():
    pos = {i: {"shares": 10, "avg_price": 100.0, "bought": "2026-10-01"} for i in "ABCDEF"}
    pf = {"cash": 1000.0, "positions": pos}
    snap = {i: m(ret_60d=0.05 + 0.01 * k) for k, i in enumerate("ABCDEFGH")}
    regime = {"label": "risk_off", "score": "0/5", "exposure": 0.5, "positions": 4}
    sells = [o for o in rules.decide(pf, UNI, snap, 50000.0, regime, params={"regime": True, "n_positions": None})["orders"]
             if o["action"] == "sell"]
    assert {o["isin"] for o in sells} == {"A", "B"}   # die zwei schwächsten


def test_sector_cap_in_rules_and_risk():
    uni = {i: {"name": i, "stars": 0, "sector": "Tech" if i in "ABC" else "Energy"} for i in "ABCDEFGH"}
    snap = {i: m(ret_60d=0.30 - 0.01 * k, sector=uni[i]["sector"]) for k, i in enumerate("ABCDEFGH")}
    buys = [o["isin"] for o in rules.decide({"cash": 50000.0, "positions": {}}, uni, snap, 50000.0)["orders"]]
    assert sum(uni[i]["sector"] == "Tech" for i in buys) <= config.MAX_PER_SECTOR
    # harte Sperre in der Risikoschicht, auch für KI-Vorschläge
    pf = {"cash": 50000.0, "positions": {i: {"shares": 10, "avg_price": 100.0, "bought": "2026-10-01"} for i in "AB"}}
    ok, rej = risk.validate([{"action": "buy", "isin": "C", "amount_eur": 9000, "reason": "x"}], pf,
                            {i: 100.0 for i in "ABC"}, uni, date(2026, 10, 10))
    assert not ok and "Branche" in rej[0][1]


# --- Kontext für Claude ---
def test_context_contains_regime_research_and_limits_candidates(monkeypatch):
    uni = {f"S{i}": {"name": f"S{i}", "stars": 0} for i in range(60)}
    snap = {i: m(ret_60d=0.01 * k) for k, i in enumerate(uni)}
    ctx = brain.build_context({"cash": 1.0, "positions": {}}, uni, snap, {"S1": ["x"], "S2": []}, date(2026, 10, 5),
                              1.0, {"label": "risk_on"}, {"market": "DAX fest", "notes": {"S59": {"sentiment": 2}}})
    assert len(ctx["kandidaten"]) == config.LLM_CANDIDATES
    assert ctx["kandidaten"]["S59"]["recherche"]["sentiment"] == 2
    assert ctx["marktumfeld"]["label"] == "risk_on" and ctx["marktlage_web"] == "DAX fest" and "S2" not in ctx["schlagzeilen"]


# --- Fundamentaldaten ---
def test_fundamentals_cache_and_derived_fields(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", str(tmp_path))
    calls = []
    monkeypatch.setattr(fundamentals, "_fetch", lambda sym: calls.append(sym) or
                        {"sector": "Tech", "pe": 20.0, "earnings": "2026-10-08", "target": 120.0})
    uni = {"A": {"name": "A", "yf": "A.DE"}}
    out = fundamentals.get(uni, {"A": {"price": 100.0}}, ["A"], date(2026, 10, 5))
    assert out["A"]["days_to_earnings"] == 3 and out["A"]["target_upside"] == 0.2 and out["A"]["sector"] == "Tech"
    fundamentals.get(uni, {"A": {"price": 100.0}}, ["A"], date(2026, 10, 5))
    assert calls == ["A.DE"]   # zweiter Aufruf am selben Tag kommt aus dem Cache


# --- Web-Recherche ---
def fake_claude(tmp_path, monkeypatch, body):
    exe = tmp_path / "claude"
    exe.write_text("#!/bin/sh\n" + body)
    exe.chmod(exe.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", f"{tmp_path}:{os.environ['PATH']}")


def test_research_parses_caches_and_passes_web_tools(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", str(tmp_path / "data"))
    args = tmp_path / "args.txt"
    payload = json.dumps({"is_error": False, "structured_output": {
        "market": "ruhig", "notes": [{"isin": "A", "sentiment": -2, "summary": "Gewinnwarnung", "event_soon": True},
                                     {"isin": "FREMD", "sentiment": 2, "summary": "x"}]}})
    fake_claude(tmp_path, monkeypatch, f"cat >/dev/null\necho \"$@\" > {args}\necho '{payload}'\n")
    uni = {"A": {"name": "Alpha", "yf": "A.DE"}}
    r = research.get(uni, ["A"], date(2026, 10, 5))
    assert r["notes"]["A"]["sentiment"] == -2 and "FREMD" not in r["notes"] and "error" not in r
    assert "WebSearch,WebFetch" in args.read_text() and "--tools" in args.read_text()
    fake_claude(tmp_path, monkeypatch, "exit 1\n")   # zweiter Aufruf darf nicht mehr nötig sein
    assert research.get(uni, ["A"], date(2026, 10, 5))["cached"] is True


def test_research_failure_never_raises(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", str(tmp_path / "data"))
    fake_claude(tmp_path, monkeypatch, "cat >/dev/null\necho boom >&2\nexit 2\n")
    r = research.get({"A": {"name": "A"}}, ["A"], date(2026, 10, 6))
    assert r["notes"] == {} and "Code 2" in r["error"]
