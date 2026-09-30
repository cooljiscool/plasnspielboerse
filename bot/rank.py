"""Geschätzter Rang gegen zufällige Depots: Ersatz für die Rangliste, die der Bot nicht kennt.

Wie im Backtest (bot/backtest.py, random_portfolios): Anteil zufällig zusammengestellter 6-Titel-Depots (Kaufen und Halten seit dem Start), deren Rendite das eigene Depot übertrifft.
Es ist eine Näherung für die anderen Teams; sie zeigt, ob man vorn oder hinten liegt, ohne die echte Rangliste zu brauchen. Der Stil "turnier" nutzt sie, um hinten mehr Risiko einzugehen."""
import numpy as np


def proxy(p0, p1, my_return: float, n: int = 300, k: int = 6, seed: int = 7) -> float:
    """p0, p1: Kurse aller Titel zu Beginn und heute (gleiche Reihenfolge, NaN = kein Kurs). Gibt den Anteil der Zufallsdepots zurück, die schlechter abschneiden als `my_return`."""
    p0, p1 = np.asarray(p0, dtype=float), np.asarray(p1, dtype=float)
    ok = np.where(~np.isnan(p0) & ~np.isnan(p1) & (p0 > 0))[0]
    if len(ok) < k:
        return 0.5
    r = p1[ok] / p0[ok] - 1
    rng = np.random.default_rng(seed)
    rets = np.array([r[rng.choice(len(ok), size=k, replace=False)].mean() for _ in range(n)])
    return float((rets < my_return).mean())
