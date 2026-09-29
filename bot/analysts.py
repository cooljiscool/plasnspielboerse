"""Änderungen der Analystenschätzungen und Ratings (Yahoo), für die engere Auswahl, einmal pro Tag zwischengespeichert.

Warum: Die Richtung, in die Analysten ihre Gewinnschätzungen ändern („Earnings Revisions“), gehört zu den am besten belegten Signalen der Forschung: Titel mit steigenden
Schätzungen schlagen danach im Schnitt den Markt, Titel mit sinkenden bleiben zurück. Heraufstufungen und Herabstufungen wirken ähnlich, aber schwächer.

Ein historischer Test über die Planspiel-Jahre ist nicht möglich (Yahoo liefert nur den heutigen Stand, nicht den damaligen). Die Angaben gehen deshalb als Information an Claude.
Nur eine deutlich gesenkte Schätzung (mindestens 5 % in 30 Tagen bei mindestens 3 Senkungen und höchstens 1 Erhöhung) zählt in der Kontrolle (brain.guard)
als belegter negativer Befund und erlaubt Claude, einen Kauf zu streichen."""
import json
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta

from . import config

CUT = -0.05          # Gewinnschätzung fürs laufende Jahr in 30 Tagen um mindestens 5 % gesenkt
RAISE = 0.05


def _num(x):
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return None if v != v else v


def _cell(df, row, col):
    """Wert einer Tabelle nach Zeilen- und Spaltenname, Spaltennamen ohne Rücksicht auf Groß- und Kleinschreibung."""
    if df is None or getattr(df, "empty", True) or row not in df.index:
        return None
    cols = {str(c).lower(): c for c in df.columns}
    return _num(df.loc[row, cols[col.lower()]]) if col.lower() in cols else None


def metrics(eps_trend, eps_rev, updown, reco, targets, today: date) -> dict:
    """Kennzahlen zu Schätzungsänderungen. Es wird nur ausgewiesen, was vorliegt."""
    out = {}
    for period, key in (("0y", "eps_jahr"), ("+1y", "eps_folgejahr")):
        cur = _cell(eps_trend, period, "current")
        for col, tag in (("30daysAgo", "30d"), ("90daysAgo", "90d")):
            old = _cell(eps_trend, period, col)
            if cur is not None and old:
                out[f"{key}_aenderung_{tag}"] = round(cur / old - 1, 4) if old > 0 else None
    out = {k: v for k, v in out.items() if v is not None}
    up30, down30 = _cell(eps_rev, "0y", "upLast30days"), _cell(eps_rev, "0y", "downLast30days")
    if up30 is not None and down30 is not None:
        out["revisionen_30d"] = {"erhoeht": int(up30), "gesenkt": int(down30)}
    if updown is not None and not getattr(updown, "empty", True):
        since = datetime.combine(today, datetime.min.time()) - timedelta(days=90)
        recent = updown[[ts.to_pydatetime().replace(tzinfo=None) >= since for ts in updown.index]]
        act = recent["Action"].astype(str).str.lower() if "Action" in recent else []
        pt = recent["priceTargetAction"].astype(str).str.lower() if "priceTargetAction" in recent else []
        if len(recent):
            out["ratings_90d"] = {"herauf": int((act == "up").sum()), "herab": int((act == "down").sum()),
                                  "kursziel_erhoeht": int((pt == "raises").sum()), "kursziel_gesenkt": int((pt == "lowers").sum())}
    if reco is not None and not getattr(reco, "empty", True) and "period" in reco:
        def buy_share(row):
            r = reco[reco["period"] == row]
            if r.empty:
                return None
            tot = sum(_num(r.iloc[0].get(c)) or 0 for c in ("strongBuy", "buy", "hold", "sell", "strongSell"))
            return None if not tot else ((_num(r.iloc[0].get("strongBuy")) or 0) + (_num(r.iloc[0].get("buy")) or 0)) / tot
        now, before = buy_share("0m"), buy_share("-3m")
        if now is not None:
            out["kauf_anteil"] = round(now, 2)
            if before is not None:
                out["kauf_anteil_aenderung_3m"] = round(now - before, 2)
    if isinstance(targets, dict) and _num(targets.get("mean")) and _num(targets.get("high")) is not None and _num(targets.get("low")) is not None:
        out["kursziel_streuung"] = round((targets["high"] - targets["low"]) / targets["mean"], 2)   # große Streuung = Analysten uneinig

    chg, rev = out.get("eps_jahr_aenderung_30d"), out.get("revisionen_30d")
    if chg is not None and rev:
        if chg <= CUT and rev["gesenkt"] >= 3 and rev["erhoeht"] <= 1:
            out["schaetzungen_gesenkt"] = True
        elif chg >= RAISE and rev["erhoeht"] >= 3 and rev["gesenkt"] <= 1:
            out["schaetzungen_angehoben"] = True
    rt = out.get("ratings_90d")
    if rt and rt["herab"] >= 3 and rt["herab"] > 2 * rt["herauf"]:
        out["herabstufungen_ueberwiegen"] = True
    return out


def _fetch(sym: str) -> dict:
    import yfinance as yf

    t = yf.Ticker(sym)

    def safe(name):
        try:
            return getattr(t, name)
        except Exception:  # noqa: BLE001 – Zusatzdaten
            return None
    return metrics(safe("eps_trend"), safe("eps_revisions"), safe("upgrades_downgrades"), safe("recommendations"),
                   safe("analyst_price_targets"), date.today())


def get(universe: dict, isins: list, today: date, fetch=None, workers: int = 4) -> dict:
    """{isin: Kennzahlen} für die Auswahl; nur was heute noch nicht im Zwischenspeicher liegt, wird geholt."""
    path = os.path.join(config.DATA_DIR, "analysts.json")
    try:
        cache = json.load(open(path))
    except (OSError, json.JSONDecodeError):
        cache = {}
    if cache.get("date") != today.isoformat():
        cache = {"date": today.isoformat(), "items": {}}
    todo = [i for i in isins if i not in cache["items"] and universe.get(i, {}).get("yf")]
    if todo:
        fn = fetch or _fetch

        def one(isin):
            try:
                return fn(universe[isin]["yf"])
            except Exception:  # noqa: BLE001
                return {}
        with ThreadPoolExecutor(workers) as ex:
            for isin, res in zip(todo, ex.map(one, todo)):
                cache["items"][isin] = res
        os.makedirs(config.DATA_DIR, exist_ok=True)
        json.dump(cache, open(path, "w"))
    return {i: cache["items"][i] for i in isins if cache["items"].get(i)}
