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
