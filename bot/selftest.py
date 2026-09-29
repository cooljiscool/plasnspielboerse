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
    ok = [check("Universum", lambda: f"{len(universe)} Wertpapiere")]
    ok.append(check("Marktdaten", lambda: f"{len(market.snapshot(universe))}/{len(universe)} mit Kurs"))

    def claude():
        import anthropic
        r = anthropic.Anthropic().messages.create(model=config.MODEL, max_tokens=10,
                                                  messages=[{"role": "user", "content": "ok?"}])
        return r.model
    ok.append(check("Claude-API", claude))

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
