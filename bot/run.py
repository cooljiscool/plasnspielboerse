"""Ein Handelslauf: Daten -> Claude -> Risikoprüfung -> Ausführung -> Log.  python -m bot.run"""
import json
import os
from datetime import date, datetime

from . import analysts, brain, config, edgar, fundamentals, journal, kronos_signal, macro, market, quiver, research, risk, rules, social, statements, track
from .executor import DryRunExecutor, PlaywrightExecutor


def load(name, default):
    path = os.path.join(config.DATA_DIR, name)
    return json.load(open(path)) if os.path.exists(path) else default


def save(name, obj):
    os.makedirs(config.DATA_DIR, exist_ok=True)
    json.dump(obj, open(os.path.join(config.DATA_DIR, name), "w"), indent=2, ensure_ascii=False)


def optional(name, fn, default=None):
    """Zusatzdaten holen. Ein Fehler wird gemeldet, stoppt den Lauf aber nie (die Regelstrategie braucht sie nicht)."""
    try:
        return fn()
    except Exception as e:  # noqa: BLE001
        print(f"{name} nicht verfügbar: {e}")
        return default


def main():
    today = date.today()
    if not (config.GAME_START <= today <= config.GAME_END):
        print("Außerhalb des Spielzeitraums.")
        return
    universe = {u["isin"]: u for u in load("universe.json", [])}
    if not universe:
        raise SystemExit("data/universe.json ist leer – Wertpapierliste der Plattform eintragen.")
    pf = load("portfolio.json", {"cash": 50000.0, "positions": {}, "buy_orders_executed": 0})

    snap, regime = market.load(universe)
    prev_pf = pf
    executor = PlaywrightExecutor() if config.LIVE else DryRunExecutor(pf)
    ctx = executor if config.LIVE else None
    if ctx:
        ctx.__enter__()
    research_info = None
    kronos_info = None
    macro_info = None
    data_info = {}
    track_record = None
    try:
        # Live: Depot von der Plattform lesen. Schlägt das fehl, wird nichts gehandelt (Exception bricht ab).
        pf = executor.get_portfolio(pf) if config.LIVE else executor.get_portfolio()
        prices = {i: s["price"] for i, s in snap.items()}
        for isin, pos in pf["positions"].items():   # Höchstkurs seit Kauf für den Trailing-Stop
            before = prev_pf["positions"].get(isin, {}).get("peak")
            pos["peak"] = max(pos.get("peak") or before or pos["avg_price"], prices.get(isin, pos["avg_price"]))
        total = risk.portfolio_value(pf, prices)

        # Engere Auswahl: Depottitel plus die stärksten nach Regelscore bekommen Fundamentaldaten und Recherche.
        top = sorted(snap, key=lambda i: rules.active_score()(snap[i], universe[i].get("stars", 0)), reverse=True)
        shortlist = [i for i in dict.fromkeys([*pf["positions"], *top[:config.SHORTLIST]]) if i in snap]
        try:
            for isin, f in fundamentals.get(universe, snap, shortlist, today).items():
                snap[isin].update({k: v for k, v in f.items() if k != "sector"})
                if f.get("sector"):
                    snap[isin]["sector"] = universe[isin]["sector"] = f["sector"]
        except Exception as e:  # noqa: BLE001 – Fundamentaldaten sind Zusatz, kein Muss
            print("Fundamentaldaten nicht verfügbar:", e)
        kronos_info = None
        if config.KRONOS:   # optional: Prognose des Basismodells Kronos für die engere Auswahl
            try:
                ks = kronos_signal.get(universe, shortlist, today)
                for isin, v in ks.items():
                    snap[isin]["kronos_ret"] = v
                kronos_info = {"titel": len(ks), "modell": config.KRONOS_SIZE, "horizont": config.KRONOS_HORIZON}
            except Exception as e:  # noqa: BLE001 – Zusatzsignal, darf den Lauf nicht stoppen
                kronos_info = {"fehler": str(e)[:200]}
        provider = brain.resolve_provider()
        news = market.headlines(universe, shortlist[:12]) if provider != "rules" else {}
        if provider == "claude_cli" and config.RESEARCH:
            research_info = research.get(universe, shortlist, today)
            for isin, note in research_info["notes"].items():
                if isin in snap and note.get("event_soon"):
                    snap[isin]["event_soon"] = True
        history = journal.recent(config.LOG_DIR, snap) if provider != "rules" else None

        # Prognose-Bilanz: Claudes Szenario-Prognosen speichern und frühere gegen den tatsächlichen Kurs auswerten (bot/track.py)
        def track_forecasts():
            rows = track.load()
            evaluated = track.update(rows, prices, today)
            added = track.add(rows, (research_info or {}).get("notes"), prices, today)
            track.save(rows)
            summaries = {f"nach_{h}_tagen": track.summary(rows, h) for h in track.HORIZONS}
            return {"neu": added, "ausgewertet": evaluated, "gespeichert": len(rows)}, {k: v for k, v in summaries.items() if v["n"] >= track.MIN_N}
        tracked = optional("Prognose-Bilanz", track_forecasts)
        if tracked:
            data_info["prognosen"], track_record = tracked[0], tracked[1] or None

        macro_info = None
        if provider != "rules":   # Zusatzdaten für Claude: Zins- und Konjunkturlage, Bilanzqualität, Insider, Analysten, Stimmung (die Regeln nutzen sie nicht)
            macro_info = macro.snapshot()
            try:
                sectors = {i: snap[i]["sector"] for i in shortlist if snap[i].get("sector")}
                for isin, extra in statements.get(universe, shortlist, today, sectors).items():
                    for key in ("bilanz", "insider"):
                        if extra.get(key):
                            snap[isin][key] = extra[key]
            except Exception as e:  # noqa: BLE001 – Zusatzdaten
                print("Bilanzdaten nicht verfügbar:", e)
            stocktwits = optional("StockTwits", lambda: social.get(universe, shortlist), {})   # Privatanleger-Stimmung, nur US-Titel
            reddit = optional("Reddit-Erwähnungen", lambda: social.reddit(universe, shortlist), {})
            for isin in {*stocktwits, *reddit}:
                snap[isin]["social"] = {k: v for k, v in (("stocktwits", stocktwits.get(isin)), ("reddit", reddit.get(isin))) if v}
            data_info.update(stocktwits=len(stocktwits), reddit=len(reddit))
            if edgar.contact_ok():
                sec = optional("SEC-Insiderdaten", lambda: edgar.get(universe, shortlist, today), {})
                for isin, v in sec.items():
                    snap[isin]["insider_sec"] = v
                data_info["insider_sec"] = len(sec)
            else:
                data_info["insider_sec"] = "aus: SEC_USER_AGENT (Name und E-Mail) fehlt"
            est = optional("Analystenschätzungen", lambda: analysts.get(universe, shortlist, today), {})
            for isin, v in est.items():
                snap[isin]["analysten"] = v
            data_info["analysten"] = len(est)
            if config.QUIVER_TOKEN:   # optional, kostenpflichtig
                qv, qerr = optional("Quiver", lambda: quiver.get(universe, shortlist, today), ({}, "Abruf gescheitert"))
                for isin, v in qv.items():
                    snap[isin]["quiver"] = v
                data_info["quiver"] = {"titel": len(qv), **({"fehler": qerr} if qerr else {})}
        proposal = brain.decide(pf, universe, snap, news, today, total, regime, research_info, history, macro_info, track_record)
        approved, rejected = risk.validate(proposal["orders"], pf, prices, universe, today)
        for o in approved:
            o["name"] = universe[o["isin"]]["name"]
            o["search"] = universe[o["isin"]].get("search") or o["name"]
            executor.place(o, today)
        if config.LIVE and approved:
            # Kontrolle: Depot nach den Orders neu lesen.
            pf = executor.get_portfolio(pf)
            pf["buy_orders_executed"] += sum(o["action"] == "buy" for o in approved)
    finally:
        if ctx:
            ctx.__exit__(None, None, None)

    save("portfolio.json", pf)
    total_after = risk.portfolio_value(pf, prices)
    holdings = {i: {"name": universe.get(i, {}).get("name", i), "shares": p["shares"], "avg_price": p["avg_price"],
                    "price": prices.get(i, p["avg_price"])} for i, p in pf["positions"].items()}
    os.makedirs(config.LOG_DIR, exist_ok=True)
    log = {"time": datetime.now().isoformat(timespec="seconds"), "live": config.LIVE, "total_before": total,
           "total_after": total_after, "cash": pf["cash"], "holdings": holdings,
           "market_view": proposal["market_view"], "provider": proposal.get("provider"),
           "fallback_reason": proposal.get("fallback_reason"), "guard": proposal.get("guard"), "kronos": kronos_info, "regime": regime,
           "makro": ({"warnsignale": macro_info.get("warnsignale", [])} if macro_info else None),
           "daten": data_info or None, "verbrauch": {"recherche": (research_info or {}).get("verbrauch"), "entscheidung": proposal.get("verbrauch")},
           "research": ({"error": research_info.get("error"), "warning": research_info.get("warning"), "cached": research_info.get("cached", False),
                         "market": research_info.get("market"), "notes": len(research_info["notes"])}
                        if research_info else None),
           "approved": approved,
           "rejected": [{"order": o, "why": w} for o, w in rejected]}
    json.dump(log, open(os.path.join(config.LOG_DIR, datetime.now().strftime("%Y%m%d-%H%M") + ".json"), "w"),
              indent=2, ensure_ascii=False)
    print(json.dumps(log, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
