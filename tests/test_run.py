import json

import pytest

from bot import config, run
from bot.executor import parse_de_number


@pytest.mark.parametrize("text,expected", [("1.234,56 €", 1234.56), ("50.000,00", 50000.0),
                                            ("-12,5 %", -12.5), ("Stück: 95", 95.0)])
def test_parse_de_number(text, expected):
    assert parse_de_number(text) == expected


def test_full_dry_run(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setattr(config, "LOG_DIR", str(tmp_path / "logs"))
    monkeypatch.setattr(config, "LIVE", False)
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "universe.json").write_text(json.dumps(
        [{"isin": "A", "name": "Alpha", "yf": "A.DE", "stars": 1}, {"isin": "B", "name": "Beta", "yf": "B.DE"}]))
    snap = {i: {"price": 100.0, "ret_5d": 0.01, "ret_20d": 0.05, "ret_60d": 0.1, "vol_20d": 0.2} for i in "AB"}
    monkeypatch.setattr(run.market, "load", lambda u: (snap, {"label": "risk_on", "score": "5/5", "exposure": 0.97, "positions": 6}))
    monkeypatch.setattr(run.fundamentals, "get", lambda *a, **k: {})
    monkeypatch.setattr(run.market, "headlines", lambda u, i: {})
    monkeypatch.setattr(run.brain, "decide", lambda *a, **k: {
        "market_view": "test", "orders": [{"action": "buy", "isin": "A", "amount_eur": 9000, "reason": "x"}]})
    monkeypatch.setattr(run, "date", type("D", (), {"today": staticmethod(lambda: config.GAME_START)}))
    run.main()
    pf = json.loads((tmp_path / "data" / "portfolio.json").read_text())
    assert pf["positions"]["A"]["shares"] == 90 and pf["buy_orders_executed"] == 1
    assert pf["cash"] == pytest.approx(50000 - 9000 - config.fee(9000))
    assert list((tmp_path / "logs").glob("*.json"))


