"""Fundamentaldaten und Termine (yfinance) für die engere Auswahl, einmal pro Tag zwischengespeichert.

Bewertung, Wachstum und Analystenurteil sind hier nur Zusatzinformationen. Der Termin der nächsten Gewinnmeldung ist eine
harte Regel: kurz davor wird nicht gekauft, weil ein Bericht den Kurs in beide Richtungen springen lässt."""
import json
import os
from datetime import date, datetime

from . import config


def _fetch(sym: str) -> dict:
    import yfinance as yf

    t = yf.Ticker(sym)
    info = t.info or {}
    price, target = info.get("currentPrice") or info.get("regularMarketPrice"), info.get("targetMeanPrice")
    out = {"sector": info.get("sector"), "pe": info.get("trailingPE"), "fwd_pe": info.get("forwardPE"),
           "rev_growth": info.get("revenueGrowth"), "margin": info.get("profitMargins"),
           "analyst": info.get("recommendationMean"),
           "target_upside": target / price - 1 if target and price else None}   # Kursziel und Kurs in derselben (Yahoo-)Währung: unabhängig von der Euro-Umrechnung der Kurse
    try:
        for d in (t.calendar or {}).get("Earnings Date") or []:
            d = d if isinstance(d, date) else datetime.fromisoformat(str(d)).date()
            if d >= date.today():
                out["earnings"] = d.isoformat()
                break
    except Exception:  # noqa: BLE001 – Termine sind optional
        pass
    return {k: (round(v, 3) if isinstance(v, float) else v) for k, v in out.items() if v is not None}


def get(universe: dict, snap: dict, isins: list, today: date) -> dict:
    """Gibt {isin: Kennzahlen} zurück; holt nur, was heute noch nicht im Cache liegt."""
    path = os.path.join(config.DATA_DIR, "fundamentals.json")
    try:
        cache = json.load(open(path))
    except (OSError, json.JSONDecodeError):
        cache = {}
    if cache.get("date") != today.isoformat():
        cache = {"date": today.isoformat(), "items": {}}
    items = cache["items"]
    for isin in isins:
        if isin not in items and universe.get(isin, {}).get("yf"):
            try:
                items[isin] = _fetch(universe[isin]["yf"])
            except Exception:  # noqa: BLE001 – ein Titel ohne Daten darf den Lauf nicht stoppen
                items[isin] = {}
    os.makedirs(config.DATA_DIR, exist_ok=True)
    json.dump(cache, open(path, "w"), indent=1, ensure_ascii=False)

    out = {}
    for isin in isins:
        f = dict(items.get(isin, {}))
        if f.get("earnings"):
            f["days_to_earnings"] = (date.fromisoformat(f.pop("earnings")) - today).days
        f.pop("target", None)   # alter Zwischenspeicher: Kursziel in Heimatwährung, gegen den Euro-Kurs wertlos
        out[isin] = f
    return out
