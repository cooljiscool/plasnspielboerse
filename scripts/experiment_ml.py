"""Schlägt ein Gradient-Boosting-Modell (LightGBM) auf denselben Kennzahlen das Momentum?   python scripts/experiment_ml.py   (ca. 6 Minuten, braucht: pip install lightgbm scikit-learn)

Walk-forward: Für jedes Planspiel-Jahr ab 2007 wird ein Modell nur mit Daten trainiert, deren 80-Tage-Ergebnis vor dem Start des Jahres feststand (kein Blick in die Zukunft).
Ziel des Modells: Querschnitts-Rang der 80-Tage-Rendite. Merkmale: Rendite über 5 bis 250 Tage, 12-1-Monats-Momentum, Abstand zu Durchschnittslinien, Volatilität, Abstand zu Hoch und Tief,
Beta, Residual-Momentum u. a. (28), jeweils als Rang unter allen Titeln des Tages. Geprüft wird in der Strategie selbst (bot/lab.py), nicht nur an der Rangkorrelation.
Testuniversum: die 214 Titel aus bot/universes.py in Heimatwährung (Ausgangswert Momentum: Rang 78 % in den 19 Fenstern)."""
import os
import sys
import warnings

import numpy as np

warnings.filterwarnings("ignore")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from bot import backtest as bt, config, lab, universes  # noqa: E402

try:
    import lightgbm as lgb
    from sklearn.linear_model import Ridge
except ImportError:
    raise SystemExit("Dieses Experiment braucht: pip install lightgbm scikit-learn")

HZ, STEP, MIN_TRAIN_YEARS = 80, 5, 3
H = lab.load_history(os.path.join(config.DATA_DIR, "cache", "history.pkl"))
d = bt.Data.from_frames(H["close"], H["high"], H["low"], H["open"], list(dict.fromkeys(universes.ALL)))
W = lab.planspiel_windows(d.dates)
close = H["close"].sort_index().ffill(limit=5)[d.cols]
high = H["high"].sort_index().ffill(limit=5)[d.cols]
low = H["low"].sort_index().ffill(limit=5)[d.cols]
daily = close / close.shift(1) - 1
mkt = daily.mean(axis=1)


def features():
    f = {f"ret_{k}": close / close.shift(k) - 1 for k in (5, 10, 20, 40, 60, 90, 120, 180, 250)}
    f["mom_12_1"] = close.shift(21) / close.shift(252) - 1
    for k in (10, 20, 50, 100, 200):
        f[f"ma_{k}"] = close / close.rolling(k).mean() - 1
    f["sma50_200"] = close.rolling(50).mean() / close.rolling(200).mean() - 1
    for k in (20, 60, 120):
        f[f"vol_{k}"] = daily.rolling(k).std() * np.sqrt(252)
    f["dist_hi"] = close / close.rolling(252, min_periods=120).max() - 1
    f["dist_lo"] = close / close.rolling(252, min_periods=120).min() - 1
    f["range_pos20"] = (close - low.rolling(20).min()) / (high.rolling(20).max() - low.rolling(20).min())
    f["max_ret20"], f["min_ret20"], f["skew60"] = daily.rolling(20).max(), daily.rolling(20).min(), daily.rolling(60).skew()
    beta = daily.rolling(120).cov(mkt).div(mkt.rolling(120).var(), axis=0)
    f["beta"] = beta
    f["rel60"] = f["ret_60"].sub((1 + mkt).rolling(60).apply(np.prod, raw=True) - 1, axis=0)
    f["resid120"] = f["ret_120"].sub(beta.mul((1 + mkt).rolling(120).apply(np.prod, raw=True) - 1, axis=0))
    return f


F = features()
names = list(F)
X = np.stack([v.rank(axis=1, pct=True).to_numpy(dtype=np.float32) for v in F.values()], axis=2)     # (Tage, Titel, Merkmale), Rang je Tag
Y = (close.shift(-HZ) / close - 1).rank(axis=1, pct=True).to_numpy(dtype=np.float32)
SMALL = [names.index(k) for k in ("ret_60", "ret_120", "mom_12_1", "ma_200", "dist_hi", "vol_60", "beta", "ret_20")]
mom_all = (F["ret_60"] + F["ret_120"] + F["mom_12_1"]).to_numpy() / 3