# --- Zusatzdaten und Prognose-Bilanz im Handelslauf ---
def prepare(tmp_path, monkeypatch, provider="claude_cli"):
    monkeypatch.setattr(config, "DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setattr(config, "LOG_DIR", str(tmp_path / "logs"))
    monkeypatch.setattr(config, "LIVE", False)
    monkeypatch.setattr(config, "RESEARCH", True)
    (tmp_path / "data").mkdir(exist_ok=True)
    (tmp_path / "data" / "universe.json").write_text(json.dumps(
        [{"isin": "A", "name": "Alpha", "yf": "AAA"}, {"isin": "B", "name": "Beta", "yf": "B.DE"}]))
    snap = {i: {"price": 100.0, "ret_5d": 0.01, "ret_20d": 0.05, "ret_60d": 0.1, "vol_20d": 0.2} for i in "AB"}
    monkeypatch.setattr(run.market, "load", lambda u: (snap, {"label": "risk_on", "score": "5/5", "exposure": 0.97, "positions": 6}))
    monkeypatch.setattr(run.fundamentals, "get", lambda *a, **k: {})
    monkeypatch.setattr(run.market, "headlines", lambda u, i: {})
    monkeypatch.setattr(run.journal, "recent", lambda *a, **k: [])
    monkeypatch.setattr(run.brain, "resolve_provider", lambda: provider)
    monkeypatch.setattr(run.brain, "shadow_picks", lambda *a, **k: (_ for _ in ()).throw(AssertionError("kein echter Claude-Aufruf im Test")))
    monkeypatch.setattr(run, "date", type("D", (), {"today": staticmethod(lambda: config.GAME_START)}))
    return snap


def capture_decide(monkeypatch):
    seen = {}

    def fake(pf, universe, snap, news, today, total, regime=None, research=None, history=None, macro=None, track_record=None, freedom=""):
        seen.update(snap=snap, research=research, macro=macro, track_record=track_record, freedom=freedom)
        return {"market_view": "test", "orders": [], "provider": "claude_cli", "verbrauch": {"kosten_usd": 0.02}}
    monkeypatch.setattr(run.brain, "decide", fake)
    return seen


def fake_sources(monkeypatch, quiver=False):
    monkeypatch.setattr(run.research, "get", lambda u, i, t: {"market": "m", "macro": "", "verbrauch": {"aufrufe": 5, "kosten_usd": 0.4}, "notes": {
        "A": {"sentiment": 1, "summary": "s", "erwartung_3m_prozent": 6.5, "risiko_einschaetzung": "mittel"}}})
    monkeypatch.setattr(run.macro, "snapshot", lambda: {"warnsignale": ["Zinskurve invers (10 Jahre unter 2 Jahren)"]})
    monkeypatch.setattr(run.statements, "get", lambda *a, **k: {"A": {"bilanz": {"schwer": False}}})
    monkeypatch.setattr(run.social, "get", lambda u, i: {"A": {"bullish_anteil": 0.8}})
    monkeypatch.setattr(run.social, "reddit", lambda u, i: {"A": {"rang": 4, "auffaellig": True}})
    monkeypatch.setattr(run.edgar, "contact_ok", lambda: True)
    monkeypatch.setattr(run.edgar, "get", lambda u, i, t: {"A": {"cluster_kauf": True, "kaeufe": 3}})
    monkeypatch.setattr(run.analysts, "get", lambda u, i, t: {"A": {"schaetzungen_gesenkt": True}})
    monkeypatch.setattr(config, "QUIVER_TOKEN", "tok" if quiver else "")
    monkeypatch.setattr(run.quiver, "get", lambda u, i, t: ({"A": {"kongress": {"kaeufe_90d": 2}}}, None))


def test_run_hands_all_extra_data_to_claude_and_logs_it(tmp_path, monkeypatch):
    prepare(tmp_path, monkeypatch)
    fake_sources(monkeypatch, quiver=True)
    seen = capture_decide(monkeypatch)
    run.main()
    a = seen["snap"]["A"]
    assert a["social"] == {"stocktwits": {"bullish_anteil": 0.8}, "reddit": {"rang": 4, "auffaellig": True}}
    assert a["insider_sec"]["cluster_kauf"] and a["analysten"]["schaetzungen_gesenkt"] and a["quiver"]["kongress"]["kaeufe_90d"] == 2 and a["bilanz"] == {"schwer": False}
    assert "insider_sec" not in seen["snap"]["B"] and seen["macro"]["warnsignale"]
    log = json.loads(next((tmp_path / "logs").glob("*.json")).read_text())
    assert log["daten"]["insider_sec"] == 1 and log["daten"]["analysten"] == 1 and log["daten"]["reddit"] == 1 and log["daten"]["stocktwits"] == 1
    assert log["daten"]["quiver"] == {"titel": 1} and log["daten"]["prognosen"] == {"neu": 1, "ausgewertet": 0, "gespeichert": 1}
    assert log["verbrauch"] == {"recherche": {"aufrufe": 5, "kosten_usd": 0.4}, "entscheidung": {"kosten_usd": 0.02}, "schattendepot": None}


def test_run_stores_forecast_and_shows_record_only_with_enough_evaluated_forecasts(tmp_path, monkeypatch):
    prepare(tmp_path, monkeypatch)
    fake_sources(monkeypatch)
    seen = capture_decide(monkeypatch)
    run.main()
    rows = json.loads((tmp_path / "data" / "forecasts.json").read_text())
    assert rows == [{"datum": "2026-10-01", "isin": "A", "preis": 100.0, "erwartung": 6.5, "sentiment": 1, "ergebnis": {}}]
    assert seen["track_record"] is None                                           # zu wenig ausgewertete Prognosen: keine Bilanz im Kontext
    old = [{"datum": "2026-09-01", "isin": "A", "preis": 100.0, "erwartung": float(k), "sentiment": 0, "ergebnis": {"28": k / 100}} for k in range(-15, 20)]
    (tmp_path / "data" / "forecasts.json").write_text(json.dumps(old))
    run.main()
    rec = seen["track_record"]["nach_28_tagen"]
    assert rec["n"] == 35 and rec["rangkorrelation"] == pytest.approx(1.0)
    log = json.loads(sorted((tmp_path / "logs").glob("*.json"))[-1].read_text())
    assert log["daten"]["prognosen"]["gespeichert"] == 36


def test_run_evaluates_old_forecasts_against_todays_prices(tmp_path, monkeypatch):
    prepare(tmp_path, monkeypatch)
    fake_sources(monkeypatch)
    capture_decide(monkeypatch)
    (tmp_path / "data" / "forecasts.json").write_text(json.dumps(
        [{"datum": "2026-09-03", "isin": "A", "preis": 80.0, "erwartung": 5.0, "sentiment": 0, "ergebnis": {}}]))    # 28 Tage vor dem 1.10.
    run.main()
    rows = json.loads((tmp_path / "data" / "forecasts.json").read_text())
    old = next(r for r in rows if r["datum"] == "2026-09-03")
    assert old["ergebnis"] == {"28": 0.25}                                        # 100 / 80 - 1


def test_run_survives_every_failing_extra_source(tmp_path, monkeypatch):
    prepare(tmp_path, monkeypatch)
    fake_sources(monkeypatch, quiver=True)

    def boom(*a, **k):
        raise RuntimeError("Quelle down")
    for mod, name in ((run.social, "get"), (run.social, "reddit"), (run.edgar, "get"), (run.analysts, "get"), (run.quiver, "get"), (run.track, "load")):
        monkeypatch.setattr(mod, name, boom)
    seen = capture_decide(monkeypatch)
    run.main()
    assert "insider_sec" not in seen["snap"]["A"] and "analysten" not in seen["snap"]["A"] and "social" not in seen["snap"]["A"]
    assert list((tmp_path / "logs").glob("*.json"))


def test_run_skips_sec_without_contact_details_and_extra_data_without_ai(tmp_path, monkeypatch):
    prepare(tmp_path, monkeypatch)
    fake_sources(monkeypatch)
    monkeypatch.setattr(run.edgar, "contact_ok", lambda: False)
    monkeypatch.setattr(run.edgar, "get", lambda *a, **k: pytest.fail("ohne Kontaktdaten darf nichts abgerufen werden"))
    seen = capture_decide(monkeypatch)
    run.main()
    log = json.loads(next((tmp_path / "logs").glob("*.json")).read_text())
    assert "SEC_USER_AGENT" in log["daten"]["insider_sec"] and "insider_sec" not in seen["snap"]["A"]
    # Regelstrategie ohne KI: keine Zusatzdaten, keine Abrufe
    prepare(tmp_path, monkeypatch, provider="rules")
    for mod, name in ((run.social, "get"), (run.social, "reddit"), (run.analysts, "get"), (run.macro, "snapshot"), (run.statements, "get")):
        monkeypatch.setattr(mod, name, lambda *a, **k: pytest.fail("die Regelstrategie braucht keine Zusatzdaten"))
    run.main()
