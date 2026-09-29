import json
import os
import stat
from datetime import date

import pytest

from bot import brain, config, journal, rules

UNI = {f"S{i:02d}": {"name": f"Titel {i}", "stars": 0} for i in range(40)}


def snap(**over):
    base = {i: {"price": 100.0, "ret_5d": 0.0, "ret_20d": 0.02, "ret_60d": 0.01 * k, "vol_20d": 0.25}
            for k, i in enumerate(UNI)}   # S39 = stärkstes Momentum
    base.update(over)
    return base


def pf(positions=None):
    return {"cash": 50000.0, "positions": positions or {}, "buy_orders_executed": 0}


def baseline(s=None):
    return rules.decide(pf(), UNI, s or snap(), 50000.0)


def buy(isin, why="x"):
    return {"action": "buy", "isin": isin, "amount_eur": 8000, "reason": why}


def test_guard_drops_buy_outside_top_25():
    s = snap()
    out = {"orders": [buy("S00"), buy("S39")]}   # S00 ist Rang 40 von 40
    kept, notes = brain.guard(baseline(s), out, s, UNI)
    assert "S00" not in {o["isin"] for o in kept}
    assert any(n["isin"] == "S00" and "verworfen" in n["aktion"] for n in notes)


def test_guard_restores_buy_vetoed_without_evidence():
    s = snap()
    base = baseline(s)
    veto = base["orders"][0]["isin"]
    out = {"orders": [o for o in base["orders"] if o["isin"] != veto]}   # Claude streicht einen Kauf ohne Grund
    kept, notes = brain.guard(base, out, s, UNI)
    assert veto in {o["isin"] for o in kept}
    assert any(n["aktion"] == "Kauf wiederhergestellt" for n in notes)


def test_guard_accepts_documented_veto():
    s = snap()
    base = baseline(s)
    veto = base["orders"][0]["isin"]
    out = {"orders": [o for o in base["orders"] if o["isin"] != veto]}
    research = {"notes": {veto: {"sentiment": -2, "summary": "Gewinnwarnung"}}}
    kept, notes = brain.guard(base, out, s, UNI, research)
    assert veto not in {o["isin"] for o in kept}
    assert any(n["aktion"] == "Veto akzeptiert" for n in notes)


def test_guard_accepts_earnings_veto_from_data():
    s = snap()
    base = baseline(s)
    veto = base["orders"][0]["isin"]
    s[veto]["days_to_earnings"] = 2
    out = {"orders": [o for o in base["orders"] if o["isin"] != veto]}
    kept, _ = brain.guard(base, out, s, UNI)
    assert veto not in {o["isin"] for o in kept}


def test_guard_accepts_replacement_within_top_25():
    s = snap()
    base = baseline(s)
    veto = base["orders"][0]["isin"]
    replacement = "S33"   # Rang 7 von 40, nicht im Vorschlag
    assert replacement not in {o["isin"] for o in base["orders"]}
    out = {"orders": [o for o in base["orders"] if o["isin"] != veto] + [buy(replacement, "Ersatz")]}
    kept, notes = brain.guard(base, out, s, UNI)
    isins = {o["isin"] for o in kept}
    assert replacement in isins and veto not in isins and len(isins) == len(base["orders"])


def test_guard_blocks_sell_without_negative_evidence():
    s = snap()
    held = {"S39": {"shares": 50, "avg_price": 90.0, "bought": "2026-10-01"}}
    base = rules.decide(pf(held), UNI, s, 50000.0)
    assert not [o for o in base["orders"] if o["action"] == "sell"]
    out = {"orders": [{"action": "sell", "isin": "S39", "reason": "Markt wirkt teuer"}]}
    kept, notes = brain.guard(base, out, s, UNI)
    assert not [o for o in kept if o["action"] == "sell"] and notes[0]["aktion"] == "Verkauf verworfen"
    kept, _ = brain.guard(base, out, s, UNI, {"notes": {"S39": {"sentiment": -2}}})
    assert [o for o in kept if o["action"] == "sell"]


