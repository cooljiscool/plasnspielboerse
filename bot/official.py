"""Amtliche Wertpapierliste des Planspiels einlesen und daraus das Universum bauen (`python -m bot.universe_tool official`).

Die Liste (PDF auf planspiel-boerse.de, Bereich Wertpapiere) nennt die Bestandteile der Indizes DAX, MDAX, SDAX, TecDAX, EuroStoxx 50, Auswahl aus dem Stoxx Europe 600, Dow Jones,
Nasdaq 100, FTSE MIB, ATX, LuxX und Global Challenges mit ISIN. Titel mit „X“ in der Spalte Nachhaltigkeit zählen für die Nachhaltigkeitswertung. Fonds, ETFs, Anleihen, Kryptowerte
und Zertifikate (im Hauptdepot nur teils handelbar, Krypto und Zertifikate nur im Trainingsdepot) sind nicht Teil des Universums: Die Strategie handelt Aktien.

Zu jeder ISIN sucht `resolve` über die Yahoo-Suche das Börsenkürzel für die Kurse (Heimatbörse bevorzugt) und die Währung. Titel, die sich nicht sicher zuordnen lassen oder keine
aktuellen Kurse haben, entfallen und werden im Bericht genannt; das Ergebnis wird zwischengespeichert (data/cache/isin_map.json), damit spätere Aktualisierungen schnell gehen."""
import json
import os
import re
import subprocess
import urllib.request
from concurrent.futures import ThreadPoolExecutor

from . import config, fx

LIST_PAGE = "https://www.planspiel-boerse.de/wertpapierliste.html"
SECTIONS = (("DAX", "dax"), ("MDAX", "mdax"), ("SDAX", "sdax"), ("TecDAX", "tecdax"), ("EuroStoxx50", "eurostoxx50"), ("Selection Europe", "europa"),
            ("DOW JONES", "dow"), ("Nasdaq100", "nasdaq100"), ("FTSE MIB", "ftsemib"), ("ATX", "atx"), ("LuxX", "luxx"), ("Global Challenges", "gci"))
ROW = re.compile(r"^\s*(\d+)\s+(.*?)\s{2,}([A-Z]{2}[A-Z0-9]{9}[0-9])(?:\s+(.*?))?\s*$")
NOISE = re.compile(r"^(Seite \d+ von \d+|Planspiel Börse \d{4}\b.*|\(Stand:.*|Wertpapierart.*|Börse\s+NH\*.*|Land\s+Wertung|Kennzeichnung.*|\*Nachhaltigkeit.*|Components)$")
# Heimatbörsen je ISIN-Land, in Reihenfolge der Vorliebe ("" = US-Symbol ohne Endung)
HOME = {"DE": (".DE",), "AT": (".VI",), "FR": (".PA",), "NL": (".AS", ".PA"), "IT": (".MI",), "ES": (".MC",), "FI": (".HE",), "BE": (".BR",), "PT": (".LS",),
        "IE": (".IR",), "LU": (".PA", ".LU", ".DE", ".BR"), "SE": (".ST",), "DK": (".CO",), "NO": (".OL",), "CH": (".SW",), "GB": (".L",), "JE": (".L",),
        "GG": (".L",), "JP": (".T",), "BG": (".DE",), "US": ("",), "CA": (".TO", ""), "BM": ("", ".L"), "KY": ("",), "PA": ("",), "CW": ("",), "AN": ("",), "IL": ("",)}
SAFE_EUR = (".DE", ".PA", ".AS", ".MI", ".MC", ".VI", ".HE", ".BR", ".LS", ".IR")   # Endungen, die immer Euro bedeuten: keine Abfrage der Währung nötig
GROUP_ORDER = ("dax", "mdax", "sdax", "tecdax", "dow", "nasdaq100", "eurostoxx50", "ftsemib", "atx", "luxx", "europa", "gci")
GROUP_OF = {"dax": "dax", "mdax": "mdax", "sdax": "sdax", "tecdax": "sdax", "dow": "us", "nasdaq100": "us"}   # alles andere: "europa"


