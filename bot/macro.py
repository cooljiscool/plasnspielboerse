"""Zins- und Konjunkturdaten (FRED, EZB): frei abrufbar, ohne Schlüssel.

Zwei Verwendungen:
1. `snapshot()`: aktuelle Makrolage als Zusatzinformation für Claude (Zinskurve, Kreditaufschläge, Leitzinsen, Arbeitslosigkeit, Inflation).
2. `frame(dates)`: dieselben Kennzahlen als Zeitreihe für den Backtest, mit dem Veröffentlichungsstand des jeweiligen Tages (monatliche Werte erscheinen
   erst Wochen später; sie werden entsprechend verzögert, damit der Test nicht in die Zukunft schaut).

Ob Makrodaten die Regeln verbessern, prüft `python -m bot.lab --macro`; nur was dort belegt ist, darf die feste Berechnung steuern (siehe README)."""
import io
import os
import time
import urllib.request

import pandas as pd

from . import config

FRED_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={}"
ECB_URL = "https://data-api.ecb.europa.eu/service/data/FM/B.U2.EUR.4F.KR.DFR.LEV?format=csvdata&startPeriod=2010-01-01"
MAX_AGE = 20 * 3600   # Sekunden bis zum erneuten Abruf


def _cache(name: str) -> str:
    return os.path.join(config.DATA_DIR, "cache", name)


def _get(url: str, name: str) -> str:
    """Text von url; bei Netzfehler der alte Zwischenspeicher, sonst Fehler."""
    path = _cache(name)
    if os.path.exists(path) and time.time() - os.path.getmtime(path) < MAX_AGE:
        return open(path, encoding="utf-8").read()
    text, last = None, None
    for attempt in range(3):   # Aussetzer der Quelle kommen vor: dreimal versuchen, mit wachsender Pause
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "planspiel-bot/1.0 (private research)"})   # FRED trennt Verbindungen, die sich als Browser ausgeben
            text = urllib.request.urlopen(req, timeout=45).read().decode()
            break
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(2 * (attempt + 1))
    if text is None:
        if os.path.exists(path):
            return open(path, encoding="utf-8").read()
        raise last
    os.makedirs(os.path.dirname(path), exist_ok=True)
    open(path, "w", encoding="utf-8").write(text)
    return text


def fred_series(sid: str) -> pd.Series:
    df = pd.read_csv(io.StringIO(_get(FRED_URL.format(sid), f"fred_{sid}.csv")), na_values=".")
    df.columns = ["date", "v"]
    df = df.dropna()
    return pd.Series(df["v"].astype(float).to_numpy(), index=pd.to_datetime(df["date"]))


def ecb_deposit_rate() -> pd.Series:
    df = pd.read_csv(io.StringIO(_get(ECB_URL, "ecb_dfr.csv")))
    return pd.Series(df["OBS_VALUE"].astype(float).to_numpy(), index=pd.to_datetime(df["TIME_PERIOD"]))


def _features(fetch) -> dict:
    """Kennzahlen als Reihen auf dem jeweiligen Veröffentlichungskalender (Lag in Tagen, wann der Wert bekannt war)."""
    t10y2y, t10y3m, baa = fetch("T10Y2Y"), fetch("T10Y3M"), fetch("BAA10Y")
    dgs10, dff, un, cpi = fetch("DGS10"), fetch("DFF"), fetch("UNRATE"), fetch("CPIAUCSL")
    un3 = un.rolling(3).mean()
    return {  # Name: (Reihe, Verzögerung in Tagen)
        "curve": (t10y2y, 0),                                       # Zinskurve 10 Jahre minus 2 Jahre, Prozentpunkte
        "curve3m": (t10y3m, 0),                                     # 10 Jahre minus 3 Monate
        "credit": (baa, 0),                                         # Baa-Unternehmensanleihen minus 10-jährige Staatsanleihe
        "credit_widening": (baa - baa.rolling(120, min_periods=60).min(), 0),   # Ausweitung gegenüber dem 120-Tage-Tief
        "y10": (dgs10, 0),
        "y10_chg63": (dgs10 - dgs10.shift(63), 0),                  # Renditeänderung über rund 3 Monate
        "dff": (dff, 0),
        "dff_chg126": (dff - dff.shift(126), 0),                    # Leitzinsänderung über rund 6 Monate
        "unrate": (un, 35),                                         # Arbeitslosenquote, erscheint ca. 5 Wochen später
        "sahm": (un3 - un3.rolling(12).min(), 35),                  # Sahm-Regel: ab 0,5 Rezessionssignal
        "cpi_yoy": (cpi.pct_change(12) * 100, 45),                  # Inflation zum Vorjahr, erscheint ca. 6 Wochen später
    }


