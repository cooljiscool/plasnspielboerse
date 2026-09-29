"""Währungsumrechnung in Euro.

Das Planspiel handelt alle Titel in Euro (Stuttgart, Wien, Luxemburg) und wertet in Euro. Yahoo liefert die Kurse in der Heimatwährung: US-Aktien in Dollar, schwedische in Kronen,
britische in Pence. Für Signale, Stückzahlen und Depotwert zählt der Euro-Kurs: Fällt der Dollar um 5 %, verliert eine US-Aktie für ein Team im Euro-Raum 5 %, auch wenn sie in Dollar
unverändert bleibt. Deshalb werden alle Kurse gleich nach dem Laden mit dem Tageskurs der jeweiligen Währung in Euro umgerechnet (Yahoo-Reihen "EURUSD=X" usw.: Einheiten der
Währung je Euro). Ohne Wechselkurs bleibt der Titel ohne Kurs und wird ignoriert, statt mit einem falschen Kurs zu laufen."""
import os
import pickle

import pandas as pd

from . import config

EUR = "EUR"
SUBUNITS = {"GBp": ("GBP", 100.0), "GBX": ("GBP", 100.0), "ZAc": ("ZAR", 100.0), "ILA": ("ILS", 100.0)}   # Pence usw.: Hundertstel der Hauptwährung
SUFFIX_CURRENCY = {".DE": "EUR", ".F": "EUR", ".SG": "EUR", ".PA": "EUR", ".AS": "EUR", ".MI": "EUR", ".MC": "EUR", ".VI": "EUR", ".HE": "EUR", ".BR": "EUR",
                   ".LS": "EUR", ".IR": "EUR", ".AT": "EUR", ".ST": "SEK", ".CO": "DKK", ".OL": "NOK", ".SW": "CHF", ".L": "GBp", ".TO": "CAD", ".WA": "PLN", ".T": "JPY"}


def infer_currency(symbol: str) -> str:
    """Währung aus dem Börsenkürzel eines Yahoo-Symbols: ohne Endung US-Dollar, sonst nach der Endung. Unbekannte Endungen ergeben None (Titel wird ignoriert)."""
    if "." not in symbol:
        return "USD"
    return SUFFIX_CURRENCY.get("." + symbol.rsplit(".", 1)[1].upper())


def rate_symbol(currency: str) -> str:
    return f"EUR{SUBUNITS.get(currency, (currency, 1))[0]}=X"


def _cache_path() -> str:
    return os.path.join(config.DATA_DIR, "cache", "fx_rates.pkl")


def download_rates(currencies, period: str = None, start: str = None, fetch=None) -> pd.DataFrame:
    """Tageskurse (Einheiten je Euro), eine Spalte je Hauptwährung. Bei Ausfall der Quelle dient der zuletzt gespeicherte Stand (höchstens 7 Tage alt); sonst Fehler."""
    need = sorted({SUBUNITS.get(c, (c, 1))[0] for c in currencies if c and c != EUR})
    if not need:
        return pd.DataFrame()
    syms = [rate_symbol(c) for c in need]
    try:
        if fetch:
            raw = fetch(syms)
        else:
            import yfinance as yf
            kw = {"start": start} if start else {"period": period or "14mo"}
            d = yf.download(syms, interval="1d", auto_adjust=False, progress=False, group_by="ticker", threads=True, **kw)
            raw = pd.DataFrame({s: (d[s]["Close"] if isinstance(d.columns, pd.MultiIndex) else d["Close"]) for s in syms})
        rates = raw.rename(columns=dict(zip(syms, need))).sort_index().dropna(how="all").ffill(limit=5)
        missing = [c for c in need if c not in rates.columns or rates[c].dropna().empty]
        if missing:
            raise RuntimeError("keine Wechselkurse für " + ", ".join(missing))
        os.makedirs(os.path.dirname(_cache_path()), exist_ok=True)
        pickle.dump(rates, open(_cache_path(), "wb"))
        return rates
    except Exception:
        try:
            if os.path.exists(_cache_path()) and (pd.Timestamp.now().timestamp() - os.path.getmtime(_cache_path())) < 7 * 86400:
                cached = pickle.load(open(_cache_path(), "rb"))
                if all(c in cached.columns for c in need):
                    return cached
        except Exception:  # noqa: BLE001
            pass
        raise


def convert(frame: pd.DataFrame, currencies: dict, rates: pd.DataFrame) -> pd.DataFrame:
    """Rechnet jede Spalte von `frame` (Kurse in der Heimatwährung) mit dem Tageskurs in Euro um. `currencies`: {Spalte: Währung}. Spalten ohne Eintrag (Indizes)
    bleiben unverändert, Spalten ohne Wechselkurs werden leer (kein Kurs statt falschem Kurs)."""
    out = frame.copy()
    for col in frame.columns:
        ccy = currencies.get(col)
        if not ccy or ccy == EUR:
            continue
        base, div = SUBUNITS.get(ccy, (ccy, 1.0))
        if base not in rates.columns:   # auch "?" (unbekannte Währung)
            out[col] = float("nan")
            continue
        r = rates[base].reindex(frame.index.union(rates.index)).sort_index().ffill(limit=5).reindex(frame.index)
        out[col] = frame[col] / div / r
    return out