def valid_isin(isin: str) -> bool:
    """Prüfziffer nach ISO 6166 (Luhn über die in Zahlen umgesetzten Buchstaben)."""
    if not re.fullmatch(r"[A-Z]{2}[A-Z0-9]{9}[0-9]", isin or ""):
        return False
    digits = "".join(str(int(c, 36)) for c in isin)
    total = 0
    for i, ch in enumerate(reversed(digits)):
        n = int(ch)
        if i % 2 == 1:
            n = n * 2 - 9 if n * 2 > 9 else n * 2
        total += n
    return total % 10 == 0


def latest_url(fetch=None) -> str:
    """Adresse der aktuellen Liste aus der Seite planspiel-boerse.de/wertpapierliste.html (der Link enthält eine Prüfsumme und ändert sich mit jeder Fassung)."""
    html = (fetch or _get)(LIST_PAGE)
    m = re.search(r'(?:href|src)="([^"]*Wertpapierliste[^"]*\.pdf[^"]*)"', html, re.I) or re.search(r'(/api/download/[^"\s]*Wertpapierliste[^"\s]*)', html, re.I)
    if not m:
        raise RuntimeError("Auf der Seite wurde kein Link zur Wertpapierliste gefunden")
    return urllib.request.urljoin(LIST_PAGE, m.group(1).replace("&amp;", "&"))


def _get(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "planspiel-bot/1.0 (private research)"})
    return urllib.request.urlopen(req, timeout=60).read().decode("utf-8", errors="replace")


def download_pdf(dest: str, url: str = None) -> str:
    url = url or latest_url()
    req = urllib.request.Request(url, headers={"User-Agent": "planspiel-bot/1.0 (private research)"})
    data = urllib.request.urlopen(req, timeout=120).read()
    if not data.startswith(b"%PDF"):
        raise RuntimeError("Der Download ist keine PDF-Datei")
    os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)
    open(dest, "wb").write(data)
    return dest


def pdf_text(path: str) -> str:
    """Text der Liste; PDF über `pdftotext -layout` (Paket poppler-utils), Textdateien werden direkt gelesen."""
    if not path.lower().endswith(".pdf"):
        return open(path, encoding="utf-8").read()
    try:
        return subprocess.run(["pdftotext", "-layout", path, "-"], capture_output=True, text=True, check=True, timeout=120).stdout
    except FileNotFoundError as e:
        raise RuntimeError("pdftotext fehlt: Paket poppler-utils installieren (Docker: bereits enthalten) oder die Liste als Textdatei angeben") from e


def parse(text: str) -> list:
    """Aktien aus den Bestandteil-Listen der Indizes: [{isin, name, indices, land, stars}], Titel in mehreren Indizes zusammengeführt. Ungültige ISIN entfallen."""
    entries, cur = {}, None
    for line in text.splitlines():
        s = line.strip()
        if not s or NOISE.match(s):
            continue
        m = ROW.match(line)
        if m:
            if cur is None:
                continue
            _, name, isin, tail = m.groups()
            if not valid_isin(isin):
                continue
            parts = (tail or "").split()
            star = bool(parts) and parts[-1] == "X"
            land = " ".join(parts[:-1] if star else parts) or None
            e = entries.setdefault(isin, {"isin": isin, "name": name.strip(), "indices": [], "land": None, "stars": 0})
            if cur not in e["indices"]:
                e["indices"].append(cur)
            e["land"] = e["land"] or land
            e["stars"] = max(e["stars"], int(star))
            continue
        if re.search(r"[A-Z]{2}[A-Z0-9]{9}[0-9]", s):   # Zeile mit ISIN, aber ohne Zählernummer (Fonds, ETC ...): nicht Teil der Index-Listen
            continue
        key = next((k for h, k in SECTIONS if s.lower().startswith(h.lower())), None)
        cur = key   # unbekannte Überschrift (ETC, Zertifikate ...): nachfolgende Zeilen ignorieren
    return list(entries.values())


def group_of(indices: list, isin: str = "") -> str:
    """Markt-Gruppe für die Auswertung: dax, mdax, sdax (SDAX/TecDAX), us (Dow/Nasdaq oder US-ISIN) oder europa (alles übrige)."""
    first = next((i for i in GROUP_ORDER if i in indices), None)
    return GROUP_OF.get(first) or ("us" if isin[:2] in ("US", "CA") else "europa")


