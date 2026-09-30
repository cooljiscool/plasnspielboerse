import json
from datetime import date, timedelta

import pytest

from bot import brain, config, run, shadow
from tests.test_run import prepare

D0 = date(2026, 10, 1)


def prices_at(scale: dict) -> dict:
    return {f"T{i}": 100.0 * scale.get(f"T{i}", 1.0) for i in range(10)}


def test_add_records_one_group_per_day_and_needs_enough_titles():
    rows = []
    p = prices_at({})
    assert shadow.add(rows, D0, {"T0": "a", "T1": "b", "T2": "c"}, ["T3", "T4", "T5"], p)
    assert not shadow.add(rows, D0, {"T0": "a", "T1": "b", "T2": "c"}, ["T3", "T4", "T5"], p)      # nur einmal je Tag
    assert not shadow.add(rows, D0 + timedelta(1), {"T0": "a", "T1": "b"}, ["T3", "T4", "T5"], p)   # zu wenige Titel von Claude
    assert not shadow.add(rows, D0 + timedelta(1), {"T0": "a", "T1": "b", "T2": "c"}, ["T3"], p)   # zu wenige Titel der Regeln
    assert len(rows) == 1 and rows[0]["claude"] == {"T0": 100.0, "T1": 100.0, "T2": 100.0} and len(rows[0]["markt"]) == 10


def test_update_scores_each_group_after_14_days_only_once():
    rows = []
    shadow.add(rows, D0, {"T0": "a", "T1": "b", "T2": "c"}, ["T3", "T4", "T5"], prices_at({}))
    later = prices_at({"T0": 1.2, "T1": 1.2, "T2": 1.2, "T3": 1.0, "T4": 1.0, "T5": 1.0, "T6": 0.9})
    assert shadow.update(rows, later, D0 + timedelta(13)) == 0                                    # noch nicht 14 Tage
    assert shadow.update(rows, later, D0 + timedelta(14)) == 1
    assert shadow.update(rows, later, D0 + timedelta(15)) == 0                                    # nicht doppelt
    res = rows[0]["ergebnis"]["14"]
    assert res["claude"] == pytest.approx(0.2) and res["regeln"] == 0.0 and res["markt"] == pytest.approx((0.6 - 0.1 * 1) / 10, abs=1e-4)


def make_rows(n_days: int, claude: float, rules_: float, noise=0.0):
    rows = []
    for k in range(n_days):
        d = D0 + timedelta(k)
        r = {"datum": d.isoformat(), "ergebnis": {"14": {"claude": claude + (noise if k % 2 else -noise), "regeln": rules_, "markt": 0.0}}}
        rows.append(r)
    return rows


def test_verdict_waits_for_independent_windows_then_judges():
    early = shadow.summary(make_rows(20, 0.05, 0.0, 0.01))                                       # 20 Tage = 1,4 Zeitfenster
    assert early["fenster"] < shadow.MIN_WINDOWS and shadow.verdict(early)["urteil"] == "zu_frueh"
    assert shadow.verdict(shadow.summary([]))["urteil"] == "zu_frueh"
    better = shadow.summary(make_rows(60, 0.05, 0.0, 0.01))
    assert better["fenster"] > shadow.MIN_WINDOWS and shadow.verdict(better)["urteil"] == "claude_besser"
    worse = shadow.summary(make_rows(60, -0.05, 0.0, 0.01))
    assert shadow.verdict(worse)["urteil"] == "regeln_besser"
    flat = shadow.summary(make_rows(60, 0.001, 0.0, 0.05))
    assert shadow.verdict(flat)["urteil"] == "gleichauf"


def test_claude_must_also_beat_the_market_to_be_called_better():
    rows = make_rows(60, 0.05, 0.0, 0.01)
    for r in rows:
        r["ergebnis"]["14"]["markt"] = 0.10                                                       # Markt lief noch besser als Claude
    assert shadow.verdict(shadow.summary(rows))["urteil"] == "gleichauf"


def test_freedom_only_with_setting_auto_and_a_clear_verdict(monkeypatch):
    good = {"urteil": "claude_besser"}
    monkeypatch.setattr(config, "FREEDOM", "auto")
    assert shadow.freedom(good) and not shadow.freedom({"urteil": "gleichauf"}) and not shadow.freedom({"urteil": "zu_frueh"})
    monkeypatch.setattr(config, "FREEDOM", "aus")
    assert not shadow.freedom(good)


def test_shadow_picks_keep_only_valid_distinct_candidates_and_do_not_see_the_rule_proposal(monkeypatch):
    seen = {}
    uni = {f"T{i}": {"name": f"T{i}", "stars": 0} for i in range(12)}
    snap = {f"T{i}": {"price": 100.0, "ret_20d": 0.0, "ret_60d": 0.01 * i, "ret_120d": 0.01 * i, "vol_20d": 0.2} for i in range(12)}
    picks = [{"isin": f"T{i}", "reason": "g"} for i in (11, 10, 11, "X", 9, 8, 7, 6, 5)]           # doppelt und unbekannt

    def fake(task, schema, system, payload):
        seen.update(system=system, payload=payload)
        return {"picks": picks}, {"kosten_usd": 0.1}
    monkeypatch.setattr(brain, "_claude_json", fake)
    got, used = brain.shadow_picks({"cash": 50000.0, "positions": {"T0": {"shares": 1, "avg_price": 1.0}}}, uni, snap, {}, D0, 50000.0)
    assert list(got) == ["T11", "T10", "T9", "T8", "T7", "T6"] and used == {"kosten_usd": 0.1}    # höchstens 6, verschieden, nur Kandidaten
    assert not {"quant_vorschlag", "verlauf", "prognose_bilanz", "nachhaltigkeit_plaetze"} & set(seen["payload"]) and seen["payload"]["positionen"] == {}
    assert "Regel" in seen["system"] and "quant_vorschlag" not in seen["system"]


