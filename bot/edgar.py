"""Insider-Geschäfte der Führungskräfte aus den offiziellen SEC-Meldungen (Form 4), kostenlos und ohne Schlüssel, nur US-Aktien.

Warum das die wichtigste der „Quiver-Datenquellen“ ist: Offene Marktkäufe von Vorständen und Aufsichtsräten (Transaktionscode P), besonders wenn mehrere
Insider kurz nacheinander kaufen („Cluster“), gelten in der Forschung als Signal für Überrendite. Verkäufe sind dagegen ein schwaches Signal: Viele sind
vorab geplant (Rule 10b5-1) oder dienen der Steuer. Deshalb werden geplante Verkäufe getrennt gezählt.

Die Angaben gehen nur als Information an Claude. Ein historischer Test über die Planspiel-Jahre wäre möglich (die SEC hat die ganze Geschichte), aber sehr aufwendig
und wegen der wenigen Ereignisse je Titel und Jahr wenig aussagekräftig; er ist nicht gemacht.

SEC-Regeln: höchstens 10 Anfragen pro Sekunde, eine Kennung mit Kontaktdaten im User-Agent (Umgebungsvariable SEC_USER_AGENT, z. B. "Vorname Nachname mail@example.org").
Ohne eigene Kontaktdaten (kein "@" in SEC_USER_AGENT) ruft der Bot nichts ab, statt sich mit einer erfundenen Kennung auszugeben."""
import json
import os
import re
import time
import urllib.request
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta

from . import config

TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{}.json"
ARCHIVE_URL = "https://www.sec.gov/Archives/edgar/data/{}/{}/{}"
PAUSE = 0.15          # Sekunden zwischen Anfragen (SEC-Grenze: 10 pro Sekunde)
MAX_XML_BYTES = 400_000
CLUSTER_DAYS = 30


def _cache(name: str) -> str:
    return os.path.join(config.DATA_DIR, "cache", name)