def _equities(isin: str, quotes: list) -> list:
    """Aktien aus den Suchtreffern; Fantasiesymbole, die nur aus der ISIN bestehen (z. B. "DE000A2YNT30.SG", ohne Kurse), zählen nicht."""
    return [q for q in quotes if q.get("quoteType") == "EQUITY" and q.get("symbol") and q["symbol"].split(".")[0].upper() != isin.upper()]


US_MAJOR = {"NMS", "NGM", "NCM", "NYQ", "ASE", "PCX", "BTS", "NASDAQ", "NYSE", "NYSE American", "NYSEArca"}   # Yahoo-Börsencodes der großen US-Märkte (nicht Freiverkehr wie PNK)


def _us(q: dict) -> bool:
    """US-Notierung an einer großen Börse: Symbol ohne Endung; ist die Börse angegeben, muss es eine große sein (Freiverkehr wie "KLKNF" an der PNK zählt nicht)."""
    ex = q.get("exchange") or q.get("exchDisp")
    return "." not in q["symbol"] and (ex is None or ex in US_MAJOR)


def _home(isin: str, q: dict):
    """Rang der Börse eines Treffers für das Land der ISIN (0 = beste Heimatbörse), None wenn keine Heimatbörse."""
    sym = q["symbol"].upper()
    if re.fullmatch(r"0[A-Z0-9]{3}\.L", sym):   # "0Y6X.L": Spiegelnotiz im internationalen Orderbuch London, kaum Umsatz, nicht die Londoner Heimatnotiz
        return None
    for n, suf in enumerate(HOME.get(isin[:2], ())):
        if (suf == "" and _us(q)) or (suf and sym.endswith(suf)):
            return n
    return None


def pick_symbol(isin: str, quotes: list, tiers=("home", "us", "eur")):
    """Wählt aus Suchtreffern der Yahoo-Suche eine Aktie, stufenweise: "home" = Heimatbörse des ISIN-Landes; "us" = US-Notierung an einer großen Börse (viele Konzerne mit
    europäischer ISIN sind primär in den USA notiert, z. B. NXP, Linde, Medtronic); "eur" = irgendeine Euro-Börse. Nie ein Freiverkehrs-Symbol (z. B. "KLKNF")."""
    eq = _equities(isin, quotes)
    if "home" in tiers:
        ranked = sorted((q for q in eq if _home(isin, q) is not None), key=lambda q: _home(isin, q))
        if ranked:
            return ranked[0]
    if "us" in tiers and (q := next((q for q in eq if _us(q)), None)):
        return q
    if "eur" in tiers:
        return next((q for q in eq if fx.infer_currency(q["symbol"]) == "EUR"), None)
    return None


def _yahoo_search(query: str) -> list:
    import yfinance as yf
    return yf.Search(query, max_results=8, news_count=0).quotes


def _yahoo_currency(symbol: str):
    import yfinance as yf
    return yf.Ticker(symbol).fast_info.get("currency")


def _exists(symbol: str) -> bool:
    import yfinance as yf
    return not yf.Ticker(symbol).history(period="5d").empty


def clean_name(name: str) -> str:
    """Suchbegriff aus der Listenbezeichnung: ohne Nennwert- und Währungsangaben ("EO -,01", "SK 0,025", "DL-,001", "INH", "O.N.")."""
    drop = {"EO", "DL", "SK", "NK", "DK", "LS", "SF", "INH", "NA", "O.N.", "ON", "NAM", "NAM.", "VZO", "FRIA", "WI", "ST", "PORT.", "(P.S.)"}
    words = [w for w in name.replace("+", " ").split() if not re.search(r"\d", w) and w.upper() not in drop]
    return " ".join(words) or name


def _plausible(name: str, quote: dict) -> bool:
    """Bei Suche nach dem Namen (nicht der ISIN): das erste längere Wort der Listenbezeichnung muss im Namen des Treffers vorkommen."""
    word = next((w for w in re.findall(r"[A-Za-zÄÖÜäöüß]{4,}", name)), None)
    text = f"{quote.get('shortname', '')} {quote.get('longname', '')}".lower()
    return bool(word) and word.lower() in text


