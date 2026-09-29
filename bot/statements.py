"""Bilanzqualität und Insider-Übersicht aus Yahoo-Daten, für die engere Auswahl, einmal pro Tag zwischengespeichert.

Bilanz: Aus den letzten Quartalsberichten (Bilanz, Gewinn- und Verlustrechnung, Cashflow) werden Kennzahlen berechnet: Nettoverschuldung zu EBITDA,
Zinsdeckung, Liquidität (Current Ratio), Eigenkapital, freier Cashflow, Marge und ein Piotroski-F-Score aus Vorjahresvergleichen der Quartale.
Es wird nur berechnet, was vorliegt. Fehlt etwas (Banken haben kein EBITDA, französische Firmen melden halbjährlich), bleibt das Feld leer und nichts wird geschätzt.

Insider: Yahoo liefert Käufe und Verkäufe der Führungskräfte nur für US-Aktien (SEC-Meldungen). Für deutsche Titel (Directors' Dealings bei der BaFin) hilft die Web-Recherche.

Beides ist nicht testbar (Yahoo hat keine Historie mit Veröffentlichungsstand) und steuert deshalb nicht die feste Berechnung, sondern geht als Information an Claude.
Nur ein *schweres* Bilanz-Warnsignal zählt in der Kontrolle (brain.guard) als belegter negativer Befund und erlaubt Claude, einen Kauf zu streichen."""
import json
import math
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import date

from . import config

NAN = float("nan")
FINANCIAL = ("Financial Services", "Financial", "Insurance", "Banks")   # Banken und Versicherer: Schulden- und Liquiditätskennzahlen sind dort nicht aussagekräftig


def _f(v) -> float:
    try:
        x = float(v)
    except (TypeError, ValueError):   # None, pd.NA und Ähnliches
        return NAN
    return NAN if math.isnan(x) else x


def _row(df, *names):
    """Werte einer Zeile, neuestes Quartal zuerst (fehlende Werte als NaN); None, wenn keine der Bezeichnungen existiert."""
    if df is None or getattr(df, "empty", True):
        return None
    for n in names:
        if n in df.index:
            return [_f(v) for v in df.loc[n].tolist()]
    return None


def _ok(*xs):
    return all(x is not None and not math.isnan(x) for x in xs)


def _ttm(vals):
    """Summe der letzten vier Quartale; None, wenn eines fehlt."""
    if not vals or len(vals) < 4 or not _ok(*vals[:4]):
        return None
    return sum(vals[:4])


def _at(vals, i):
    return vals[i] if vals and len(vals) > i and _ok(vals[i]) else None