def test_decide_applies_guard_end_to_end(tmp_path, monkeypatch):
    s = snap()
    veto = baseline(s)["orders"][0]["isin"]
    orders = [o for o in baseline(s)["orders"] if o["isin"] != veto]
    payload = json.dumps({"is_error": False, "structured_output": {"market_view": "Vorsicht", "orders": orders}})
    exe = tmp_path / "claude"
    exe.write_text(f"#!/bin/sh\ncat >/dev/null\necho '{payload}'\n")
    exe.chmod(exe.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", f"{tmp_path}:{os.environ['PATH']}")
    monkeypatch.setattr(config, "PROVIDER", "claude_cli")
    out = brain.decide(pf(), UNI, s, {}, date(2026, 10, 5), 50000.0)
    assert out["provider"] == "claude_cli" and veto in {o["isin"] for o in out["orders"]}
    assert any(n["aktion"] == "Kauf wiederhergestellt" for n in out["guard"])


def test_journal_reports_outcome_since_order(tmp_path):
    log = {"time": "2026-10-05T09:25:00", "provider": "claude_cli", "approved": [
        {"action": "buy", "isin": "A", "name": "Alpha", "est_price": 100.0},
        {"action": "sell", "isin": "B", "name": "Beta", "est_price": 50.0}]}
    (tmp_path / "20261005-0925.json").write_text(json.dumps(log))
    rows = journal.recent(str(tmp_path), {"A": {"price": 110.0}, "B": {"price": 60.0}})
    a = next(r for r in rows if r["titel"] == "Alpha")
    b = next(r for r in rows if r["titel"] == "Beta")
    assert a["aktion"] == "Kauf" and a["rendite_seither"] == pytest.approx(0.10)
    assert b["aktion"] == "Verkauf" and b["kurs_seit_verkauf"] == pytest.approx(0.20)   # nach dem Verkauf gestiegen
    assert journal.recent(str(tmp_path / "leer"), {}) == []


def test_context_contains_history_and_bear_case_schema():
    ctx = brain.build_context(pf(), UNI, snap(), {}, date(2026, 10, 5), 50000.0, None, None, None, [{"aktion": "Kauf"}])
    assert ctx["verlauf"] == [{"aktion": "Kauf"}]
    item = brain.TOOL["input_schema"]["properties"]["orders"]["items"]["properties"]
    assert "bear_case" in item


# --- Zusatzdaten: Makro, Bilanz, Insider, Social Media ---
def test_severe_balance_sheet_warning_counts_as_negative_evidence():
    s = snap()
    base = baseline(s)
    veto = base["orders"][0]["isin"]
    out = {"orders": [o for o in base["orders"] if o["isin"] != veto]}
    s[veto]["bilanz"] = {"schwer": True, "warnungen": ["Zinsdeckung nur 0.8"]}
    kept, notes = brain.guard(base, out, s, UNI)
    assert veto not in {o["isin"] for o in kept} and any(n["aktion"] == "Veto akzeptiert" for n in notes)


def test_mild_balance_sheet_warning_social_and_insider_are_no_veto_reason():
    s = snap()
    base = baseline(s)
    veto = base["orders"][0]["isin"]
    out = {"orders": [o for o in base["orders"] if o["isin"] != veto]}
    s[veto]["bilanz"] = {"schwer": False, "warnungen": ["Liquidität knapp"]}
    s[veto]["insider"] = {"kaeufe": 0, "verkaeufe": 9, "signal": "Netto-Verkäufe der Führungskräfte (oft planmäßig, schwaches Signal)"}
    research = {"notes": {veto: {"sentiment": 0, "social": -2, "social_summary": "Forum schimpft", "insider_web": "Verkauf 1 Mio."}}}
    kept, notes = brain.guard(base, out, s, UNI, research)
    assert veto in {o["isin"] for o in kept} and any(n["aktion"] == "Kauf wiederhergestellt" for n in notes)


def test_context_carries_macro_bilanz_and_web_macro():
    s = snap()
    s["S39"]["bilanz"] = {"schwer": False, "piotroski": "7/9"}
    ctx = brain.build_context(pf(), UNI, s, {}, date(2026, 10, 5), 50000.0, None,
                              {"market": "ruhig", "macro": "EZB pausiert", "notes": {}}, None, None,
                              {"kurve_10y_2y": 0.3, "warnsignale": []})
    assert ctx["makro"]["kurve_10y_2y"] == 0.3 and ctx["makro_web"] == "EZB pausiert"
    assert ctx["kandidaten"]["S39"]["bilanz"]["piotroski"] == "7/9"
    assert "makro" not in brain.build_context(pf(), UNI, s, {}, date(2026, 10, 5), 50000.0)


def test_prompt_tells_claude_not_to_trade_on_macro_or_social():
    assert "NICHT wegen Makrodaten in Cash" in brain.SYSTEM and "Weder Kaufgrund noch Veto-Grund" in brain.SYSTEM
    assert "bilanz.schwer" in brain.SYSTEM


def test_research_schema_has_social_insider_and_macro_fields(tmp_path, monkeypatch):
    from bot import research
    item = research.SCHEMA["properties"]["notes"]["items"]["properties"]
    assert {"social", "social_summary", "insider_web", "next_event"} <= set(item)
    assert "macro_view" in research.SCHEMA["properties"]
    monkeypatch.setattr(config, "DATA_DIR", str(tmp_path / "data"))
    payload = json.dumps({"is_error": False, "structured_output": {"market": "m", "macro_view": "Zinsen stabil", "notes": [
        {"isin": "S01", "sentiment": 0, "summary": "s", "social": -1, "insider_web": "Kauf CEO 2 Mio."}]}})
    exe = tmp_path / "claude"
    exe.write_text(f"#!/bin/sh\ncat >/dev/null\necho '{payload}'\n")
    exe.chmod(exe.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", f"{tmp_path}:{os.environ['PATH']}")
    out = research.get(UNI, ["S01"], date(2026, 10, 5))
    assert out["macro"] == "Zinsen stabil" and out["notes"]["S01"]["insider_web"].startswith("Kauf CEO")
    again = research.get(UNI, ["S01"], date(2026, 10, 5))
    assert again["cached"] is True and again["macro"] == "Zinsen stabil"


# --- Szenarien, Risikomatrix, Analysten, Prognose-Bilanz ---
def scenario(p_bull, r_bull, p_base, r_base, p_bear, r_bear):
    return {"bull": {"wahrscheinlichkeit_prozent": p_bull, "rendite_prozent": r_bull}, "base": {"wahrscheinlichkeit_prozent": p_base, "rendite_prozent": r_base},
            "bear": {"wahrscheinlichkeit_prozent": p_bear, "rendite_prozent": r_bear}}


def test_derive_weights_scenarios_by_probability():
    from bot import research
    note = research.derive({"szenarien": scenario(25, 30, 50, 8, 25, -20)})
    assert note["erwartung_3m_prozent"] == pytest.approx(6.5)               # 0,25*30 + 0,5*8 + 0,25*(-20)
    assert research.derive({"szenarien": scenario(30, 20, 60, 5, 15, -10)})["erwartung_3m_prozent"] == pytest.approx((6 + 3 - 1.5) / 1.05, abs=0.1)   # Summe 105: normiert


def test_derive_ignores_unusable_scenarios():
    from bot import research
    for sc in (scenario(60, 30, 60, 8, 60, -20),                                   # Summe 180
               scenario(10, 30, 10, 8, 10, -20),                                   # Summe 30
               scenario(40, 30, 40, 8, 20, float("nan")),                          # keine Zahl
               scenario(40, 500, 40, 8, 20, -20),                                  # unglaubwürdige Rendite
               scenario(-10, 30, 60, 8, 50, -20),                                  # negative Wahrscheinlichkeit
               {"bull": {"wahrscheinlichkeit_prozent": 50}}, "text", None, 7):
        assert "erwartung_3m_prozent" not in research.derive({"szenarien": sc})
    assert "erwartung_3m_prozent" not in research.derive({"sentiment": 1})


def test_derive_risk_level_from_largest_probability_times_impact():
    from bot import research
    risk = lambda *pairs: {"risikomatrix": [{"risiko": "x", "wahrscheinlichkeit": w, "auswirkung": a} for w, a in pairs]}   # noqa: E731
    assert research.derive(risk((2, 2), (1, 5)))["risiko_einschaetzung"] == "niedrig"       # größtes Produkt 5
    assert research.derive(risk((2, 4), (1, 1)))["risiko_einschaetzung"] == "mittel"        # 8
    assert research.derive(risk((3, 5)))["risiko_einschaetzung"] == "hoch"                  # 15
    assert research.derive(risk((5, 5), (1, 1)))["risiko_einschaetzung"] == "hoch"
    for bad in ([], [{"risiko": "x"}], [{"risiko": "x", "wahrscheinlichkeit": 9, "auswirkung": 3}], "kaputt", None):
        assert "risiko_einschaetzung" not in research.derive({"risikomatrix": bad})


def test_research_get_derives_and_caches_scenario_numbers(tmp_path, monkeypatch):
    from bot import research
    monkeypatch.setattr(config, "DATA_DIR", str(tmp_path / "data"))
    note = {"isin": "S01", "sentiment": 1, "summary": "s", "szenarien": scenario(30, 25, 50, 6, 20, -18),
            "risikomatrix": [{"risiko": "Zölle", "wahrscheinlichkeit": 4, "auswirkung": 4}]}
    payload = json.dumps({"is_error": False, "structured_output": {"market": "m", "notes": [note]}})
    exe = tmp_path / "claude"
    exe.write_text(f"#!/bin/sh\ncat >/dev/null\necho '{payload}'\n")
    exe.chmod(exe.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", f"{tmp_path}:{os.environ['PATH']}")
    out = research.get(UNI, ["S01"], date(2026, 10, 5))
    assert out["notes"]["S01"]["erwartung_3m_prozent"] == pytest.approx(6.9) and out["notes"]["S01"]["risiko_einschaetzung"] == "hoch"
    assert research.get(UNI, ["S01"], date(2026, 10, 5))["notes"]["S01"]["erwartung_3m_prozent"] == pytest.approx(6.9)    # kommt aus dem Zwischenspeicher


def test_research_schema_and_prompt_ask_for_scenarios_and_risk_matrix():
    from bot import research
    item = research.SCHEMA["properties"]["notes"]["items"]["properties"]
    assert {"szenarien", "risikomatrix"} <= set(item) and set(item["szenarien"]["properties"]) == {"bull", "base", "bear"}
    assert set(item["risikomatrix"]["items"]["required"]) == {"risiko", "wahrscheinlichkeit", "auswirkung"}
    assert "Szenario" in research.SYSTEM and "Risikomatrix" not in research.SYSTEM and "Wahrscheinlichkeit (1-5)" in research.SYSTEM
    assert "Schätzungen, keine Fakten" in research.SYSTEM


def test_cut_analyst_estimates_count_as_negative_evidence_but_raised_ones_do_not():
    s = snap()
    base = baseline(s)
    veto = base["orders"][0]["isin"]
    out = {"orders": [o for o in base["orders"] if o["isin"] != veto]}
    s[veto]["analysten"] = {"schaetzungen_gesenkt": True, "eps_jahr_aenderung_30d": -0.08}
    kept, notes = brain.guard(base, out, s, UNI)
    assert veto not in {o["isin"] for o in kept} and any(n["aktion"] == "Veto akzeptiert" for n in notes)
    s[veto]["analysten"] = {"schaetzungen_angehoben": True, "herabstufungen_ueberwiegen": True, "kauf_anteil": 0.2}      # nur Information
    kept, notes = brain.guard(base, out, s, UNI)
    assert veto in {o["isin"] for o in kept} and any(n["aktion"] == "Kauf wiederhergestellt" for n in notes)


def test_claudes_own_scenarios_and_risk_rating_never_justify_a_veto():
    s = snap()
    base = baseline(s)
    veto = base["orders"][0]["isin"]
    out = {"orders": [o for o in base["orders"] if o["isin"] != veto]}
    research = {"notes": {veto: {"sentiment": 0, "erwartung_3m_prozent": -25.0, "risiko_einschaetzung": "hoch",
                                 "szenarien": scenario(10, 5, 30, -10, 60, -40)}}}
    s[veto]["risiko"] = {"vola_jahr": 0.9, "max_rueckgang_1j": -0.6, "var95_10_tage": -0.2, "risikostufe": 5}
    s[veto]["insider_sec"] = {"verkaeufe_ungeplant": 12, "kaeufe": 0}
    s[veto]["social"] = {"stocktwits": {"bullish_anteil": 0.1}, "reddit": {"auffaellig": True}}
    kept, notes = brain.guard(base, out, s, UNI, research)
    assert veto in {o["isin"] for o in kept} and any(n["aktion"] == "Kauf wiederhergestellt" for n in notes)


def test_context_carries_all_new_candidate_data_and_forecast_record():
    s = snap()
    s["S39"].update(insider_sec={"cluster_kauf": True}, analysten={"schaetzungen_angehoben": True}, quiver={"kongress": {"kaeufe_90d": 3}},
                    social={"stocktwits": {"bullish_anteil": 0.8}, "reddit": {"rang": 4}}, risiko={"risikostufe": 3})
    rec = {"nach_28_tagen": {"n": 40, "rangkorrelation": 0.11}}
    ctx = brain.build_context(pf(), UNI, s, {}, date(2026, 10, 5), 50000.0, None, {"market": "m", "notes": {"S39": {"erwartung_3m_prozent": 4.0}}},
                              None, None, None, rec)
    cand = ctx["kandidaten"]["S39"]
    assert cand["insider_sec"]["cluster_kauf"] and cand["analysten"]["schaetzungen_angehoben"] and cand["quiver"]["kongress"]["kaeufe_90d"] == 3
    assert cand["social"]["reddit"]["rang"] == 4 and cand["risiko"]["risikostufe"] == 3 and cand["recherche"]["erwartung_3m_prozent"] == 4.0
    assert ctx["prognose_bilanz"] == rec
    assert "prognose_bilanz" not in brain.build_context(pf(), UNI, s, {}, date(2026, 10, 5), 50000.0)


def test_prompt_explains_new_data_and_limits_forecast_use():
    for key in ("insider_sec", "analysten", "schaetzungen_gesenkt", "quiver", "risiko", "prognose_bilanz", "social.reddit", "erwartung_3m_prozent"):
        assert key in brain.SYSTEM
    assert "Nie als Veto-Grund" in brain.SYSTEM and "Rangkorrelation bei 0 oder darunter" in brain.SYSTEM
    assert "next_event, bilanz.schwer" not in brain.SYSTEM     # Prompt und Kontrolle nennen dieselben Belege
    assert "analysten.schaetzungen_gesenkt) rechtfertigt" in brain.SYSTEM


def test_decide_passes_forecast_record_to_claude(monkeypatch):
    captured = {}
    monkeypatch.setattr(config, "PROVIDER", "claude_cli")
    monkeypatch.setattr(brain, "_decide_cli", lambda ctx: captured.update(ctx) or {"market_view": "", "orders": []})
    brain.decide(pf(), UNI, snap(), {}, date(2026, 10, 5), 50000.0, None, None, None, None, {"nach_28_tagen": {"n": 31}})
    assert captured["prognose_bilanz"] == {"nach_28_tagen": {"n": 31}}