def _share_class(name: str):
    """Aktiengattung am Ende der Listenbezeichnung ("KESKO B", "KINNEVIK B SK 0,025"): A, B oder C; sonst None."""
    m = re.search(r"(?:^|\s)(A|B|C)(?=\s|$)", clean_name(name))
    return m.group(1) if m else None


REGIONAL = (".F", ".SG", ".HM", ".MU", ".DU", ".BE", ".HA", ".XC", ".XD")   # deutsche Nebenplätze: gleiches Kürzel wie an der Xetra (".DE")
OVERRIDES = {"US02079K3059": "GOOGL", "US02079K1079": "GOOG", "US7223041028": "PDD"}   # Alphabet A und C (gleicher Name, nicht trennbar); Pinduoduo heißt jetzt PDD Holdings
SEARCH_PAUSE = 1.0


def resolve_one(entry: dict, search=None, currency=None, exists=None, sleep=None):
    """Ergänzt einen Eintrag um yf, currency und einen lesbaren Namen. Gibt None zurück, wenn keine sichere Zuordnung möglich ist. Reihenfolge:
    (1) Treffer der ISIN-Suche an der Heimatbörse; (2) deutsche Nebenplätze (Yahoo liefert für kleine Werte oft nur Frankfurt "XYZ.F", gehandelt wird Xetra "XYZ.DE"): dasselbe
    Kürzel an der Xetra, wenn es Kurse gibt; (3) US-Notierung an einer großen Börse; (4) Suche nach dem Namen (auch nur das erste Wort), nur mit Heimatbörse und passendem
    Namen, bei A/B-Aktien die passende Gattung; (5) irgendeine Euro-Börse. Leere Antworten der Suche werden einmal wiederholt (Yahoo drosselt bei vielen Anfragen)."""
    import time
    search, currency, exists, sleep = search or _yahoo_search, currency or _yahoo_currency, exists or _exists, sleep or time.sleep
    isin, name = entry["isin"], entry["name"]
    quotes = search(isin) or []
    if not quotes:
        sleep(SEARCH_PAUSE)
        quotes = search(isin) or []
    def xetra(hits):
        """Deutsche Nebenplätze (Frankfurt, Stuttgart, München ...) ergeben dasselbe Kürzel an der Xetra, wenn es dort Kurse gibt."""
        for x in hits:
            if x["symbol"].upper().endswith(REGIONAL) and exists(x["symbol"].rsplit(".", 1)[0] + ".DE"):
                return {**x, "symbol": x["symbol"].rsplit(".", 1)[0] + ".DE"}
        return None
    q = {"symbol": OVERRIDES[isin], "quoteType": "EQUITY"} if isin in OVERRIDES else pick_symbol(isin, quotes, tiers=("home",))
    q = q or xetra(_equities(isin, quotes)) or pick_symbol(isin, quotes, tiers=("us",))
    if q is None:
        cls, cand, named = _share_class(name), [], []
        for query in dict.fromkeys([clean_name(name), clean_name(name).split()[0]]):
            named = [c for c in _equities(isin, search(query) or []) if _plausible(name, c)]
            cand = [c for c in named if _home(isin, c) is not None]
            if cand:
                break
        cand.sort(key=lambda c: (_home(isin, c), not (cls and re.sub(r"[-.]", "", c["symbol"].rsplit(".", 1)[0]).upper().endswith(cls))))
        q = cand[0] if cand else xetra(named)
    q = q or pick_symbol(isin, quotes, tiers=("eur",))
    if q is None:
        return None
    sym = q["symbol"]
    ccy = fx.infer_currency(sym)
    if ccy is None or not sym.upper().endswith(SAFE_EUR) and "." in sym:   # Endungen außerhalb der Eurobörsen: Währung bei Yahoo erfragen (London z. B. Pence oder Dollar)
        try:
            ccy = currency(sym) or ccy
        except Exception:  # noqa: BLE001
            pass
    if ccy is None:
        return None
    return {"yf": sym, "currency": ccy, "name": q.get("longname") or q.get("shortname") or name}