def compute(bs, inc, cf, sector: str = None) -> dict:
    """Kennzahlen und Warnungen aus Quartalsdaten. Gibt {} zurück, wenn nichts berechenbar ist."""
    financial = bool(sector) and any(f.lower() in sector.lower() for f in FINANCIAL)
    revenue = _row(inc, "Total Revenue")
    gross = _row(inc, "Gross Profit")
    ebit = _row(inc, "EBIT", "Operating Income")
    ebitda = _row(inc, "EBITDA", "Normalized EBITDA")
    ni = _row(inc, "Net Income")
    interest = _row(inc, "Interest Expense")
    debt = _row(bs, "Total Debt")
    cash = _row(bs, "Cash And Cash Equivalents")
    equity = _row(bs, "Stockholders Equity", "Common Stock Equity")
    assets = _row(bs, "Total Assets")
    cur_a, cur_l = _row(bs, "Current Assets"), _row(bs, "Current Liabilities")
    shares = _row(bs, "Ordinary Shares Number", "Share Issued")
    cfo = _row(cf, "Operating Cash Flow")
    fcf = _row(cf, "Free Cash Flow")

    m, warn, severe = {}, [], []
    t_rev, t_ebit, t_ebitda, t_ni, t_cfo, t_fcf, t_int = (_ttm(x) for x in (revenue, ebit, ebitda, ni, cfo, fcf, interest))
    d0, c0, e0 = _at(debt, 0), _at(cash, 0), _at(equity, 0)

    if not financial and _ok(d0, c0, t_ebitda) and t_ebitda > 0:
        m["nettoschuld_ebitda"] = round((d0 - c0) / t_ebitda, 2)
        if m["nettoschuld_ebitda"] > 6:
            severe.append(f"Nettoverschuldung {m['nettoschuld_ebitda']:.1f}-faches EBITDA")
        elif m["nettoschuld_ebitda"] > 4:
            warn.append(f"Nettoverschuldung {m['nettoschuld_ebitda']:.1f}-faches EBITDA")
    if not financial and _ok(t_ebit, t_int) and t_int:
        m["zinsdeckung"] = round(t_ebit / abs(t_int), 2)
        net_cash = _ok(d0, c0) and c0 >= d0   # mehr Bargeld als Schulden: schwache Zinsdeckung ist dann kein Überlebensrisiko
        if m["zinsdeckung"] < 1.5 and not net_cash:
            severe.append(f"Zinsdeckung nur {m['zinsdeckung']:.1f}")
        elif m["zinsdeckung"] < 1.5:
            warn.append(f"Zinsdeckung nur {m['zinsdeckung']:.1f} (Bargeld übersteigt die Schulden)")
        elif m["zinsdeckung"] < 3:
            warn.append(f"Zinsdeckung {m['zinsdeckung']:.1f}")
    a0, l0 = _at(cur_a, 0), _at(cur_l, 0)
    if not financial and _ok(a0, l0) and l0 > 0:
        m["current_ratio"] = round(a0 / l0, 2)
        if m["current_ratio"] < 0.8:
            warn.append(f"Liquidität knapp (Current Ratio {m['current_ratio']:.2f})")
    if _ok(e0):
        m["eigenkapital_positiv"] = e0 > 0
        if not financial and _ok(d0) and e0 > 0:
            m["schulden_eigenkapital"] = round(d0 / e0, 2)
    if _ok(t_fcf, t_rev) and t_rev > 0:
        m["fcf_marge"] = round(t_fcf / t_rev, 3)
    if _ok(t_ni, e0) and e0 > 0:
        m["eigenkapitalrendite"] = round(t_ni / e0, 3)
    if _ok(t_cfo) and t_cfo < 0:
        warn.append("negativer operativer Cashflow in den letzten 12 Monaten")
    if not financial and _ok(e0, t_fcf) and e0 < 0 and t_fcf < 0:
        severe.append("negatives Eigenkapital bei negativem freiem Cashflow")
    g0, g4, r0, r4 = _at(gross, 0), _at(gross, 4), _at(revenue, 0), _at(revenue, 4)
    if _ok(g0, g4, r0, r4) and r0 > 0 and r4 > 0:
        m["bruttomarge_veraenderung_j"] = round(g0 / r0 - g4 / r4, 3)   # Quartal gegen Vorjahresquartal, Prozentpunkte als Anteil

    # Piotroski-F-Score aus Vorjahresvergleichen der Quartale (Quartal 0 gegen Quartal 4)
    sig = []
    ni0, ni4, as0, as4 = _at(ni, 0), _at(ni, 4), _at(assets, 0), _at(assets, 4)
    if _ok(t_ni):
        sig.append(t_ni > 0)
    if _ok(t_cfo):
        sig.append(t_cfo > 0)
    if _ok(ni0, ni4, as0, as4) and as0 > 0 and as4 > 0:
        sig.append(ni0 / as0 > ni4 / as4)
    if _ok(t_cfo, t_ni):
        sig.append(t_cfo > t_ni)
    d4 = _at(debt, 4)
    if _ok(d0, d4, as0, as4) and as0 > 0 and as4 > 0:
        sig.append(d0 / as0 < d4 / as4)
    ca4, cl4 = _at(cur_a, 4), _at(cur_l, 4)
    if _ok(a0, l0, ca4, cl4) and l0 > 0 and cl4 > 0:
        sig.append(a0 / l0 > ca4 / cl4)
    s0, s4 = _at(shares, 0), _at(shares, 4)
    if _ok(s0, s4):
        sig.append(s0 <= s4 * 1.005)
    if _ok(g0, g4, r0, r4) and r0 > 0 and r4 > 0:
        sig.append(g0 / r0 > g4 / r4)
    if _ok(r0, r4, as0, as4) and as0 > 0 and as4 > 0:
        sig.append(r0 / as0 > r4 / as4)
    if len(sig) >= 6:
        m["piotroski"] = f"{sum(sig)}/{len(sig)}"
        if sum(sig) / len(sig) <= 0.3:
            warn.append(f"schwache Bilanzqualität (Piotroski {sum(sig)}/{len(sig)})")

    if not m:
        return {}
    m["schwer"] = bool(severe)
    if severe or warn:
        m["warnungen"] = severe + warn
    return m


