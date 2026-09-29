"""Vortrainierte Zeitreihenmodelle (Chronos-Bolt, Chronos-2) als Signal: Rangkorrelation der Prognose mit der tatsächlichen Rendite nach 10 und 20 Handelstagen, gegen Momentum.
python scripts/experiment_foundation.py   (ca. 15 Minuten ohne Grafikkarte, braucht: pip install chronos-forecasting; die Gewichte lädt das Skript von Hugging Face)

60 zufällig gewählte Titel (Startwert 1) aus bot/universes.py, Kurse in Heimatwährung, Prognose aus den letzten 256 Kursen (auf den letzten Kurs = 1 normiert), Rangkorrelation je Tag,
Mittelwert und t-Wert über die Tage. Zeiträume: nach August 2025 (Chronos-2 erschien Oktober 2025, kann die Daten nicht kennen), 2023-2024 und 2018-2022 (evtl. im Training)."""
import os
import sys
import warnings

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from scipy.stats import spearmanr  # noqa: E402

from bot import universes  # noqa: E402

try:
    import torch
    from chronos import BaseChronosPipeline
except ImportError:
    raise SystemExit("Dieses Experiment braucht: pip install chronos-forecasting")
import yfinance as yf  # noqa: E402

CTX, HMAX = 256, 20
MODELS = ("amazon/chronos-bolt-small", "amazon/chronos-bolt-base", "amazon/chronos-2")


def universe():
    rng = np.random.default_rng(1)
    pick = lambda lst, n: list(rng.choice(sorted(set(lst)), size=n, replace=False))      # noqa: E731
    cand = pick(universes.DAX + universes.MDAX, 26) + pick(universes.EUROPE, 22) + pick(universes.US, 26)
    d = yf.download(cand, start="2016-01-01", interval="1d", auto_adjust=True, progress=False, group_by="ticker", threads=True)
    close = d.xs("Close", axis=1, level=1).ffill(limit=5)
    syms = [s for s in cand if s in close.columns and close[s].loc["2016-06-01":].notna().all()][:60]
    return close[syms].loc["2016-06-01":]


def tstat(a):
    a = np.asarray(a, float)
    a = a[~np.isnan(a)]
    return a.mean(), a.mean() / (a.std(ddof=1) / np.sqrt(len(a)))


def forecaster(name):
    pipe = BaseChronosPipeline.from_pretrained(name, device_map="cpu", torch_dtype=torch.float32)

    def fc(series):
        x = [torch.tensor(a, dtype=torch.float32) for a in series]
        try:
            q, _ = pipe.predict_quantiles(x, prediction_length=HMAX, quantile_levels=[0.1, 0.5, 0.9])
        except TypeError:
            q, _ = pipe.predict_quantiles(inputs=x, prediction_length=HMAX, quantile_levels=[0.1, 0.5, 0.9])
        q = q if not isinstance(q, (list, tuple)) else torch.stack([t.squeeze() for t in q])
        q = q.detach().cpu().numpy()
        return q[..., 1] if q.ndim == 3 else q
    return fc


if __name__ == "__main__":
    C = universe()
    c, idx = C.to_numpy(), C.index

    def dates(start, end, step):
        a, b = idx.searchsorted(pd.Timestamp(start)), idx.searchsorted(pd.Timestamp(end))
        return list(range(max(a, CTX + 252), min(b, len(idx) - HMAX - 1), step))
    periods = {"nach Aug. 2025": dates("2025-09-01", "2026-09-15", 5), "2023-2024": dates("2023-03-01", "2024-12-31", 5), "2018-2022": dates("2018-01-01", "2022-12-31", 10)}
    print(f"{C.shape[1]} Titel; Rangkorrelation (Mittel, t-Wert) der Prognose mit der tatsächlichen Rendite\n")
    for name in MODELS:
        fc = forecaster(name)
        for pname, ds in periods.items():
            ic10, ic20, m10, m20 = [], [], [], []
            for i in ds:
                med = fc([c[i - CTX + 1:i + 1, j] / c[i, j] for j in range(c.shape[1])])
                f10, f20 = c[i + 10] / c[i] - 1, c[i + 20] / c[i] - 1
                mom = (c[i] / c[i - 60] - 1 + c[i] / c[i - 120] - 1 + c[i - 21] / c[i - 252] - 1) / 3
                ic10.append(spearmanr(med[:, 9], f10)[0]); ic20.append(spearmanr(med[:, 19], f20)[0])
                m10.append(spearmanr(mom, f10)[0]); m20.append(spearmanr(mom, f20)[0])
            f = lambda a: "%+.3f (t=%+.1f)" % tstat(a)      # noqa: E731
            print(f"{name.split('/')[1]:18} {pname:15} 10 Tage: Modell {f(ic10)} Momentum {f(m10)} | 20 Tage: Modell {f(ic20)} Momentum {f(m20)}", flush=True)
