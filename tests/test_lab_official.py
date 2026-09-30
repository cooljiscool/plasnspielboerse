import json
import sys
import types

import numpy as np
import pandas as pd
import pytest

from bot import config, fx, lab

IDX = pd.bdate_range("2026-01-01", periods=30)


def fake_yf(calls):
    def download(syms, **kw):
        calls.append(list(syms))
        cols = pd.MultiIndex.from_product([syms, ["Close", "High", "Low", "Open"]])
        return pd.DataFrame(np.full((len(IDX), len(cols)), 100.0), index=IDX, columns=cols)
    return types.SimpleNamespace(download=download)


def test_load_history_converts_to_euro_and_caches(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setitem(sys.modules, "yfinance", fake_yf(calls))
    monkeypatch.setattr(fx, "download_rates", lambda ccys, period=None, start=None, **k: pd.DataFrame({"USD": 1.25}, index=IDX))
    cache = str(tmp_path / "cache" / "history_official.pkl")
    h = lab.load_history(cache, symbols=["AAA", "BBB.DE"], currencies={"AAA": "USD", "BBB.DE": "EUR"})
    assert set(h) == {"close", "high", "low", "open"}
    assert h["close"]["AAA"].iloc[0] == pytest.approx(80.0) and h["close"]["BBB.DE"].iloc[0] == 100.0        # Dollar-Kurs in Euro, Euro-Kurs unverändert
    assert h["close"]["^GSPC"].iloc[0] == 100.0                                                                # Indizes bleiben unverändert
    assert h["open"]["AAA"].iloc[0] == pytest.approx(80.0) and len(calls) == 1
    lab.load_history(cache, symbols=["AAA", "BBB.DE"], currencies={"AAA": "USD", "BBB.DE": "EUR"})
    assert len(calls) == 1                                                                                      # zweiter Aufruf aus dem Zwischenspeicher


def test_load_history_without_currencies_keeps_local_prices(tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, "yfinance", fake_yf([]))
    h = lab.load_history(str(tmp_path / "h.pkl"), symbols=["AAA"])
    assert h["close"]["AAA"].iloc[0] == 100.0


def test_official_report_needs_a_universe_from_the_official_import(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", str(tmp_path))
    (tmp_path / "universe.json").write_text(json.dumps([{"isin": "SAP.DE", "name": "SAP", "yf": "SAP.DE"}]))
    with pytest.raises(SystemExit, match="official"):
        lab._official_report(False, False)


# --- Nachhaltigkeitsertrag ---
def test_nh_yield_sums_gains_of_traded_star_titles_only():
    sim = {"flows": {"A": [8000.0, 0.0], "B": [8000.0, 9500.0], "C": [8000.0, 0.0]}, "held_value": {"A": 9000.0, "C": 7000.0}}
    assert lab.nh_yield(sim, {"A", "B"}) == pytest.approx((9000 - 8000) + (9500 - 8000))            # A hält 1.000 Gewinn (unrealisiert), B 1.500 realisiert; C ohne Stern zählt nicht
    assert lab.nh_yield(sim, {"C"}) == pytest.approx(-1000.0) and lab.nh_yield(sim, set()) == 0.0
    assert lab.nh_yield({"flows": {}, "held_value": {}}, {"A"}) == 0.0


def test_random_nh_yields_are_sums_of_equal_sized_positions():
    class Fr:
        a = {"price": np.array([[100.0, 100.0, 100.0, 100.0], [110.0, 90.0, 120.0, np.nan]])}
        col_index = {"A": 0, "B": 1, "C": 2, "D": 3, "X": 4}
    h = types.SimpleNamespace(fr=Fr)
    y = lab.random_nh_yields(h, 0, 1, {"A", "B", "C", "D"}, n=50, k=3, amount=1000.0)
    # D hat am Ende keinen Kurs und entfällt; die drei übrigen (+10 %, -10 %, +20 %) ergeben genau eine Kombination
    assert np.allclose(y, 1000.0 * (0.10 - 0.10 + 0.20))
    y2 = lab.random_nh_yields(h, 0, 1, {"A", "B", "C"}, n=50, k=2, amount=1000.0)
    assert set(np.round(y2, 6)) <= {0.0, 300.0, 100.0}                                                # Paare: A+B = 0, A+C = 300, B+C = 100


# --- Trefferquote ---
def fake_days(n_titles=30, n=60, vol=0.2):
    """30 Titel; Titel j hat den Score 0,01·j und steigt (j > 10), fällt (j < 10) oder bleibt gleich (j = 10)."""
    price = np.array([[100 * (1 + 0.002 * (j - 10) * t) for j in range(n_titles)] for t in range(n)])
    names = [f"T{j}" for j in range(n_titles)]
    snaps = {t: {c: {"price": 100.0, "vol_20d": vol, "ret_20d": 0.0, "ret_60d": 0.01 * j, "ret_120d": 0.01 * j, "mom_12_1": 0.01 * j} for j, c in enumerate(names)} for t in range(n)}
    return types.SimpleNamespace(dates=pd.bdate_range("2026-01-01", periods=n), snap=lambda i: snaps[i], fr=types.SimpleNamespace(a={"price": price}, col_index={c: j for j, c in enumerate(names)}))


def test_forward_returns_pick_the_six_strongest_titles_and_measure_rank_correlation():
    d = fake_days()
    r = lab.forward_returns(d, 5, 10)
    assert len(r["pick"]) == 6 and (r["pick"] > 0).all() and len(r["alle"]) == 30
    assert r["ic"] == pytest.approx(1.0)                                                       # Score und spätere Rendite steigen gleichmäßig
    assert r["pick"].min() > np.median(r["alle"])
    assert lab.forward_returns(d, 55, 10) is None                                              # Haltedauer reicht über die Daten hinaus
    assert lab.forward_returns(fake_days(vol=0.9), 5, 10) is None                              # nichts kaufbar (Schwankung über 55 %)


def test_hit_stats_counts_buys_above_zero_and_above_the_median_title():
    d = fake_days()
    s = lab.hit_stats([lab.forward_returns(d, i, 10) for i in (5, 7, 9)])
    assert s["kaeufe"] == 18 and s["starts"] == 3
    assert s["plus"] == 1.0 and s["ueber_median"] == 1.0 and s["ic"] == pytest.approx(1.0)
    assert s["alle_plus"] == pytest.approx(19 / 30)                                            # 19 der 30 Titel steigen, einer bleibt gleich, zehn fallen
    assert s["ueberrendite"] > 0 and s["t"] > 2


def test_hit_stats_with_a_single_start_has_no_t_value_and_without_results_nothing():
    assert lab.hit_stats([lab.forward_returns(fake_days(), 5, 10)])["t"] == 0.0
    assert lab.hit_stats([]) is None


def scripted_positions():
    """Kursdaten und Depotstände, die `simulate` an den Tagen 2, 4, 6, 8 und 10 der Strategie zeigt: A wird zwischen Tag 6 und 8 verkauft, B bleibt, C kommt an Tag 9 dazu."""
    dates = pd.bdate_range("2026-01-01", periods=30)
    base = {"A": 10.0, "B": 20.0, "C": 30.0}
    opn = np.array([[base[c] + i + 0.5 for c in "ABC"] for i in range(30)])
    opn[7, 0] = np.nan                                                                          # kein Eröffnungskurs: Schlusskurs des Vortags gilt
    d = types.SimpleNamespace(dates=dates, open=opn, fr=types.SimpleNamespace(col_index={"A": 0, "B": 1, "C": 2}), px=lambda i, c: base[c] + i)
    day = lambda i: dates[i].date().isoformat()
    states = [{}, {"A": (10.0, day(3))}, {"A": (10.0, day(3)), "B": (20.0, day(5))}, {"B": (20.0, day(5))}, {"B": (20.0, day(5)), "C": (30.0, day(9))}]
    return d, dates, states


def scripted_simulate(states, held_at_end, seen):
    def fake(d, s, e, strategy, step=2, capital=50000.0):
        for st in states:
            pf = {"positions": {c: {"avg_price": p, "bought": b} for c, (p, b) in st.items()}}
            seen.append(strategy(pf, {}, {}, 0.0, None))
        return {"held_value": {c: 1.0 for c in held_at_end}}
    return fake


def test_position_outcomes_finds_sales_between_calls_and_open_positions(monkeypatch):
    d, dates, states = scripted_positions()
    seen = []
    monkeypatch.setattr(lab.bt, "simulate", scripted_simulate(states, ["B", "C"], seen))
    out = lab.position_outcomes(d, [(2026, 2, 12)], lambda *a: {"orders": []})
    assert seen == [{"orders": []}] * 5                                                         # die Strategie wird unverändert durchgereicht
    a, b, c = (out[out["isin"] == x].iloc[0] for x in "ABC")
    assert (a.ausstieg, a.offen, a.tage) == (16.0, False, (dates[7].date() - dates[3].date()).days)   # zwischen Aufruf 3 und 4 verkauft, Tag 7: Eröffnungskurs fehlt, Schlusskurs von Tag 6
    assert (b.ausstieg, b.offen, b.tage) == (32.0, True, (dates[12].date() - dates[5].date()).days)   # bis zum letzten Tag (12) gehalten, Schlusskurs
    assert (c.ausstieg, c.offen) == (42.0, True)
    assert list(out.jahr.unique()) == [2026] and len(out) == 3


def test_position_outcomes_finds_a_sale_after_the_last_call(monkeypatch):
    d, dates, states = scripted_positions()
    monkeypatch.setattr(lab.bt, "simulate", scripted_simulate(states, ["B"], []))                # C fehlt am Ende: nach dem letzten Aufruf (Tag 10) verkauft
    out = lab.position_outcomes(d, [(2026, 2, 12)], lambda *a: {"orders": []})
    c = out[out["isin"] == "C"].iloc[0]
    assert (c.ausstieg, c.offen) == (41.5, False)                                               # Eröffnungskurs von Tag 11


def test_summarize_positions():
    df = pd.DataFrame({"einstand": [100.0] * 4, "ausstieg": [150.0, 110.0, 90.0, 80.0], "tage": [100, 60, 20, 30]})
    s = lab.summarize_positions(df)
    assert s["n"] == 4 and s["plus"] == 0.5 and s["gewinn"] == pytest.approx(0.3) and s["verlust"] == pytest.approx(-0.15)
    assert s["mittel"] == pytest.approx(0.075) and s["median"] == pytest.approx(0.0) and s["tage"] == 52.5
    assert s["anteil_beste"] == pytest.approx(0.5 / 0.3)                                        # bester Trade allein bringt mehr als das Gesamtergebnis, weil die Verlierer es mindern


def test_hit_report_needs_the_official_universe(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", str(tmp_path))
    (tmp_path / "universe.json").write_text(json.dumps([{"isin": "SAP.DE", "name": "SAP", "yf": "SAP.DE"}]))
    with pytest.raises(SystemExit, match="official"):
        lab._hit_report(False, False)


def test_hit_report_runs_on_a_small_universe(monkeypatch, capsys):
    idx = pd.bdate_range("2019-01-01", periods=1600)
    rng = np.random.default_rng(1)
    syms = [f"T{j}.DE" for j in range(25)]
    close = pd.DataFrame({s: 100 * np.cumprod(1 + 0.0004 + 0.01 * rng.standard_normal(len(idx))) for s in syms}, index=idx)
    for ix in ("^GDAXI", "^GSPC", "^VIX"):
        close[ix] = 100 * np.cumprod(1 + 0.0003 + 0.008 * rng.standard_normal(len(idx)))
    hist = {"close": close, "high": close * 1.005, "low": close * 0.995, "open": close}
    monkeypatch.setattr(lab, "_official_rows", lambda: [{"yf": s, "markt": "dax", "currency": "EUR"} for s in syms])
    monkeypatch.setattr(lab, "_official_history", lambda rows, refresh: hist)
    lab._hit_report(False, True)
    out = capsys.readouterr().out
    assert "A) Käufe zum Start der" in out and "B) Käufe an beliebigen Tagen" in out and "C) Was aus den Positionen" in out
    assert out.count(" Tage") >= 8 and "alle Positionen" in out and "je Planspiel-Jahr" in out and "2020/21" in out
    assert "zu wenig Kursdaten   (nur Jahre bis 2014)" in out                                     # die Testdaten beginnen 2019: kein früher Teil, aber kein Absturz


def test_protocol_report_lists_every_order_with_reason_and_result_per_style(monkeypatch, capsys):
    idx = pd.bdate_range("2019-01-01", periods=1600)
    rng = np.random.default_rng(2)
    syms = [f"T{j}.DE" for j in range(25)]
    close = pd.DataFrame({s: 100 * np.cumprod(1 + 0.0005 + 0.012 * rng.standard_normal(len(idx))) for s in syms}, index=idx)
    for ix in ("^GDAXI", "^GSPC", "^VIX"):
        close[ix] = 100 * np.cumprod(1 + 0.0003 + 0.008 * rng.standard_normal(len(idx)))
    hist = {"close": close, "high": close * 1.005, "low": close * 0.995, "open": close}
    rows = [{"yf": s, "isin": f"DE000000{j:04d}", "name": f"Firma {j}", "markt": "dax", "currency": "EUR", "sector": "A" if j % 2 else "B"} for j, s in enumerate(syms)]
    monkeypatch.setattr(lab, "_official_rows", lambda: rows)
    monkeypatch.setattr(lab, "_official_history", lambda r, refresh: hist)
    lab._protocol_report(2021, False)
    out = capsys.readouterr().out
    for style in ("sicher", "breit", "turnier", "angriff", "jackpot"):
        assert f"## Stil `{style}`" in out
    assert "# Simulation Planspiel 2021/22" in out and "| Kauf | Firma " in out and "Momentum Rang" in out and "**Ergebnis je Wertpapier**" in out and "## Vergleich der Stile" in out
    with pytest.raises(SystemExit, match="1999"):
        lab._protocol_report(1999, False)