def insider_summary(df) -> dict:
    """Aus yfinance `insider_purchases`: Käufe und Verkäufe der Führungskräfte der letzten 6 Monate (nur US-Aktien haben Daten)."""
    if df is None or getattr(df, "empty", True) or df.shape[1] < 3:
        return {}
    rows = {str(r[0]).strip(): (r[1], r[2]) for r in df.itertuples(index=False)}

    def num(x):
        try:
            v = float(x)
            return None if math.isnan(v) else v
        except (TypeError, ValueError):
            return None
    buys, sells = rows.get("Purchases", (None, None)), rows.get("Sales", (None, None))
    net = rows.get("Net Shares Purchased (Sold)", (None, None))[0]
    n_buy, n_sell = num(buys[1]), num(sells[1])
    if not (n_buy or n_sell):
        return {}
    out = {"kaeufe": int(n_buy or 0), "verkaeufe": int(n_sell or 0), "netto_aktien": num(net)}
    out["signal"] = ("Netto-Käufe der Führungskräfte" if (num(net) or 0) > 0 and out["kaeufe"] >= out["verkaeufe"]
                     else "Netto-Verkäufe der Führungskräfte (oft planmäßig, schwaches Signal)" if (num(net) or 0) < 0 else "ausgeglichen")
    return out


def _fetch(sym: str, sector: str = None) -> dict:
    import yfinance as yf

    t, out = yf.Ticker(sym), {}
    try:
        b = compute(t.quarterly_balance_sheet, t.quarterly_income_stmt, t.quarterly_cashflow, sector)
        if b:
            out["bilanz"] = b
    except Exception:  # noqa: BLE001 – Zusatzdaten
        pass
    try:
        i = insider_summary(t.insider_purchases)
        if i:
            out["insider"] = i
    except Exception:  # noqa: BLE001
        pass
    return out


def get(universe: dict, isins: list, today: date, sectors: dict = None, fetch=None, workers: int = 4) -> dict:
    """{isin: {"bilanz": {...}, "insider": {...}}} für die Auswahl; nur was heute noch nicht im Zwischenspeicher liegt, wird geholt."""
    path = os.path.join(config.DATA_DIR, "statements.json")
    try:
        cache = json.load(open(path))
    except (OSError, json.JSONDecodeError):
        cache = {}
    if cache.get("date") != today.isoformat():
        cache = {"date": today.isoformat(), "items": {}}
    todo = [i for i in isins if i not in cache["items"] and universe.get(i, {}).get("yf")]
    if todo:
        fn = fetch or _fetch
        sectors = sectors or {}
        with ThreadPoolExecutor(workers) as ex:
            for isin, res in zip(todo, ex.map(lambda i: fn(universe[i]["yf"], sectors.get(i)), todo)):
                cache["items"][isin] = res
        os.makedirs(config.DATA_DIR, exist_ok=True)
        json.dump(cache, open(path, "w"), ensure_ascii=False)
    return {i: cache["items"].get(i, {}) for i in isins}