def frame(dates, fetch=fred_series) -> pd.DataFrame:
    """Kennzahlen zu jedem Handelstag in `dates`, so wie sie an diesem Tag bekannt waren."""
    idx = pd.DatetimeIndex(dates)
    out = {}
    for name, (s, lag) in _features(fetch).items():
        s = s.dropna().copy()
        s.index = s.index + pd.Timedelta(days=lag)
        s = s[~s.index.duplicated(keep="last")].sort_index()
        out[name] = s.reindex(s.index.union(idx)).ffill().reindex(idx)
    return pd.DataFrame(out, index=idx)


# --- Warnsignale: aus dem Backtest, siehe bot/lab.py ---
def flags(m: dict) -> list:
    """Menschenlesbare Warnsignale zu einer Zeile aus frame()/snapshot()."""
    out = []
    if m.get("curve") is not None and m["curve"] < 0:
        out.append("Zinskurve invers (10 Jahre unter 2 Jahren)")
    if m.get("credit_widening") is not None and m["credit_widening"] > 0.5:
        out.append("Kreditaufschläge weiten sich stark aus")
    if m.get("y10_chg63") is not None and m["y10_chg63"] > 0.75:
        out.append("Anleiherenditen steigen schnell (über 0,75 Punkte in 3 Monaten)")
    if m.get("dff_chg126") is not None and m["dff_chg126"] > 1.0:
        out.append("Notenbank strafft (US-Leitzins über 1 Punkt in 6 Monaten gestiegen)")
    if m.get("sahm") is not None and m["sahm"] >= 0.5:
        out.append("Sahm-Regel ausgelöst (Rezessionssignal am Arbeitsmarkt)")
    return out


def snapshot(fetch=fred_series, ecb=ecb_deposit_rate) -> dict:
    """Aktuelle Makrolage für Claude. Fehlende Quellen werden übersprungen, nie ein Fehler."""
    out = {}
    try:
        row = {}
        for name, (s, lag) in _features(fetch).items():
            s = s.dropna()
            s = s[s.index <= pd.Timestamp.today().normalize() - pd.Timedelta(days=lag)]
            if len(s):
                row[name] = round(float(s.iloc[-1]), 3)
        out = {"kurve_10y_2y": row.get("curve"), "kurve_10y_3m": row.get("curve3m"), "kreditaufschlag_baa": row.get("credit"),
               "kreditaufschlag_ausweitung_120d": row.get("credit_widening"), "rendite_10y_usa": row.get("y10"),
               "rendite_10y_veraenderung_3m": row.get("y10_chg63"), "leitzins_fed": row.get("dff"),
               "leitzins_fed_veraenderung_6m": row.get("dff_chg126"), "arbeitslosenquote_usa": row.get("unrate"),
               "sahm_regel": row.get("sahm"), "inflation_usa_vorjahr_prozent": row.get("cpi_yoy"), "warnsignale": flags(row)}
    except Exception as e:  # noqa: BLE001 – Makrodaten sind Zusatz, kein Muss
        out["fehler_fred"] = str(e)[:120]
    try:
        r = ecb().dropna()
        out["leitzins_ezb_einlagesatz"] = float(r.iloc[-1])
    except Exception:  # noqa: BLE001
        pass
    try:
        de = fetch("IRLTLT01DEM156N").dropna()
        out["rendite_10y_deutschland_monatlich"] = round(float(de.iloc[-1]), 2)
    except Exception:  # noqa: BLE001
        pass
    return {k: v for k, v in out.items() if v is not None}