def test_freedom_widens_the_guard_and_tells_claude(monkeypatch):
    calls = {}
    monkeypatch.setattr(config, "PROVIDER", "claude_cli")
    monkeypatch.setattr(brain, "_decide_cli", lambda ctx: calls.update(ctx=ctx) or {"market_view": "", "orders": []})
    monkeypatch.setattr(brain, "guard", lambda *a, top_k=25, **k: calls.update(top_k=top_k) or ([], []))
    uni = {f"T{i}": {"name": f"T{i}", "stars": 0} for i in range(12)}
    snap = {f"T{i}": {"price": 100.0, "ret_20d": 0.0, "ret_60d": 0.01 * i, "vol_20d": 0.2} for i in range(12)}
    pf = {"cash": 50000.0, "positions": {}, "buy_orders_executed": 0}
    brain.decide(pf, uni, snap, {}, D0, 50000.0)
    assert calls["top_k"] == 25 and "freiheit" not in calls["ctx"]
    brain.decide(pf, uni, snap, {}, D0, 50000.0, freedom="Claude ist besser.")
    assert calls["top_k"] == config.LLM_CANDIDATES and "Claude ist besser." in calls["ctx"]["freiheit"]


def setup_run(tmp_path, monkeypatch):
    prepare(tmp_path, monkeypatch)
    for name in ("statements.get", "social.get", "social.reddit", "edgar.get", "analysts.get"):
        mod, fn = name.split(".")
        monkeypatch.setattr(getattr(run, mod), fn, lambda *a, **k: {})            # Zusatzdaten für andere Titel als die Testtitel entfallen
    monkeypatch.setattr(run.edgar, "contact_ok", lambda: False)
    monkeypatch.setattr(run.macro, "snapshot", lambda: {"warnsignale": []})
    uni = [{"isin": f"T{i}", "name": f"T{i}", "yf": f"T{i}.DE"} for i in range(8)]
    (tmp_path / "data" / "universe.json").write_text(json.dumps(uni))
    snap = {f"T{i}": {"price": 100.0, "ret_5d": 0.01, "ret_20d": 0.05, "ret_60d": 0.02 * i, "vol_20d": 0.2} for i in range(8)}
    monkeypatch.setattr(run.market, "load", lambda u: (snap, {"label": "risk_on", "score": "5/5", "exposure": 0.97, "positions": 6}))
    monkeypatch.setattr(run.research, "get", lambda u, i, t: {"market": "m", "macro": "", "notes": {}})
    monkeypatch.setattr(config, "FREEDOM", "auto")
    decided = {}

    def fake_decide(*a, **k):
        decided.update(k)
        return {"market_view": "t", "orders": [], "provider": "claude_cli"}
    monkeypatch.setattr(run.brain, "decide", fake_decide)
    return decided


def test_run_records_the_shadow_group_and_writes_the_report(tmp_path, monkeypatch):
    decided = setup_run(tmp_path, monkeypatch)
    monkeypatch.setattr(run.brain, "shadow_picks", lambda *a, **k: ({"T1": "x", "T2": "y", "T3": "z"}, {"kosten_usd": 0.12}))
    run.main()
    rows = json.loads((tmp_path / "data" / "shadow.json").read_text())
    assert len(rows) == 1 and set(rows[0]["claude"]) == {"T1", "T2", "T3"} and set(rows[0]["regeln"]) == {"T7", "T6", "T5", "T4", "T3", "T2"}
    rep = json.loads((tmp_path / "data" / "shadow_report.json").read_text())
    assert rep["urteil"] == "zu_frueh" and rep["gruppen"] == 1 and rep["freiheit"] is False
    log = json.loads(next((tmp_path / "logs").glob("*.json")).read_text())
    assert log["vergleich"]["urteil"] == "zu_frueh" and log["verbrauch"]["schattendepot"] == {"kosten_usd": 0.12}
    assert decided["freedom"] == ""                                                             # noch kein Urteil: Regeln bleiben Grundlage
    run.main()                                                                                  # zweiter Lauf am selben Tag: keine zweite Gruppe, kein zweiter Aufruf
    assert len(json.loads((tmp_path / "data" / "shadow.json").read_text())) == 1


def test_run_gives_claude_freedom_once_the_verdict_says_so(tmp_path, monkeypatch):
    decided = setup_run(tmp_path, monkeypatch)
    monkeypatch.setattr(run.brain, "shadow_picks", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("Limit")))
    monkeypatch.setattr(run.shadow, "load", lambda: [])
    monkeypatch.setattr(run.shadow, "report", lambda rows: {"urteil": "claude_besser", "text": "Claude schlägt die Regeln.", "gruppen": 40})
    run.main()
    assert decided["freedom"] == "Claude schlägt die Regeln."
    monkeypatch.setattr(config, "FREEDOM", "aus")
    run.main()
    assert decided["freedom"] == ""                                                             # Einstellung aus: nie


def test_run_survives_a_failing_shadow_call(tmp_path, monkeypatch):
    setup_run(tmp_path, monkeypatch)
    monkeypatch.setattr(run.brain, "shadow_picks", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("Limit erreicht")))
    run.main()
    assert list((tmp_path / "logs").glob("*.json")) and not (tmp_path / "data" / "shadow.json").exists() or json.loads((tmp_path / "data" / "shadow.json").read_text()) == []
