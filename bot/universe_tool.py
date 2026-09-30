"""Baut data/universe.json.

  python -m bot.universe_tool official [x.pdf|x.txt|URL]   # EMPFOHLEN: die amtliche Wertpapierliste des Planspiels (ohne Angabe: die aktuelle von planspiel-boerse.de)
  python -m bot.universe_tool tested         # das getestete Universum (bot/universes.py: DAX, MDAX, Europa, USA) mit Namen und ISINs
  python -m bot.universe_tool sectors        # Branche (Yahoo) für alle Titel in data/universe.json eintragen; die Begrenzung "höchstens 2 je Branche" wirkt nur bei bekannter Branche
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


_LEGAL = {"aktiengesellschaft", "ag", "se", "sa", "nv", "plc", "inc", "corporation", "corp", "company", "co", "kgaa", "kg", "gmbh",
          "&", "and", "holding", "holdings", "group", "ltd", "spa", "asa", "oyj", "ab", "limited", "the"}


def search_term(name: str) -> str:
    """Suchbegriff für die Plattform: Name ohne Rechtsform, höchstens die ersten zwei Wörter
    ("Siemens Aktiengesellschaft" -> "Siemens", "Eckert & Ziegler SE" -> "Eckert Ziegler")."""
    words = [w for w in name.replace(",", " ").split() if w.lower().strip(".") .replace(".", "") not in _LEGAL]
    return " ".join(words[:2]) or name


def _lookup(sym: str) -> dict:
    """Name und ISIN eines Yahoo-Symbols (best effort; fehlt etwas, bleibt das Symbol als Platzhalter)."""
    import yfinance as yf

    t, name, isin = yf.Ticker(sym), None, None
    try:
        info = t.info or {}
        name = info.get("longName") or info.get("shortName")
    except Exception:  # noqa: BLE001
        pass
    try:
        isin = t.isin
    except Exception:  # noqa: BLE001
        pass
    return {"name": name, "isin": isin if isin and isin != "-" else None}


def build_tested(workers: int = 8, lookup=None, alive=None) -> list:
    """Das Universum, an dem die Strategie getestet wurde (bot/universes.py). Titel ohne aktuelle Kurse (delistet) entfallen."""
    from concurrent.futures import ThreadPoolExecutor

    from . import universes

    group_of = {s: g for g, lst in universes.GROUPS.items() for s in lst}
    syms = list(dict.fromkeys(universes.ALL))
    if alive is None:
        import yfinance as yf
        recent = yf.download(syms, period="1mo", interval="1d", progress=False, group_by="ticker", threads=True, auto_adjust=True)
        alive = {s for s in syms if s in recent.columns.get_level_values(0) and recent[s]["Close"].notna().any()}
    syms = [s for s in syms if s in alive]
    with ThreadPoolExecutor(workers) as ex:
        info = list(ex.map(lookup or _lookup, syms))
    return [{"isin": i["isin"] or s, "name": i["name"] or s, "search": search_term(i["name"] or s), "yf": s, "stars": 0,
             "markt": group_of[s]} for s, i in zip(syms, info)]


def build_official(source: str = None):
    """Amtliche Liste (URL, PDF- oder Textdatei; ohne Angabe die aktuelle von planspiel-boerse.de) einlesen und zu Yahoo-Symbolen zuordnen: (Zeilen, Bericht)."""
    from . import official

    path = source
    if not path or path.startswith("http"):
        path = official.download_pdf(os.path.join(config.DATA_DIR, "cache", "wertpapierliste.pdf"), path)
    return official.build(official.pdf_text(path))


def _yahoo_sector(sym: str):
    import yfinance as yf

    for _ in range(2):
        try:
            sec = (yf.Ticker(sym).info or {}).get("sector")
            if sec:
                return sec
        except Exception:  # noqa: BLE001 – Yahoo antwortet gelegentlich mit 404 oder leer
            pass
    return None


def add_sectors(rows: list, lookup=None, workers: int = 8) -> tuple:
    """Trägt bei jedem Titel die Branche ein (Feld `sector`), damit die Branchenbegrenzung schon beim ersten Lauf für alle Titel gilt und nicht nur für die, deren
    Fundamentaldaten Yahoo am Tag liefert. Ein vorhandener Eintrag bleibt, wenn Yahoo nichts liefert. Gibt (Zeilen, Titel ohne Branche) zurück."""
    from concurrent.futures import ThreadPoolExecutor

    lookup = lookup or _yahoo_sector
    todo = [r for r in rows if r.get("yf")]
    with ThreadPoolExecutor(workers) as ex:
        found = list(ex.map(lambda r: lookup(r["yf"]), todo))
    for r, sec in zip(todo, found):
        if sec:
            r["sector"] = sec
    return rows, [r["name"] for r in rows if not r.get("sector")]


def report_text(rep: dict) -> str:
    """Bericht der amtlichen Liste in Worten."""
    lines = [f"Amtliche Liste: {rep['aus_liste']} Aktien, davon {rep['universum']} mit Kürzel und aktuellen Kursen im Universum.",
             "Verteilung: " + ", ".join(f"{g} {n}" for g, n in rep["je_gruppe"].items()) + f"; {rep['mit_stern']} mit Nachhaltigkeits-Kennzeichen; Währungen: "
             + ", ".join(f"{c} {n}" for c, n in rep["waehrungen"].items()) + " (alle Kurse werden in Euro umgerechnet)."]
    if rep["ohne_kuerzel"]:
        lines.append(f"Kein Börsenkürzel gefunden ({len(rep['ohne_kuerzel'])}, werden nicht gehandelt): " + "; ".join(rep["ohne_kuerzel"]))
    if rep["ohne_kurse"]:
        lines.append(f"Ohne aktuelle oder genug Kurse ({len(rep['ohne_kurse'])}, werden nicht gehandelt): " + "; ".join(rep["ohne_kurse"]))
    return "\n".join(lines)


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in ("build", "import", "tested", "official", "sectors"):
        raise SystemExit(__doc__)
    if sys.argv[1] == "official":
        rows, rep = build_official(sys.argv[2] if len(sys.argv) > 2 else None)
        print(report_text(rep))
        if len(rows) < 100:
            raise SystemExit(f"Nur {len(rows)} Wertpapiere zugeordnet: Das sieht nach einem Fehler aus, data/universe.json bleibt unverändert.")
        old = os.path.join(config.DATA_DIR, "universe.json")
        if os.path.exists(old):
            os.replace(old, os.path.join(config.DATA_DIR, "universe_vorher.json"))   # eine Sicherung der bisherigen Liste
    elif sys.argv[1] == "sectors":
        rows = json.load(open(os.path.join(config.DATA_DIR, "universe.json")))
    elif sys.argv[1] == "tested":
        rows = build_tested()
    elif sys.argv[1] == "build":
        rows = build()
    else:
        rows = [{"isin": r["isin"], "name": r["name"], "yf": r.get("yf") or None, "stars": int(r.get("stars") or 0)}
                for r in csv.DictReader(open(sys.argv[2], encoding="utf-8"))]
    if sys.argv[1] in ("official", "sectors"):
        rows, missing = add_sectors(rows)
        print(f"Branche bekannt bei {len(rows) - len(missing)} von {len(rows)} Titeln." + (f" Ohne Branche (Begrenzung je Branche wirkt dort nicht): {'; '.join(missing[:40])}" + (" ..." if len(missing) > 40 else "") if missing else ""))
    os.makedirs(config.DATA_DIR, exist_ok=True)
    json.dump(rows, open(os.path.join(config.DATA_DIR, "universe.json"), "w"), indent=2, ensure_ascii=False)
    print(f"{len(rows)} Wertpapiere gespeichert.")


if __name__ == "__main__":
    main()