def resolve(entries: list, search=None, currency=None, workers: int = 4, cache_path: str = None, exists=None, sleep=None):
    """(zugeordnete Einträge, nicht zuordenbare). Bereits zugeordnete ISIN kommen aus dem Zwischenspeicher."""
    cache_path = cache_path or os.path.join(config.DATA_DIR, "cache", "isin_map.json")
    try:
        cache = json.load(open(cache_path))
    except (OSError, json.JSONDecodeError):
        cache = {}
    todo = [e for e in entries if e["isin"] not in cache]

    def one(e):
        try:
            return resolve_one(e, search, currency, exists, sleep)
        except Exception:  # noqa: BLE001 – Suche kurzzeitig gestört: nicht zwischenspeichern, beim nächsten Mal erneut versuchen
            return "fehler"
    with ThreadPoolExecutor(workers) as ex:
        for e, r in zip(todo, ex.map(one, todo)):
            if r not in (None, "fehler"):   # Fehlschläge nicht merken: Sie werden bei der nächsten Aktualisierung erneut versucht
                cache[e["isin"]] = r
    os.makedirs(os.path.dirname(cache_path), exist_ok=True)
    json.dump(cache, open(cache_path, "w"), ensure_ascii=False)
    ok, missing = [], []
    for e in entries:
        r = cache.get(e["isin"])
        (ok if r else missing).append({**e, **r} if r else e)
    return ok, missing


def to_universe(resolved: list) -> list:
    """Universum-Zeilen für data/universe.json. Gleiches Yahoo-Symbol unter zwei ISIN (z. B. Doppelnotiz): nur die erste."""
    out, seen = [], set()
    for e in sorted(resolved, key=lambda e: (GROUP_ORDER.index(next((i for i in GROUP_ORDER if i in e["indices"]), "europa")), e["isin"])):
        if e["yf"] in seen:
            continue
        seen.add(e["yf"])
        out.append({"isin": e["isin"], "name": e["name"], "search": e["isin"], "yf": e["yf"], "currency": e["currency"], "stars": e["stars"],
                    "markt": group_of(e["indices"], e["isin"]), "indices": e["indices"], "land": e.get("land"), "liste": e["name"]})
    return out


MIN_QUOTED_DAYS = 12   # mindestens so viele Kurse im letzten Monat (rund 21 Handelstage), sonst zu dünn gehandelt für verlässliche Kennzahlen


def alive(rows: list, download=None) -> list:
    """Nur Titel mit Kursen der letzten Tage und genug Handelstagen (Delisting, Handelsaussetzung, falsches Symbol und dünn gehandelte Nebenplätze fallen hier heraus)."""
    syms = [r["yf"] for r in rows]
    if download is None:
        import yfinance as yf

        def download(s):
            d = yf.download(s, period="1mo", interval="1d", progress=False, group_by="ticker", threads=True, auto_adjust=True)
            return {x for x in s if x in d.columns.get_level_values(0) and d[x]["Close"].notna().sum() >= MIN_QUOTED_DAYS}
    good = set(download(syms))
    return [r for r in rows if r["yf"] in good]


def build(text: str, search=None, currency=None, download=None, cache_path: str = None, exists=None, sleep=None):
    """Aus dem Text der Liste: (Universum, Bericht). Der Bericht nennt Zahlen und alles, was entfallen ist."""
    entries = parse(text)
    ok, missing = resolve(entries, search, currency, cache_path=cache_path, exists=exists, sleep=sleep)
    rows = to_universe(ok)
    live = alive(rows, download)
    dead = [r for r in rows if r not in live]
    report = {"aus_liste": len(entries), "ohne_kuerzel": [f"{e['name']} ({e['isin']})" for e in missing],
              "ohne_kurse": [f"{r['name']} ({r['yf']})" for r in dead], "universum": len(live),
              "je_gruppe": {g: sum(r["markt"] == g for r in live) for g in ("dax", "mdax", "sdax", "europa", "us")},
              "mit_stern": sum(r["stars"] for r in live), "waehrungen": {c: sum(r["currency"] == c for r in live) for c in sorted({r["currency"] for r in live})}}
    return live, report
