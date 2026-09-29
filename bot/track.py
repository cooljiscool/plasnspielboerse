"""Prognose-Bilanz: Was wurde vorhergesagt, was ist danach passiert?

Claudes Szenario-Prognosen (bot/research.py: Erwartung über 3 Monate je Titel) sind nirgends historisch prüfbar. Damit man trotzdem wenigstens im Nachhinein erfährt, ob sie
taugen, speichert der Bot jede Prognose (einmal je Titel und Tag) und trägt später ein, wie sich der Kurs nach 14, 28 und 56 Tagen entwickelt hat. `python -m bot.track` zeigt
die Trefferquote der Richtung und die Rangkorrelation. Ab 30 ausgewerteten Prognosen bekommt Claude diese Bilanz in den Kontext und soll seine Prognosen danach gewichten:
liegt die Rangkorrelation bei null oder darunter, taugen sie nichts und dürfen keine Entscheidung tragen."""
import json
import os
from datetime import date, datetime

import pandas as pd

from . import config

HORIZONS = (14, 28, 56)   # Kalendertage
TOLERANCE = 7             # so viele Tage nach dem Zeitpunkt darf der Kurs noch als Ergebnis eingetragen werden
MIN_N = 30                # so viele Prognosen mit Ergebnis braucht die Bilanz, bevor sie Claude gezeigt wird


def _path() -> str:
    return os.path.join(config.DATA_DIR, "forecasts.json")


def load() -> list:
    try:
        return json.load(open(_path()))
    except (OSError, json.JSONDecodeError):
        return []


def save(rows: list) -> None:
    os.makedirs(config.DATA_DIR, exist_ok=True)
    json.dump(rows, open(_path(), "w"), ensure_ascii=False)


def add(rows: list, notes: dict, prices: dict, today: date) -> int:
    """Neue Prognosen anhängen (einmal je Titel und Tag). Gibt die Zahl der neuen Zeilen zurück."""
    have = {(r["datum"], r["isin"]) for r in rows}
    n = 0
    for isin, note in (notes or {}).items():
        exp = note.get("erwartung_3m_prozent")
        if exp is None or isin not in prices or (today.isoformat(), isin) in have:
            continue
        rows.append({"datum": today.isoformat(), "isin": isin, "preis": prices[isin], "erwartung": exp,
                     "sentiment": note.get("sentiment"), "ergebnis": {}})
        n += 1
    return n


def update(rows: list, prices: dict, today: date) -> int:
    """Kursentwicklung seit der Prognose eintragen, sobald ein Zeitpunkt (14/28/56 Tage) erreicht ist. Gibt die Zahl neuer Ergebnisse zurück."""
    n = 0
    for r in rows:
        age = (today - datetime.fromisoformat(r["datum"]).date()).days
        for h in HORIZONS:
            if str(h) not in r["ergebnis"] and h <= age <= h + TOLERANCE and r["isin"] in prices and r["preis"]:
                r["ergebnis"][str(h)] = round(prices[r["isin"]] / r["preis"] - 1, 4)
                n += 1
    return n


def _rank_corr(a, b) -> float:
    ra, rb = pd.Series(a).rank(), pd.Series(b).rank()
    return float(ra.corr(rb)) if ra.nunique() > 1 and rb.nunique() > 1 else 0.0


def summary(rows: list, horizon: int = 28) -> dict:
    """Bilanz für einen Zeitraum: Zahl der Prognosen mit Ergebnis, Trefferquote der Richtung, Rangkorrelation und mittleres Ergebnis nach Erwartung."""
    pairs = [(r["erwartung"], r["ergebnis"][str(horizon)]) for r in rows if str(horizon) in r["ergebnis"] and r["erwartung"] is not None]
    if not pairs:
        return {"n": 0, "hinweis": "noch keine ausgewerteten Prognosen"}
    exp, res = zip(*pairs)
    out = {"n": len(pairs), "horizont_tage": horizon}
    if len(pairs) < MIN_N:
        out["hinweis"] = f"erst {len(pairs)} ausgewertete Prognosen, für eine Bilanz braucht es {MIN_N}"
        return out
    signed = [(e, x) for e, x in pairs if e != 0]
    out["trefferquote_richtung"] = round(sum((e > 0) == (x > 0) for e, x in signed) / len(signed), 2) if signed else None
    out["rangkorrelation"] = round(_rank_corr(exp, res), 3)
    med = sorted(exp)[len(exp) // 2]
    hi = [x for e, x in pairs if e >= med]
    lo = [x for e, x in pairs if e < med]
    if hi and lo:
        out["ergebnis_obere_haelfte"] = round(sum(hi) / len(hi), 4)
        out["ergebnis_untere_haelfte"] = round(sum(lo) / len(lo), 4)
    return out


def main():
    rows = load()
    print(f"{len(rows)} gespeicherte Prognosen")
    for h in HORIZONS:
        s = summary(rows, h)
        print(f"  nach {h:2} Tagen: {json.dumps(s, ensure_ascii=False)}")


if __name__ == "__main__":
    main()