def rows(ts, cols):
    xs, ys = [], []
    for t in ts:
        x, y = X[t][:, cols], Y[t]
        ok = (~np.isnan(y)) & ((~np.isnan(x)).sum(1) >= len(cols) - 3)
        xs.append(x[ok]); ys.append(y[ok])
    return np.concatenate(xs), np.concatenate(ys)


def predict(kind, s, e):
    ts = list(range(255, s - HZ - 1, STEP))
    if len(ts) * STEP < MIN_TRAIN_YEARS * 252:
        return None
    cols = SMALL if kind == "lgbm_klein" else list(range(len(names)))
    xtr, ytr = rows(ts, cols)
    if kind == "ridge":
        m = Ridge(alpha=100.0).fit(np.nan_to_num(xtr, nan=0.5), ytr)
        fn = lambda x: m.predict(np.nan_to_num(x, nan=0.5))      # noqa: E731
    else:
        params = dict(n_estimators=250, learning_rate=0.03, num_leaves=15, min_child_samples=400, colsample_bytree=0.7, reg_lambda=10.0) if kind == "lgbm" else \
            dict(n_estimators=200, learning_rate=0.03, num_leaves=7, min_child_samples=800, colsample_bytree=0.8, reg_lambda=20.0)
        m = lgb.LGBMRegressor(subsample=0.7, subsample_freq=1, verbose=-1, n_jobs=4, random_state=1, **params).fit(xtr, ytr)
        fn = m.predict
    out = np.full(X.shape[:2], np.nan, dtype=np.float32)
    for t in range(s, e + 1):
        out[t] = fn(X[t][:, cols])
    return out


EXP = lab.mktvol_exposure(0.20, 0.4)


def show(name, df, years):
    s = lab.summarize(df); sp = lab.split_summary(df, split_year=(years[0] + years[-1]) // 2)
    print(f"{name:46} Median {s['median']*100:+5.1f}%  schlechtestes Jahr {s['worst']*100:+6.1f}%  Rang {s['pct']*100:3.0f}% (früh {sp['früh']['pct']*100:3.0f}, spät {sp['spät']['pct']*100:3.0f})", flush=True)


def inject(preds, mode, k=15, weight=1.0):
    d._snaps = {}
    idx = {c: n for n, c in enumerate(d.cols)}
    for y, (s, e, p) in preds.items():
        for i in range(s, e + 1):
            snap = d.snap(i)
            ids = list(snap)
            mom = np.array([mom_all[i, idx[c]] for c in ids])
            ml = np.nan_to_num(np.array([p[i, idx[c]] for c in ids]), nan=-1)
            top = np.argsort(-mom)[:k]
            rm, rl = mom[top].argsort().argsort() / (k - 1), ml[top].argsort().argsort() / (k - 1)
            for n, c in enumerate(ids):
                snap[c]["_ml"], snap[c]["_mom"] = float(ml[n]), float(mom[n])
            for pos, n in enumerate(top):
                snap[ids[n]]["_re"] = 1000.0 + (1 - weight) * rm[pos] + weight * rl[pos]


if __name__ == "__main__":
    base = lab.make("mom_blend", keep_frac=0.7, exposure=EXP)
    preds = {kind: {} for kind in ("lgbm", "lgbm_klein", "ridge")}
    for kind in preds:
        for y, s, e in W:
            p = predict(kind, s, e)
            if p is not None:
                preds[kind][y] = (s, e, p)
    years = sorted(preds["lgbm"])
    Wm = [w for w in W if w[0] in years]
    print(f"Walk-forward, Testjahre {years[0]} bis {years[-1]} ({len(Wm)} Fenster); Rang = Anteil zufälliger 6-Titel-Depots, die geschlagen werden\n")
    show("Momentum (Standard)", lab.evaluate(d, Wm, base), years)
    for kind, label in (("lgbm", "LightGBM, 28 Merkmale"), ("lgbm_klein", "LightGBM, 8 Merkmale"), ("ridge", "Ridge-Regression, 28 Merkmale")):
        inject(preds[kind], "rang")
        show(f"{label}: reiner ML-Rang", lab.evaluate(d, Wm, lab.make(lambda m, s=0: m.get("_ml", -1.0), keep_frac=0.7, exposure=EXP)), years)
        if kind != "ridge":
            for weight in (0.5, 1.0):
                inject(preds[kind], "neu", weight=weight)
                show(f"{label}: Top 15 des Momentum neu sortiert ({weight})", lab.evaluate(d, Wm, lab.make(lambda m, s=0: m.get("_re", m.get("_mom", -1.0)), keep_frac=0.7, exposure=EXP)), years)
