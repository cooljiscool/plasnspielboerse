"""Gewichtung der 6 Positionen: gleich (Standard) gegen inverse Schwankung, Minimum-Varianz, HRP und Gewichtung nach Momentum.   python scripts/experiment_weights.py   (ca. 3 Minuten)

Gewichte gelten nur für die Käufe eines Laufs (zu Beginn also für alle 6), zwischen dem 0,6- und 1,17-fachen eines gleichen Anteils (die 19-%-Grenze der Risikoschicht).
Kovarianz aus den letzten 250 Handelstagen. Testuniversum: die 214 Titel aus bot/universes.py in Heimatwährung."""
import os
import sys
import warnings

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from scipy.cluster.hierarchy import leaves_list, linkage  # noqa: E402
from scipy.spatial.distance import squareform  # noqa: E402

from bot import backtest as bt, config, lab, universes  # noqa: E402

H = lab.load_history(os.path.join(config.DATA_DIR, "cache", "history.pkl"))
d = bt.Data.from_frames(H["close"], H["high"], H["low"], H["open"], list(dict.fromkeys(universes.ALL)))
W = lab.planspiel_windows(d.dates)
PX = d.fr.a["price"]
LO, HI = 0.6, 1.17


def bar_of(snap):
    return next(i for i, sn in d._snaps.items() if sn is snap)


def rets(cols, i, n=250):
    p = PX[max(0, i - n):i + 1][:, [d.fr.col_index[c] for c in cols]]
    return np.nan_to_num(p[1:] / p[:-1] - 1, nan=0.0)


def inv_vol(R, mom):
    v = R.std(0) + 1e-9
    return (1 / v) / (1 / v).sum()


def min_var(R, mom):
    S = np.cov(R.T)
    S = 0.7 * S + 0.3 * np.diag(np.diag(S))          # geschrumpfte Kovarianz
    w = np.clip(np.linalg.solve(S, np.ones(len(S))), 0, None)
    return w / w.sum() if w.sum() > 0 else np.ones(len(S)) / len(S)


def hrp(R, mom):
    S, C = np.cov(R.T), np.corrcoef(R.T)
    order = list(leaves_list(linkage(squareform(np.sqrt(np.clip((1 - C) / 2, 0, 1)), checks=False), "single")))
    w, clusters = pd.Series(1.0, index=order), [order]

    def var(idx):
        sub = S[np.ix_(idx, idx)]
        iv = 1 / np.diag(sub)
        iv /= iv.sum()
        return float(iv @ sub @ iv)
    while clusters:
        clusters = [c[k:m] for c in clusters for k, m in ((0, len(c) // 2), (len(c) // 2, len(c))) if len(c) > 1]
        for i in range(0, len(clusters), 2):
            a, b = clusters[i], clusters[i + 1]
            alpha = 1 - var(a) / (var(a) + var(b))
            w[a] *= alpha
            w[b] *= 1 - alpha
    out = np.zeros(len(order))
    out[w.index.to_numpy()] = w.to_numpy()
    return out / out.sum()


def by_momentum(R, mom):
    x = np.asarray(mom, float)
    x = x - x.min() + 0.05 * (x.max() - x.min() + 1e-9)
    return x / x.sum()


def weighted(method):
    base = lab.make("mom_blend", keep_frac=0.7, exposure=lab.mktvol_exposure(0.20, 0.4))

    def strat(pf, uni, snap, total, regime=None):
        out = base(pf, uni, snap, total, regime)
        buys = [o for o in out["orders"] if o["action"] == "buy"]
        if len(buys) < 2:
            return out
        cols = [o["isin"] for o in buys]
        mom = [(snap[c]["ret_60d"] + snap[c].get("ret_120d", snap[c]["ret_60d"]) + snap[c].get("mom_12_1", snap[c].get("ret_120d", snap[c]["ret_60d"]))) / 3 for c in cols]
        n = len(buys)
        m = np.clip(method(rets(cols, bar_of(snap)), mom) * n, LO, HI)
        for _ in range(5):
            m = np.clip(m * n / m.sum(), LO, HI)
        for o, k in zip(buys, m):
            o["amount_eur"] = round(o["amount_eur"] * float(k))
        return out
    return strat


def show(name, strat):
    df = lab.evaluate(d, W, strat)
    s, sp = lab.summarize(df), lab.split_summary(df)
    print(f"{name:42} Median {s['median']*100:+5.1f}%  schlechtestes Jahr {s['worst']*100:+6.1f}%  Rang {s['pct']*100:3.0f}% (früh {sp['früh']['pct']*100:3.0f}, spät {sp['spät']['pct']*100:3.0f})", flush=True)


if __name__ == "__main__":
    show("gleich gewichtet (Standard)", lab.make("mom_blend", keep_frac=0.7, exposure=lab.mktvol_exposure(0.20, 0.4)))
    for name, fn in (("inverse Schwankung", inv_vol), ("Minimum-Varianz", min_var), ("HRP (hierarchische Risikoparität)", hrp), ("nach Momentum", by_momentum)):
        show(name, weighted(fn))
