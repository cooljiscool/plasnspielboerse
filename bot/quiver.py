"""Quiver Quantitative (quiverquant.com): Alternativdaten zu US-Aktien. OPTIONAL und KOSTENPFLICHTIG (Schnittstelle ab 30 $ pro Monat, je nach Tarif verschiedene Datensätze).

Ohne Schlüssel (Umgebungsvariable QUIVER_API_TOKEN, im Dashboard unter Einstellungen) wird nichts abgerufen. Genutzt werden fünf Datensätze:
- Kongress-Handel (Aktiengeschäfte von US-Abgeordneten): in der Forschung nur schwach und umstritten belegt (nach dem STOCK Act kaum Überrendite),
- Regierungsaufträge und Lobbyausgaben: Zusatzinformation zur Abhängigkeit von Staatsgeschäften,
- Wikipedia-Aufrufe: Aufmerksamkeit (kann ein Gegenindikator sein),
- außerbörslicher Leerverkaufsanteil (Dark-Pool-Index).
Alles geht nur als Information an Claude. Kostenlos und besser belegt sind die Insider-Käufe aus den SEC-Meldungen (bot/edgar.py).

STAND: Endpunkte und Anmeldeverfahren stammen aus dem öffentlichen Quellcode des Python-Pakets `quiverquant` (Authorization: Token ...). Die Feldnamen der Antworten
werden tolerant gelesen. NICHT gegen die echte Schnittstelle getestet (ohne bezahlten Schlüssel nicht möglich): beim ersten Einsatz die Ausgabe im Protokoll prüfen."""
import json
import os
import time
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta

from . import config

BASE = "https://api.quiverquant.com/beta"
PATHS = {"kongress": "/historical/congresstrading/{}", "regierung": "/historical/govcontractsall/{}", "lobbying": "/historical/lobbying/{}",
         "wikipedia": "/historical/wikipedia/{}", "leerverkauf": "/historical/offexchange/{}"}
UPGRADE = "Upgrade your subscription plan"
PAUSE = 0.25


class AuthError(Exception):
    """Schlüssel ungültig oder abgelaufen: weitere Abfragen wären zwecklos."""


def _default_fetch(path: str, token: str):
    req = urllib.request.Request(BASE + path, headers={"accept": "application/json", "Authorization": "Token " + token,
                                                       "User-Agent": "planspiel-bot/1.0 (private research)"})
    time.sleep(PAUSE)
    try:
        body = urllib.request.urlopen(req, timeout=30).read().decode()
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            raise AuthError(f"HTTP {e.code}") from e
        raise
    if UPGRADE in body:
        return None                                   # Datensatz gehört nicht zum gebuchten Tarif
    return json.loads(body)


def _day(row: dict, *keys):
    for k in keys:
        v = row.get(k)
        if not v:
            continue
        try:
            return datetime.fromisoformat(str(v)[:10]).date()
        except ValueError:
            continue
    return None


def _num(x):
    try:
        v = float(str(x).replace(",", "").replace("$", ""))
    except (TypeError, ValueError):
        return None
    return None if v != v else v


def _since(rows, today: date, days: int, *keys):
    lo = today - timedelta(days=days)
    return [r for r in rows if isinstance(r, dict) and (d := _day(r, *keys)) and lo <= d <= today]


def summarize(name: str, rows, today: date) -> dict:
    """Kompakte Zahlen aus den Zeilen eines Datensatzes; {} wenn nichts Auswertbares vorliegt. Feldnamen werden tolerant gelesen."""
    if not isinstance(rows, list) or not rows:
        return {}
    if name == "kongress":
        recent = _since(rows, today, 90, "TransactionDate", "Traded", "ReportDate", "Filed")
        buys = [r for r in recent if "purchase" in str(r.get("Transaction", "")).lower()]
        sells = [r for r in recent if "sale" in str(r.get("Transaction", "")).lower()]
        if not (buys or sells):
            return {}
        who = lambda rs: len({str(r.get("Representative") or r.get("Name") or "?") for r in rs})  # noqa: E731
        return {"kaeufe_90d": len(buys), "kaeufer": who(buys), "verkaeufe_90d": len(sells), "verkaeufer": who(sells)}
    if name in ("regierung", "lobbying"):
        recent = _since(rows, today, 365, "Date", "Report_Date", "TransactionDate")
        vals = [v for r in recent if (v := _num(r.get("Amount"))) is not None]
        return {"summe_12m_usd": round(sum(vals)), "eintraege_12m": len(recent)} if recent and vals else {}
    if name == "wikipedia":
        recent, before = _since(rows, today, 14, "Date"), _since(rows, today - timedelta(days=14), 14, "Date")
        a = [v for r in recent if (v := _num(r.get("Views"))) is not None]
        b = [v for r in before if (v := _num(r.get("Views"))) is not None]
        if a and b and sum(b):
            return {"aufrufe_14d_schnitt": round(sum(a) / len(a)), "veraenderung_zu_vorher": round((sum(a) / len(a)) / (sum(b) / len(b)) - 1, 2)}
        return {}
    if name == "leerverkauf":
        recent = _since(rows, today, 10, "Date")
        dpi = [v for r in recent if (v := _num(r.get("DPI"))) is not None]
        return {"dark_pool_index_10d": round(sum(dpi) / len(dpi), 3)} if dpi else {}
    return {}


def get(universe: dict, isins: list, today: date, token: str = None, fetch=None):
    """(Daten, Fehler): {isin: {Datensatz: Zahlen}} für US-Titel der Auswahl, einmal pro Tag zwischengespeichert. Ohne Schlüssel ({}, None)."""
    from .social import us_symbol
    token = token if token is not None else config.QUIVER_TOKEN
    if not token:
        return {}, None
    path = os.path.join(config.DATA_DIR, "quiver.json")
    try:
        cache = json.load(open(path))
    except (OSError, json.JSONDecodeError):
        cache = {}
    if cache.get("date") != today.isoformat():
        cache = {"date": today.isoformat(), "items": {}}
    fetch = fetch or _default_fetch
    error = None
    for isin in [i for i in isins if i not in cache["items"] and us_symbol(universe.get(i, {}).get("yf"))]:
        sym, res = universe[isin]["yf"], {}
        try:
            for name, p in PATHS.items():
                s = summarize(name, fetch(p.format(sym), token), today)
                if s:
                    res[name] = s
        except AuthError as e:
            error = f"Quiver lehnt den Schlüssel ab ({e}); Schlüssel und Tarif prüfen"
            break
        except Exception as e:  # noqa: BLE001 – Zusatzdaten
            error = f"Quiver-Abruf gescheitert: {str(e)[:100]}"
        cache["items"][isin] = res
    os.makedirs(config.DATA_DIR, exist_ok=True)
    json.dump(cache, open(path, "w"))
    return {i: cache["items"][i] for i in isins if cache["items"].get(i)}, error
