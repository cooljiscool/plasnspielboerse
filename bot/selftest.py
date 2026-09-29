"""Lesender Selbsttest ohne Order:  python -m bot.selftest
Prüft Universum, Marktdaten, Claude-Zugang und (bei PSB_USER/PSB_PASSWORD) Login + Depotauslesung."""
import json
import os
import sys

from . import config, market
from .run import load


def check(name, fn):
    try:
        print(f"[ OK ] {name}: {fn()}")
        return True
    except Exception as e:  # noqa: BLE001
        print(f"[FAIL] {name}: {e}")
        return False


def main():
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

    if os.environ.get("PSB_USER"):
        from .executor import PlaywrightExecutor

        def plattform():
            with PlaywrightExecutor() as ex:
                pf = ex.get_portfolio()
                return json.dumps({"cash": pf["cash"], "positionen": len(pf["positions"])})
        ok.append(check("Plattform-Login + Depot lesen", plattform))
    else:
        print("[ -- ] Plattform: PSB_USER/PSB_PASSWORD nicht gesetzt, übersprungen")
    sys.exit(0 if all(ok) else 1)


if __name__ == "__main__":
    main()
