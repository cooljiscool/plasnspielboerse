"""Baut data/universe.json.

  python -m bot.universe_tool build          # DAX/MDAX/TecDAX/SDAX aus Wikipedia + Symbolsuche (yfinance)
  python -m bot.universe_tool import x.csv   # eigene Liste: Spalten isin,name[,stars][,yf]

Die automatische Zuordnung Name -> Börsensymbol ist eine Heuristik: das Ergebnis vor dem Einsatz prüfen und mit der
Instrumentenliste der Plattform abgleichen. Sterne (Nachhaltigkeit) müssen aus der Plattform übernommen werden."""
import csv
import io
import json
import os
import sys
import urllib.request

from . import config

INDEX_PAGES = {"DAX": "https://de.wikipedia.org/wiki/DAX", "MDAX": "https://de.wikipedia.org/wiki/MDAX",
               "TecDAX": "https://de.wikipedia.org/wiki/TecDAX", "SDAX": "https://de.wikipedia.org/wiki/SDAX"}


def names_from_wikipedia(url: str) -> list:
    import pandas as pd

    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    html = urllib.request.urlopen(req).read().decode()
    for t in pd.read_html(io.StringIO(html)):
        cols = [str(c) for c in t.columns]
        if "Name" in cols and 25 <= len(t) <= 100 and any("Branche" in c for c in cols):
            return [str(n).strip() for n in t["Name"] if str(n).strip() and str(n) != "nan"]
    return []


def resolve(name: str):
    import yfinance as yf

    for q in yf.Search(name, max_results=8).quotes:
        sym = q.get("symbol", "")
        if q.get("quoteType") == "EQUITY" and sym.endswith(".DE"):
            return sym
    return None


def build():
    out, seen = [], set()
    for idx, url in INDEX_PAGES.items():
        for name in names_from_wikipedia(url):
            sym = resolve(name)
            if sym and sym not in seen:
                seen.add(sym)
                out.append({"isin": sym, "name": name, "yf": sym, "stars": 0, "index": idx})
                print(f"{idx:7} {name:35} -> {sym}")
            elif not sym:
                print(f"{idx:7} {name:35} -> KEIN SYMBOL (manuell ergänzen)")
    return out


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in ("build", "import"):
        raise SystemExit(__doc__)
    if sys.argv[1] == "build":
        rows = build()
    else:
        rows = [{"isin": r["isin"], "name": r["name"], "yf": r.get("yf") or None, "stars": int(r.get("stars") or 0)}
                for r in csv.DictReader(open(sys.argv[2], encoding="utf-8"))]
    os.makedirs(config.DATA_DIR, exist_ok=True)
    json.dump(rows, open(os.path.join(config.DATA_DIR, "universe.json"), "w"), indent=2, ensure_ascii=False)
    print(f"{len(rows)} Wertpapiere gespeichert.")


if __name__ == "__main__":
    main()