def _default_fetch(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": config.SEC_USER_AGENT})
    time.sleep(PAUSE)
    return urllib.request.urlopen(req, timeout=30).read().decode("utf-8", errors="replace")


def cik_map(fetch=None) -> dict:
    """{Ticker: CIK mit 10 Stellen}, eine Woche zwischengespeichert."""
    path = _cache("sec_tickers.json")
    if os.path.exists(path) and time.time() - os.path.getmtime(path) < 7 * 86400:
        return json.load(open(path))
    data = json.loads((fetch or _default_fetch)(TICKERS_URL))
    out = {v["ticker"].upper(): str(v["cik_str"]).zfill(10) for v in data.values()}
    os.makedirs(os.path.dirname(path), exist_ok=True)
    json.dump(out, open(path, "w"))
    return out


def parse_form4(xml_text: str) -> list:
    """Transaktionen (ohne Derivate) aus einer Form-4-Datei. Leere Liste bei unlesbarem oder verdächtigem XML."""
    if len(xml_text) > MAX_XML_BYTES or "<!DOCTYPE" in xml_text or "<!ENTITY" in xml_text:   # Schutz vor manipuliertem XML
        return []
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []

    def num(el, path):
        try:
            return float(el.findtext(path) or "")
        except ValueError:
            return None
    owners = []
    for o in root.iter("reportingOwner"):
        rel = o.find("reportingOwnerRelationship")
        flag = lambda tag: (rel.findtext(tag) or "0").strip() in ("1", "true") if rel is not None else False  # noqa: E731
        role = (rel.findtext("officerTitle") or "").strip() if rel is not None else ""
        owners.append({"name": (o.findtext("reportingOwnerId/rptOwnerName") or "?").strip(),
                       "rolle": role or ("Director" if flag("isDirector") else "10%-Eigner" if flag("isTenPercentOwner") else "Insider")})
    planned = (root.findtext("aff10b5One") or "0").strip() in ("1", "true")
    who = owners[0] if owners else {"name": "?", "rolle": "Insider"}
    out = []
    for t in root.iter("nonDerivativeTransaction"):
        code = (t.findtext("transactionCoding/transactionCode") or "").strip()
        day = (t.findtext("transactionDate/value") or "")[:10]
        shares, price = num(t, "transactionAmounts/transactionShares/value"), num(t, "transactionAmounts/transactionPricePerShare/value")
        if not code or not day or shares is None:
            continue
        out.append({"datum": day, "code": code, "aktien": shares, "preis": price or 0.0, "insider": who["name"],
                    "rolle": who["rolle"], "geplant": planned,
                    "richtung": (t.findtext("transactionAmounts/transactionAcquiredDisposedCode/value") or "").strip()})
    return out


def recent_form4(cik: str, today: date, days: int = 90, max_filings: int = 40, fetch=None) -> list:
    """Alle Form-4-Transaktionen der letzten `days` Tage eines Unternehmens (die neuesten max_filings Meldungen)."""
    fetch = fetch or _default_fetch
    rec = json.loads(fetch(SUBMISSIONS_URL.format(cik)))["filings"]["recent"]
    since = (today - timedelta(days=days)).isoformat()
    out, n = [], 0
    for i, form in enumerate(rec["form"]):
        if form != "4" or rec["filingDate"][i] < since:
            continue
        if n >= max_filings:
            break
        n += 1
        acc = rec["accessionNumber"][i].replace("-", "")
        raw = re.sub(r"^xsl[^/]+/", "", rec["primaryDocument"][i])   # die Rohdatei liegt ohne den Anzeige-Ordner
        try:
            out += parse_form4(fetch(ARCHIVE_URL.format(int(cik), acc, raw)))
        except Exception:  # noqa: BLE001 – eine kaputte Meldung darf die übrigen nicht verhindern
            continue
    return [t for t in out if t["datum"] >= since]


def summarize(txns: list) -> dict:
    """Zahlen zu offenen Marktkäufen (P) und -verkäufen (S). Leeres Ergebnis, wenn es nichts davon gab."""
    buys = [t for t in txns if t["code"] == "P"]
    sells = [t for t in txns if t["code"] == "S"]
    if not buys and not sells:
        return {}
    value = lambda ts: round(sum(t["aktien"] * t["preis"] for t in ts))  # noqa: E731
    out = {"kaeufe": len(buys), "kaeufer": len({t["insider"] for t in buys}), "kaufvolumen_usd": value(buys),
           "verkaeufe_ungeplant": sum(1 for t in sells if not t["geplant"]), "verkaeufe_geplant_10b5_1": sum(1 for t in sells if t["geplant"]),
           "verkaufsvolumen_usd": value(sells)}
    if buys:
        out["kaeufer_rollen"] = sorted({t["rolle"] for t in buys})[:4]
        out["letzter_kauf"] = max(t["datum"] for t in buys)
    days = sorted(datetime.fromisoformat(t["datum"]) for t in buys)
    people = {}
    for t in buys:
        people.setdefault(t["insider"], []).append(datetime.fromisoformat(t["datum"]))
    out["cluster_kauf"] = any(len({p for p, ds in people.items() if any(0 <= (d - d0).days <= CLUSTER_DAYS for d in ds)}) >= 2 for d0 in days)
    out["signal"] = ("Cluster: mehrere Führungskräfte kauften innerhalb von 30 Tagen am offenen Markt" if out["cluster_kauf"]
                     else "Insider-Kauf am offenen Markt" if buys
                     else "nur Verkäufe (überwiegend geplant, schwaches Signal)" if out["verkaeufe_ungeplant"] <= out["verkaeufe_geplant_10b5_1"]
                     else "Insider-Verkäufe ohne Plan (schwaches Signal)")
    return out


def contact_ok() -> bool:
    return "@" in config.SEC_USER_AGENT


def get(universe: dict, isins: list, today: date, fetch=None, symbol_ok=None) -> dict:
    """{isin: Zusammenfassung} für US-Titel der Auswahl, einmal pro Tag zwischengespeichert. Einzelne Fehler werden übersprungen.
    Ohne Kontaktdaten in SEC_USER_AGENT (und ohne eigene fetch-Funktion) wird nichts abgerufen."""
    from .social import us_symbol
    if fetch is None and not contact_ok():
        return {}
    symbol_ok = symbol_ok or us_symbol
    path = os.path.join(config.DATA_DIR, "edgar.json")
    try:
        cache = json.load(open(path))
    except (OSError, json.JSONDecodeError):
        cache = {}
    if cache.get("date") != today.isoformat():
        cache = {"date": today.isoformat(), "items": {}}
    todo = [i for i in isins if i not in cache["items"] and symbol_ok(universe.get(i, {}).get("yf"))]
    if todo:
        ciks = cik_map(fetch)
        for isin in todo:
            cik = ciks.get(universe[isin]["yf"].upper())
            try:
                cache["items"][isin] = summarize(recent_form4(cik, today, fetch=fetch)) if cik else {}
            except Exception:  # noqa: BLE001
                cache["items"][isin] = {}
        os.makedirs(config.DATA_DIR, exist_ok=True)
        json.dump(cache, open(path, "w"))
    return {i: cache["items"][i] for i in isins if cache["items"].get(i)}
