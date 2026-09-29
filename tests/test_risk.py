from datetime import date

from bot import config, risk

UNI = {"A": {"name": "A"}, "B": {"name": "B"}}
TODAY = date(2026, 10, 10)


def pf(cash=50000.0, positions=None):
    return {"cash": cash, "positions": positions or {}, "buy_orders_executed": 0}


def test_buy_capped_at_position_limit():
    ok, rej = risk.validate([{"action": "buy", "isin": "A", "amount_eur": 40000}], pf(), {"A": 100.0}, UNI, TODAY)
    assert len(ok) == 1 and not rej
    assert ok[0]["shares"] * 100.0 <= config.POSITION_CAP * 50000


def test_small_order_rejected():
    ok, rej = risk.validate([{"action": "buy", "isin": "A", "amount_eur": 1000}], pf(), {"A": 10.0}, UNI, TODAY)
    assert not ok and rej


def test_penny_stock_rejected():
    ok, rej = risk.validate([{"action": "buy", "isin": "A", "amount_eur": 9000}], pf(), {"A": 0.5}, UNI, TODAY)
    assert not ok and "Penny" in rej[0][1]


def test_min_hold_blocks_sell():
    p = pf(positions={"A": {"shares": 100, "avg_price": 50.0, "bought": "2026-10-09"}})
    ok, rej = risk.validate([{"action": "sell", "isin": "A"}], p, {"A": 50.0}, UNI, TODAY)
    assert not ok and "haltedauer" in rej[0][1]


def test_stop_sell_allowed_early():
    p = pf(positions={"A": {"shares": 200, "avg_price": 50.0, "bought": "2026-10-09"}})
    ok, _ = risk.validate([{"action": "sell", "isin": "A", "stop": True}], p, {"A": 50.0}, UNI, TODAY)
    assert ok and ok[0]["shares"] == 200


def test_cash_never_negative():
    orders = [{"action": "buy", "isin": i, "amount_eur": 9500} for i in ("A", "B")]
    p = pf(cash=10000.0)
    ok, _ = risk.validate(orders, p, {"A": 10.0, "B": 10.0}, UNI, TODAY)
    spent = sum(o["shares"] * o["est_price"] + config.fee(o["shares"] * o["est_price"]) for o in ok)
    assert spent <= 10000.0
