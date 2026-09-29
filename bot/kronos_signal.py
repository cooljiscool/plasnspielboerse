"""Kronos (github.com/shiyu-coder/Kronos, MIT): Basismodell für Kerzendaten, trainiert auf über 12 Milliarden Kerzen von 45 Börsen.

Es sagt aus Open/High/Low/Close/Volumen der letzten Handelstage die nächsten Kerzen voraus. Hier wird daraus pro Titel eine einzige Zahl:
`kronos_ret` = vorhergesagte Rendite bis zum Ende des Prognosezeitraums (Standard 10 Handelstage). Die Zahl ist unkalibriert (die Höhe stimmt
nicht, nur die Reihenfolge der Titel untereinander kann etwas aussagen) und wird nur als zusätzliches Signal genutzt, siehe README.

Optional: Ohne PyTorch und ohne den geklonten Kronos-Code läuft der Bot unverändert (`scripts/setup_kronos.sh` richtet beides ein).
Rechenzeit auf der CPU: Kronos-small etwa 0,7 s je Titel (Kontext 256, 10 Tage), Kronos-mini etwa 0,14 s."""
import json
import os
import sys
from datetime import date

import pandas as pd

from . import config

SIZES = {  # Kurzname: (Modell, Tokenizer, maximaler Kontext)
    "mini": ("Kronos-mini", "Kronos-Tokenizer-2k", 2048),
    "small": ("Kronos-small", "Kronos-Tokenizer-base", 512),
    "base": ("Kronos-base", "Kronos-Tokenizer-base", 512),
}
COLS = ["open", "high", "low", "close", "volume"]
CHUNK = 32   # Titel je Rechenlauf (begrenzt den Speicher)


def available() -> tuple:
    """(True, "") oder (False, Grund)."""
    try:
        import torch  # noqa: F401
    except ImportError:
        return False, "PyTorch fehlt (scripts/setup_kronos.sh)"
    if not os.path.exists(os.path.join(config.KRONOS_DIR, "model", "kronos.py")):
        return False, f"Kronos-Code fehlt in {config.KRONOS_DIR} (scripts/setup_kronos.sh)"
    return True, ""


class KronosSignal:
    def __init__(self, size: str = None, horizon: int = None, context: int = None, predictor=None):
        self.size = size or config.KRONOS_SIZE
        self.horizon = horizon or config.KRONOS_HORIZON
        self.context = context or config.KRONOS_CONTEXT
        self._pred = predictor   # für Tests einsetzbar

    def _predictor(self):
        if self._pred is None:
            ok, why = available()
            if not ok:
                raise RuntimeError(why)
            import torch
            sys.path.insert(0, config.KRONOS_DIR)
            from model import Kronos, KronosPredictor, KronosTokenizer
            name, tok, max_ctx = SIZES[self.size]
            torch.manual_seed(0)
            self._pred = KronosPredictor(Kronos.from_pretrained("NeoQuasar/" + name),
                                         KronosTokenizer.from_pretrained("NeoQuasar/" + tok),
                                         device="cpu", max_context=min(max_ctx, max(self.context, 64)))
        return self._pred

    def forecast(self, frames: dict) -> dict:
        """frames: {Schlüssel: DataFrame(open, high, low, close, volume) mit Datumsindex}. Titel mit zu kurzer oder lückenhafter
        Historie werden übersprungen. Gibt {Schlüssel: vorhergesagte Rendite über den Prognosezeitraum} zurück."""
        items = []
        for key, df in frames.items():
            w = df.reindex(columns=COLS).iloc[-self.context:]
            if len(w) < self.context or w[COLS[:4]].isna().any().any():
                continue
            items.append((key, w.assign(volume=w["volume"].fillna(0.0))))
        if not items:
            return {}
        pred, out = self._predictor(), {}
        for a in range(0, len(items), CHUNK):
            part = items[a:a + CHUNK]
            dfs = [w.reset_index(drop=True) for _, w in part]
            xts = [pd.Series(w.index) for _, w in part]
            yts = [pd.Series(pd.bdate_range(w.index[-1] + pd.Timedelta(days=1), periods=self.horizon)) for _, w in part]
            res = pred.predict_batch(dfs, xts, yts, pred_len=self.horizon, T=1.0, top_p=0.9,
                                     sample_count=config.KRONOS_SAMPLES, verbose=False)
            for (key, w), r in zip(part, res):
                last = float(w["close"].iloc[-1])
                out[key] = round(float(r["close"].iloc[-1]) / last - 1, 4)
        return out


def get(universe: dict, isins: list, today: date, signal: KronosSignal = None, downloader=None) -> dict:
    """{isin: kronos_ret} für die Auswahl, einmal pro Tag zwischengespeichert (Modell, Größe und Horizont gehören zum Schlüssel)."""
    signal = signal or KronosSignal()
    tag = f"{today.isoformat()}|{signal.size}|{signal.horizon}|{signal.context}"
    path = os.path.join(config.DATA_DIR, "kronos.json")
    try:
        cache = json.load(open(path))
    except (OSError, json.JSONDecodeError):
        cache = {}
    if cache.get("tag") != tag:
        cache = {"tag": tag, "items": {}}
    todo = [i for i in isins if i not in cache["items"] and universe.get(i, {}).get("yf")]
    if todo:
        from . import market
        frames = (downloader or market.download_ohlcv)([universe[i]["yf"] for i in todo], "2y")
        by_isin = {i: frames[universe[i]["yf"]] for i in todo if universe[i]["yf"] in frames}
        cache["items"].update(signal.forecast(by_isin))
        os.makedirs(config.DATA_DIR, exist_ok=True)
        json.dump(cache, open(path, "w"))
    return {i: cache["items"][i] for i in isins if i in cache["items"]}
