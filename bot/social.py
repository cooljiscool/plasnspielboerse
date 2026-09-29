"""Stimmung von Privatanlegern auf StockTwits (öffentliche Schnittstelle, ohne Schlüssel), nur für US-Symbole.

Die Schnittstelle liefert die letzten 30 Beiträge zu einem Symbol, viele davon vom Verfasser als „Bullish“ oder „Bearish“ markiert. Das ist eine Momentaufnahme
der letzten Stunden (bei sehr aktiven Titeln nur Minuten). Zählt man die Markierungen, ergibt sich ein grobes Stimmungsbild. Kein historischer Test möglich
(die Schnittstelle liefert keine Vergangenheit), und Privatanleger-Stimmung gilt als leicht manipulierbar und teils als Gegenindikator (Stichprobe von 6 großen US-Titeln: 73 bis 92 % Bullish, die Grundstimmung ist fast immer positiv): sie geht nur als
Information an Claude und ist weder Kaufgrund noch Veto-Grund. Reddit sperrt Zugriffe von Programmen (403) und wird nicht abgefragt.
Fremdtexte der Beiträge werden nicht weitergegeben, nur Zahlen."""
import json
import os
import re
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

from . import config

URL = "https://api.stocktwits.com/api/2/streams/symbol/{}.json"
APE_URL = "https://apewisdom.io/api/v1.0/filter/all-stocks/page/{}"   # frei nutzbar, wertet Reddit-Foren (u. a. wallstreetbets) aus; Daten: apewisdom.io
MAX_AGE = 3 * 3600   # Stimmung ist kurzlebig: nach 3 Stunden neu abfragen
MIN_TAGGED = 5       # unter so vielen markierten Beiträgen wird kein Anteil ausgewiesen


def us_symbol(yf_symbol: str) -> bool:
    """StockTwits kennt US-Symbole (AAPL, NVDA); Auslandsbörsen (SAP.DE, MC.PA) haben andere Kürzel und werden übersprungen."""
    return bool(re.fullmatch(r"[A-Z]{1,5}", yf_symbol or ""))


def summarize(payload: dict) -> dict:
    """Zahlen aus einer Antwort der Schnittstelle; {} wenn zu wenig Beiträge."""
    msgs = payload.get("messages") or []
    if not msgs:
        return {}
    tags = [((m.get("entities") or {}).get("sentiment") or {}).get("basic") for m in msgs]
    bull, bear = tags.count("Bullish"), tags.count("Bearish")
    out = {"beitraege": len(msgs), "bullish": bull, "bearish": bear,
           "beobachter": (payload.get("symbol") or {}).get("watchlist_count")}
    try:
        t0 = datetime.fromisoformat(msgs[-1]["created_at"].replace("Z", "+00:00"))
        t1 = datetime.fromisoformat(msgs[0]["created_at"].replace("Z", "+00:00"))
        out["zeitspanne_stunden"] = round((t1 - t0).total_seconds() / 3600, 1)
    except (KeyError, ValueError):
        pass
    if bull + bear >= MIN_TAGGED:
        share = bull / (bull + bear)
        out["bullish_anteil"] = round(share, 2)
        out["stimmung"] = ("überwiegend positiv" if share >= 0.7 else "überwiegend negativ" if share <= 0.3 else "gemischt")
    return out


def _fetch(sym: str) -> dict:
    req = urllib.request.Request(URL.format(sym), headers={"User-Agent": "planspiel-bot/1.0 (private research)"})
    return summarize(json.loads(urllib.request.urlopen(req, timeout=20).read().decode()))


def get(universe: dict, isins: list, fetch=None, workers: int = 3) -> dict:
    """{isin: Stimmung} für US-Titel der Auswahl. Fehler einzelner Titel werden übersprungen, nie ein Abbruch."""
    path = os.path.join(config.DATA_DIR, "social.json")
    try:
        cache = json.load(open(path))
    except (OSError, json.JSONDecodeError):
        cache = {}
    now = time.time()
    if now - cache.get("time", 0) > MAX_AGE:
        cache = {"time": now, "items": {}}
    todo = [i for i in isins if i not in cache["items"] and us_symbol(universe.get(i, {}).get("yf"))]
    if todo:
        fn = fetch or _fetch

        def one(isin):
            try:
                return fn(universe[isin]["yf"])
            except Exception:  # noqa: BLE001 – Zusatzsignal
                return {}
        with ThreadPoolExecutor(workers) as ex:
            for isin, res in zip(todo, ex.map(one, todo)):
                cache["items"][isin] = res
        os.makedirs(config.DATA_DIR, exist_ok=True)
        json.dump(cache, open(path, "w"))
    return {i: cache["items"][i] for i in isins if cache["items"].get(i)}


def ape_summary(rows: dict, symbol: str) -> dict:
    """Zahlen zu Reddit-Erwähnungen eines Symbols aus den Zeilen von ApeWisdom ({Ticker: Zeile}); {} wenn es nicht erwähnt wird."""
    r = rows.get(symbol)
    if not r:
        return {}
    now, before = r.get("mentions"), r.get("mentions_24h_ago")
    out = {"rang": r.get("rank"), "erwaehnungen_24h": now, "erwaehnungen_vor_24h": before, "rang_vor_24h": r.get("rank_24h_ago"), "upvotes": r.get("upvotes")}
    try:
        out["auffaellig"] = bool(int(r["rank"]) <= 20 or (int(now) >= 30 and int(before) > 0 and int(now) >= 2 * int(before)))
    except (KeyError, TypeError, ValueError):
        pass
    return out


def _fetch_ape(max_pages: int = 8, wanted: set = None) -> dict:
    rows = {}
    for page in range(1, max_pages + 1):
        req = urllib.request.Request(APE_URL.format(page), headers={"User-Agent": "planspiel-bot/1.0 (private research)"})
        data = json.loads(urllib.request.urlopen(req, timeout=20).read().decode())
        for r in data.get("results", []):
            rows[str(r.get("ticker", "")).upper()] = r
        if page >= int(data.get("pages", 1)) or (wanted and wanted <= set(rows)):
            break
    return rows


def reddit(universe: dict, isins: list, fetch=None) -> dict:
    """{isin: Reddit-Erwähnungen} für US-Titel der Auswahl (ApeWisdom, 3 Stunden zwischengespeichert). Fehler ergeben ein leeres Ergebnis."""
    path = os.path.join(config.DATA_DIR, "reddit.json")
    try:
        cache = json.load(open(path))
    except (OSError, json.JSONDecodeError):
        cache = {}
    us = {i: universe[i]["yf"] for i in isins if us_symbol(universe.get(i, {}).get("yf"))}
    if not us:
        return {}
    if time.time() - cache.get("time", 0) > MAX_AGE or not cache.get("rows"):
        try:
            cache = {"time": time.time(), "rows": (fetch or _fetch_ape)(wanted=set(us.values()))}
        except Exception:  # noqa: BLE001 – Zusatzsignal
            return {}
        os.makedirs(config.DATA_DIR, exist_ok=True)
        json.dump(cache, open(path, "w"))
    return {i: s for i, sym in us.items() if (s := ape_summary(cache["rows"], sym))}
