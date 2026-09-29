import json
import os
import stat
from datetime import date

import numpy as np
import pandas as pd
import pytest

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
                        {"sector": "Tech", "pe": 20.0, "earnings": "2026-10-08", "target_upside": 0.2})
    uni = {"A": {"name": "A", "yf": "A.DE"}}
    out = fundamentals.get(uni, {"A": {"price": 100.0}}, ["A"], date(2026, 10, 5))
    assert out["A"]["days_to_earnings"] == 3 and out["A"]["target_upside"] == 0.2 and out["A"]["sector"] == "Tech"
    fundamentals.get(uni, {"A": {"price": 100.0}}, ["A"], date(2026, 10, 5))
    assert calls == ["A.DE"]   # zweiter Aufruf am selben Tag kommt aus dem Cache


def test_target_upside_uses_yahoos_own_price_and_target_in_the_same_currency(monkeypatch):
    """Kursziel (Dollar) und Kurs (Euro nach Umrechnung) dürfen nie gemischt werden: der Aufschlag kommt aus Yahoos Kurs derselben Währung."""
    import types
    info = {"currentPrice": 200.0, "targetMeanPrice": 250.0, "sector": "Tech", "trailingPE": 25.0}
    fake = types.SimpleNamespace(Ticker=lambda sym: types.SimpleNamespace(info=info, calendar={}))
    monkeypatch.setitem(__import__("sys").modules, "yfinance", fake)
    out = fundamentals._fetch("AAPL")
    assert out["target_upside"] == 0.25 and "target" not in out
    info.pop("currentPrice")
    assert "target_upside" not in fundamentals._fetch("AAPL")                                   # ohne Kurs kein Aufschlag statt falscher Rechnung


