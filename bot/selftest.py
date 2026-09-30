"""Lesender Selbsttest ohne Order:  python -m bot.selftest
Prüft Universum, Marktdaten, Claude-Zugang und (bei PSB_USER/PSB_PASSWORD) Login + Depotauslesung.
Die optionalen Zusatzdaten (Analysten, Reddit, SEC, Quiver, MCP) werden mitgeprüft; ihr Ausfall zeigt [WARN] und lässt den Test nicht scheitern, der Bot handelt auch ohne sie."""
import json
import os
import re
import sys

from . import config, market
from .run import load


def check(name, fn, optional=False):
    try:
        print(f"[ OK ] {name}: {fn()}")
        return True
    except Exception as e:  # noqa: BLE001
        print(f"[{'WARN' if optional else 'FAIL'}] {name}: {e}")
        return optional


def official_check(universe: dict) -> str:
    """Stammt data/universe.json aus der amtlichen Planspiel-Liste (Felder markt und currency, echte ISIN)? Sonst Hinweis, wie man sie lädt."""
    rows = list(universe.values())
    if not rows or not all(u.get("markt") and u.get("currency") for u in rows):
        raise RuntimeError("Das Universum ist nicht die amtliche Planspiel-Liste (Tab Steuerung: „Wertpapierliste des Planspiels laden“ oder python -m bot.universe_tool official)")
    isin = sum(bool(re.fullmatch(r"[A-Z]{2}[A-Z0-9]{9}[0-9]", u["isin"])) for u in rows)
    return f"{isin} von {len(rows)} mit echter ISIN, {sum(bool(u.get('stars')) for u in rows)} mit Nachhaltigkeits-Kennzeichen, Kurse in Euro umgerechnet ({', '.join(sorted({u['currency'] for u in rows}))})"


def extras(check):
    """Optionale Zusatzdaten: jeweils ein Probeabruf mit einem bekannten US-Titel."""
    from datetime import date

    from . import analysts, edgar, mcp, quiver, social

    def analysten():
        out = analysts._fetch("AAPL")
        if not out:
            raise RuntimeError("Yahoo lieferte keine Schätzungsdaten")
        return f"Yahoo liefert {len(out)} Kennzahlen (AAPL)"
    check("Zusatzdaten Analysten", analysten, optional=True)

    def reddit():
        rows = social._fetch_ape(max_pages=1)
        if not rows:
            raise RuntimeError("keine Reddit-Erwähnungen erhalten")
        return f"ApeWisdom liefert {len(rows)} Titel"
    check("Zusatzdaten Reddit", reddit, optional=True)

    if edgar.contact_ok():
        def sec():
            ciks = edgar.cik_map()
            n = len(edgar.summarize(edgar.recent_form4(ciks["AAPL"], date.today(), days=30, max_filings=3)) or {})
            return f"SEC erreichbar, {len(ciks)} Unternehmen, AAPL-Probe {'mit' if n else 'ohne'} Insider-Käufe oder -Verkäufe"
        check("Zusatzdaten SEC-Insider", sec, optional=True)
    else:
        print("[ -- ] SEC-Insiderdaten: SEC_USER_AGENT (Name und E-Mail) nicht gesetzt, übersprungen")

    if config.QUIVER_TOKEN:
        def quiver_probe():
            rows = quiver._default_fetch(quiver.PATHS["kongress"].format("AAPL"), config.QUIVER_TOKEN)
            if rows is None:
                raise RuntimeError("Datensatz gehört nicht zum gebuchten Tarif")
            return f"Quiver antwortet ({len(rows)} Zeilen Kongress-Handel zu AAPL)"
        check("Zusatzdaten Quiver", quiver_probe, optional=True)
    else:
        print("[ -- ] Quiver: QUIVER_API_TOKEN nicht gesetzt, übersprungen")

    if config.MCP_CONFIG or config.MCP_TOOLS:
        def mcp_check():
            _, tools = mcp.setup(config.MCP_CONFIG, config.MCP_TOOLS)
            return f"Nur-Lese-Werkzeuge freigegeben: {', '.join(tools)}"
        check("Zusatzdaten MCP (nur lesen)", mcp_check, optional=True)


