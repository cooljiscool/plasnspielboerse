"""Ein Handelslauf: Daten -> Claude -> Risikoprüfung -> Ausführung -> Log.  python -m bot.run"""
import json
import os
from datetime import date, datetime

from . import brain, config, market, risk
from .executor import DryRunExecutor, PlaywrightExecutor


def load(name, default):
    path = os.path.join(config.DATA_DIR, name)
    return json.load(open(path)) if os.path.exists(path) else default


def save(name, obj):
    os.makedirs(config.DATA_DIR, exist_ok=True)
    json.dump(obj, open(os.path.join(config.DATA_DIR, name), "w"), indent=2, ensure_ascii=False)


def main():
    today = date.today()
    if not (config.GAME_START <= today <= config.GAME_END):
        print("Außerhalb des Spielzeitraums.")
        return
    universe = {u["isin"]: u for u in load("universe.json", [])}
    if not universe:
        raise SystemExit("data/universe.json ist leer – Wertpapierliste der Plattform eintragen.")
    pf = load("portfolio.json", {"cash": 50000.0, "positions": {}, "buy_orders_executed": 0})

    snap = market.snapshot(universe)
    executor = PlaywrightExecutor() if config.LIVE else DryRunExecutor(pf)
    ctx = executor if config.LIVE else None
    if ctx:
        ctx.__enter__()
    try:
        pf = executor.get_portfolio()
        prices = {i: s["price"] for i, s in snap.items()}
        total = risk.portfolio_value(pf, prices)
        focus = list(pf["positions"]) + sorted(snap, key=lambda i: snap[i]["ret_20d"], reverse=True)[:10]
        news = market.headlines(universe, list(dict.fromkeys(focus)))
        proposal = brain.decide(pf, universe, snap, news, today, total)
        approved, rejected = risk.validate(proposal["orders"], pf, prices, universe, today)
        for o in approved:
            executor.place(o, today)
    finally:
        if ctx:
            ctx.__exit__(None, None, None)

    if not config.LIVE:
        save("portfolio.json", executor.pf)
    os.makedirs(config.LOG_DIR, exist_ok=True)
    log = {"time": datetime.now().isoformat(timespec="seconds"), "live": config.LIVE, "total_before": total,
           "market_view": proposal["market_view"], "approved": approved,
           "rejected": [{"order": o, "why": w} for o, w in rejected]}
    json.dump(log, open(os.path.join(config.LOG_DIR, datetime.now().strftime("%Y%m%d-%H%M") + ".json"), "w"),
              indent=2, ensure_ascii=False)
    print(json.dumps(log, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