def test_old_cache_entries_with_raw_target_are_dropped(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", str(tmp_path))
    (tmp_path / "fundamentals.json").write_text('{"date": "2026-10-05", "items": {"A": {"sector": "Tech", "target": 120.0}}}')
    out = fundamentals.get({"A": {"name": "A", "yf": "A"}}, {"A": {"price": 100.0}}, ["A"], date(2026, 10, 5))
    assert "target_upside" not in out["A"] and "target" not in out["A"]


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


# --- Risikoprofil ---
def test_risk_profile_orders_calm_and_wild_series():
    calm = series(n=300, drift=0.0005, noise=0.005, seed=4)
    wild = series(n=300, drift=0.0, noise=0.035, seed=5)
    a, b = signals.risk_profile(calm.to_numpy()), signals.risk_profile(wild.to_numpy())
    assert a["vola_jahr"] < b["vola_jahr"] and a["risikostufe"] < b["risikostufe"]
    assert a["max_rueckgang_1j"] > b["max_rueckgang_1j"] and a["var95_10_tage"] > b["var95_10_tage"]      # ruhiger: kleinerer Rückgang, kleinerer Verlust
    assert 1 <= a["risikostufe"] <= 5 and -1 < b["max_rueckgang_1j"] <= 0 and b["var95_10_tage"] < 0


def test_risk_profile_deep_crash_raises_level_and_short_history_gives_nothing():
    prices = np.r_[np.linspace(100, 100, 150), np.linspace(100, 40, 60), np.linspace(40, 45, 60)]
    p = signals.risk_profile(prices)
    assert p["max_rueckgang_1j"] <= -0.55
    base_level = 1 if p["vola_jahr"] < 0.2 else 2 if p["vola_jahr"] < 0.3 else 3 if p["vola_jahr"] < 0.4 else 4 if p["vola_jahr"] < 0.55 else 5
    assert p["risikostufe"] == min(5, base_level + 1)
    assert signals.risk_profile(np.arange(1.0, 100.0)) == {} and signals.risk_profile([np.nan] * 300) == {}


def test_risk_profile_ignores_nan_gaps():
    s = series(n=300, seed=6).to_numpy().copy(); s[50] = np.nan; s[120] = np.nan
    assert signals.risk_profile(s)["vola_jahr"] > 0


# --- Datenfehler in Kurshistorien ---
def frames_from(cols: dict):
    idx = pd.bdate_range("2026-01-01", periods=len(next(iter(cols.values()))))
    close = pd.DataFrame(cols, index=idx)
    return close, close * 1.01, close * 0.99, close.copy()


def test_clean_prices_removes_spikes_that_reverse_and_non_positive_prices():
    c, h, l, o = frames_from({
        "SPIKE": [100, 101, 500, 102, 103, 104, 103, 102],                  # +395 %, am nächsten Tag zurück: Datenfehler
        "DIP": [100, 101, 20, 100, 101, 102, 103, 102],                     # Kurs stürzt und erholt sich sofort: Datenfehler
        "NEG": [100, 101, -60, 102, 103, 104, 103, 102],                    # negativer Kurs
        "JUMP": [100, 101, 190, 191, 192, 190, 191, 192],                   # echter Sprung ohne Gegenbewegung (Übernahmeangebot)
        "CALM": [100, 101, 100, 102, 101, 103, 102, 101]})
    cc, hh, ll, oo = signals.clean_prices(c, h, l, o)
    assert np.isnan(cc["SPIKE"].iloc[2]) and np.isnan(cc["DIP"].iloc[2]) and np.isnan(cc["NEG"].iloc[2])
    assert np.isnan(hh["SPIKE"].iloc[2]) and np.isnan(ll["SPIKE"].iloc[2]) and np.isnan(oo["SPIKE"].iloc[2])       # High, Low, Open desselben Tages ebenfalls
    assert cc["SPIKE"].iloc[3] == 102 and cc["SPIKE"].iloc[1] == 101                                              # Nachbartage bleiben
    assert cc["JUMP"].iloc[2] == 190 and cc["CALM"].isna().sum() == 0                                             # echte Sprünge bleiben
    assert c["SPIKE"].iloc[2] == 500                                                                               # Eingabe unverändert
    assert cc.ffill().loc[:, "SPIKE"].iloc[2] == 101                                                               # anschließendes Auffüllen nimmt den letzten guten Kurs


def test_clean_prices_handles_alternating_error_chains():
    c, h, l, o = frames_from({"CHAIN": [100, 400, 80, 400, 80, 100, 101, 102]})   # +300 %, -80 %, +400 %, -80 %: wechselnde Fehler
    cc = signals.clean_prices(c, h, l, o)[0]
    ok = cc["CHAIN"].dropna()
    assert ok.max() < 150 and ok.min() > 70                                        # keine Ausreißer mehr


def test_max_jump_reports_the_largest_daily_move_in_the_recent_window():
    c, *_ = frames_from({"A": [100, 101, 190, 191, 190, 191, 190, 191], "B": [100, 101, 100, 102, 101, 103, 102, 101]})
    j = signals.max_jump(c, days=6)
    assert j["A"] == pytest.approx(0.881, abs=0.01) and j["B"] < 0.05
    assert signals.max_jump(c, days=3)["A"] < 0.05                                 # der Sprung liegt außerhalb des Fensters


# --- Nachhaltigkeitsplätze ---
def nh_setup():
    uni = {i: {"name": i, "stars": 1 if i in ("C", "H", "M") else 0} for i in "ABCDEFGHIJKLMN"}
    snap = {i: m(ret_60d=0.02 + 0.01 * k) for k, i in enumerate("ABCDEFGHIJKLMN")}         # N ist das stärkste, A das schwächste
    return uni, snap


def test_nh_slots_reserve_places_for_the_strongest_starred_titles():
    uni, snap = nh_setup()
    base = [o["isin"] for o in rules.decide({"cash": 50000.0, "positions": {}}, uni, snap, 50000.0)["orders"]]
    assert base == ["M", "N", "L", "K", "J", "I"]                                             # ohne Reservierung: Momentum (M trägt zufällig einen Stern, der Bonus von 1 Punkt hebt es an N vorbei)
    two = rules.decide({"cash": 50000.0, "positions": {}}, uni, snap, 50000.0, params={"nh_slots": 2})["orders"]
    assert [o["isin"] for o in two] == ["M", "H", "N", "L", "K", "J"]                          # zuerst die zwei stärksten Sterntitel (M, H), dann der Rest nach Rang
    assert sum(uni[o["isin"]]["stars"] for o in two) == 2 and all(o["action"] == "buy" for o in two) and len(two) == 6
    assert "Nachhaltigkeits-Stern" in two[1]["reason"]


def test_nh_slots_count_starred_positions_already_held_and_fill_up_with_others_if_stars_run_out():
    uni, snap = nh_setup()
    pos = {"C": {"shares": 10, "avg_price": 100.0, "bought": "2026-10-01"}, "N": {"shares": 10, "avg_price": 100.0, "bought": "2026-10-01"}}
    pf = {"cash": 40000.0, "positions": pos}
    buys = [o["isin"] for o in rules.decide(pf, uni, snap, 50000.0, params={"nh_slots": 2, "keep_frac": 1.0})["orders"] if o["action"] == "buy"]
    assert buys[0] == "M" and len(buys) == 4                                                   # C ist schon im Depot: nur ein weiterer Sterntitel (der stärkste, M), Rest nach Rang
    uni2 = {i: {"name": i, "stars": 1 if i == "A" else 0} for i in "ABCDEFGHIJKLMN"}
    few = rules.decide({"cash": 50000.0, "positions": {}}, uni2, snap, 50000.0, params={"nh_slots": 4})["orders"]
    assert len(few) == 6 and [o["isin"] for o in few][0] == "A" and sum(uni2[o["isin"]]["stars"] for o in few) == 1      # nur ein Sterntitel vorhanden: übrige Plätze nach Rang


def test_nh_slots_default_is_off_and_never_buys_a_title_twice():
    assert rules.PARAMS["nh_slots"] == 0
    uni, snap = nh_setup()
    orders = rules.decide({"cash": 50000.0, "positions": {}}, uni, snap, 50000.0, params={"nh_slots": 6})["orders"]
    ids = [o["isin"] for o in orders]
    assert len(ids) == len(set(ids)) == 6 and set(ids) >= {"C", "H", "M"}                        # alle drei Sterntitel, keine Doppelkäufe


def test_nh_slots_come_from_the_environment_within_bounds(monkeypatch):
    import importlib
    try:
        for raw, expected in (("", 0), ("2", 2), ("99", 6), ("-3", 0)):
            monkeypatch.setenv("BOT_NH_SLOTS", raw)
            assert importlib.reload(config).NH_SLOTS == expected
        monkeypatch.setenv("BOT_NH_SLOTS", "2")
        importlib.reload(config)
        assert importlib.reload(rules).PARAMS["nh_slots"] == 2
    finally:
        monkeypatch.delenv("BOT_NH_SLOTS")
        importlib.reload(config)
        importlib.reload(rules)