def testorder(isin: str = "DE000BASF111", shares: int = 1) -> int:
    """Geführte Testorder, ausschließlich im Test-/Trainingsdepot: ein Stück kaufen, im Depot nachsehen, wieder verkaufen. Prüft damit die Schritte für Kauf und Verkauf
    auf der echten Plattform und zeigt, was sie nach dem Ordern meldet. Das Wettbewerbsdepot wird nie angefasst (config.DEPOT wird hier fest auf "test" gesetzt)."""
    from datetime import date

    from .executor import PlaywrightExecutor

    config.DEPOT = "test"
    universe = {u["isin"]: u for u in load("universe.json", [])}
    if isin not in universe:
        print(f"[FAIL] {isin} steht nicht in data/universe.json (erst Wertpapierliste laden)")
        return 1
    u = universe[isin]
    base = {"isin": isin, "name": u["name"], "search": u.get("search") or u["name"], "shares": shares, "indices": u.get("indices") or []}

    def shown(ex):
        """Sichtbarer Text der Bestätigung bzw. Maske nach dem Ordern (kurz), damit man sieht, was die Plattform meldet."""
        try:
            return " | ".join(t.replace("\n", " ") for t in ex.page.locator("mat-dialog-container, .mat-mdc-snack-bar-container, app-order").all_inner_texts())[:700]
        except Exception:  # noqa: BLE001
            return ""

    try:
        with PlaywrightExecutor() as ex:
            print(f"[ OK ] Anmeldung und Testdepot gewählt (Browser: {config.BROWSER})")
            before = ex.get_portfolio()
            print(f"[ OK ] Depot gelesen: {before['cash']:.2f} € frei, {len(before['positions'])} Positionen")
            msg = ex.place({**base, "action": "buy"}, date.today())
            print(f"[ OK ] Kauf von {shares} x {u['name']} abgeschickt. Rückmeldung der Plattform: {msg or '(leer)'}")
            print(f"       Seite danach: {shown(ex)}")
            after = ex.get_portfolio(before)
            gained = after["positions"].get(isin, {}).get("shares", 0) - before["positions"].get(isin, {}).get("shares", 0)
            if gained < shares:
                print(f"[WARN] Die Position erscheint noch nicht im Depot (Börse geschlossen oder Order noch offen?). Später erneut versuchen, der Verkauf wird nicht geprüft. Barbestand jetzt {after['cash']:.2f} €")
                return 0
            print(f"[ OK ] Position im Depot: {after['positions'][isin]['shares']} Stück zu {after['positions'][isin]['avg_price']:.2f} €")
            msg = ex.place({**base, "action": "sell"}, date.today())
            print(f"[ OK ] Verkauf abgeschickt. Rückmeldung der Plattform: {msg or '(leer)'}")
            print(f"       Seite danach: {shown(ex)}")
            end = ex.get_portfolio(after)
            left = end["positions"].get(isin, {}).get("shares", 0)
            print(f"[{' OK ' if left == before['positions'].get(isin, {}).get('shares', 0) else 'WARN'}] Nach dem Verkauf {left} Stück im Depot, Barbestand {end['cash']:.2f} €")
    except Exception as e:  # noqa: BLE001
        print(f"[FAIL] {e}")
        print(f"       Bild und Seitenquelltext der Fehlerstelle liegen in {os.path.join(config.LOG_DIR, 'debug')}")
        return 1
    return 0


def main():
    if "--testorder" in sys.argv:
        for k in ("PSB_USER", "PSB_PASSWORD"):
            if not os.environ.get(k):
                print(f"[FAIL] {k} ist nicht gesetzt (Dashboard, Tab Einstellungen)")
                sys.exit(1)
        rest = [a for a in sys.argv[1:] if not a.startswith("--")]
        sys.exit(testorder(*rest[:1]))
    universe = {u["isin"]: u for u in load("universe.json", [])}
    def uni():
        if not universe:
            raise RuntimeError("data/universe.json ist leer")
        return f"{len(universe)} Wertpapiere"

    def kurse():
        n = len(market.load(universe)[0])
        if n == 0:
            raise RuntimeError("keine Kursdaten geladen (Symbole prüfen)")
        return f"{n}/{len(universe)} mit Kurs"

    ok = [check("Universum", uni), check("Marktdaten", kurse)]
    check("Amtliche Wertpapierliste", lambda: official_check(universe), optional=True)

    def entscheider():
        from . import brain
        provider = brain.resolve_provider()
        if provider == "rules":
            return "Regelstrategie ohne KI (kostenlos). Für KI: CLAUDE_CODE_OAUTH_TOKEN oder ANTHROPIC_API_KEY setzen"
        if provider == "claude_cli":
            out = brain._decide_cli({"aufgabe": "Selbsttest: gib eine leere Orderliste zurück", "kandidaten": {}})
            return f"claude_cli (Abo) antwortet, {len(out['orders'])} Orders"
        out = brain._decide_api({"aufgabe": "Selbsttest: gib eine leere Orderliste zurück", "kandidaten": {}})
        return f"api antwortet, {len(out['orders'])} Orders"
    ok.append(check("Entscheidungsquelle", entscheider))

    if config.KRONOS:
        def kronos():
            from . import kronos_signal
            good, why = kronos_signal.available()
            if not good:
                raise RuntimeError(why)
            syms = [u["yf"] for u in list(universe.values())[:3] if u.get("yf")]
            frames = market.download_ohlcv(syms, "2y")
            out = kronos_signal.KronosSignal().forecast(frames)
            if not out:
                raise RuntimeError("keine Prognose (zu wenig Historie?)")
            return f"{config.KRONOS_SIZE} liefert Prognosen: " + ", ".join(f"{k} {v:+.1%}" for k, v in out.items())
        ok.append(check("Kronos", kronos))

    extras(check)

    if os.environ.get("PSB_USER"):
        from .executor import PlaywrightExecutor

        def plattform():
            with PlaywrightExecutor() as ex:
                pf = ex.get_portfolio()
                return json.dumps({"depot": "Wettbewerbsdepot" if config.DEPOT == "echt" else "Testdepot", "browser": config.BROWSER, "cash": pf["cash"], "positionen": len(pf["positions"])})
        ok.append(check("Plattform-Login + Depot lesen", plattform))
    else:
        print("[ -- ] Plattform: PSB_USER/PSB_PASSWORD nicht gesetzt, übersprungen")
    sys.exit(0 if all(ok) else 1)


if __name__ == "__main__":
    main()
