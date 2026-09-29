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
