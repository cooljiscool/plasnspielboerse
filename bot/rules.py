"""Regelstrategie ohne KI und ohne Kosten (Momentum mit Stopps).

Ziel ist der Rang, nicht der Durchschnitt: wenige, konzentrierte Positionen in den stärksten Trends, fast voll investiert,
wenig Handel wegen der Gebühr (0,3 %, mind. 15 €). Verkauft wird nur bei klarem Grund, damit nicht ständig getauscht wird."""
from . import config

N_POSITIONS = 6          # Zielanzahl gleich gewichteter Positionen
CASH_BUFFER = 0.03       # bleibt als Reserve für Gebühren und Kursbewegung
KEEP_RANK = 12           # eine Position bleibt, solange sie unter den besten 12 Titeln liegt
STOP_LOSS = 0.12         # Verkauf, wenn der Kurs 12 % unter dem Einstand liegt
TREND_BREAK = -0.08      # Verkauf, wenn die 20-Tage-Rendite unter -8 % fällt
MAX_VOL = 0.55           # Titel mit mehr als 55 % Jahresvolatilität werden nicht neu gekauft


def score(m: dict, stars: int = 0) -> float:
    """Gewichtetes Momentum; ein kleiner Bonus für Sterntitel bedient die Nachhaltigkeitswertung."""
    return 0.5 * m["ret_60d"] + 0.35 * m["ret_20d"] + 0.15 * m["ret_5d"] + 0.01 * stars


def decide(pf: dict, universe: dict, snap: dict, total: float) -> dict:
    ranked = sorted(snap, key=lambda i: score(snap[i], universe[i].get("stars", 0)), reverse=True)
    rank = {isin: r for r, isin in enumerate(ranked)}
    orders, notes = [], []

    # 1. Verkäufe: Stop-Loss, Trendbruch oder aus dem Spitzenfeld gefallen.
    kept = 0
    for isin, pos in pf["positions"].items():
        m = snap.get(isin)
        if not m:
            kept += 1
            continue
        reason, stop = None, False
        if m["price"] <= pos["avg_price"] * (1 - STOP_LOSS):
            reason, stop = f"Stop-Loss: {m['price'] / pos['avg_price'] - 1:+.1%} zum Einstand", True
        elif m["ret_20d"] < TREND_BREAK:
            reason, stop = f"Trendbruch: 20 Tage {m['ret_20d']:+.1%}", True
        elif rank.get(isin, 10 ** 6) >= KEEP_RANK:
            reason = f"aus dem Spitzenfeld gefallen (Rang {rank.get(isin, 0) + 1})"
        if reason:
            orders.append({"action": "sell", "isin": isin, "reason": reason, "stop": stop})
        else:
            kept += 1

    # 2. Käufe: freie Plätze mit den stärksten Trends füllen.
    free = N_POSITIONS - kept
    if free > 0:
        slot = total * (1 - CASH_BUFFER) / N_POSITIONS
        for isin in ranked:
            if free == 0:
                break
            m, held = snap[isin], pf["positions"].get(isin)
            if held or m["price"] < config.MIN_PRICE_EUR or m["ret_20d"] <= 0 or m["vol_20d"] > MAX_VOL:
                continue
            orders.append({"action": "buy", "isin": isin, "amount_eur": round(slot),
                           "reason": f"Momentum Rang {rank[isin] + 1}: 60 Tage {m['ret_60d']:+.1%}, "
                                     f"20 Tage {m['ret_20d']:+.1%}, Vola {m['vol_20d']:.0%}"})
            free -= 1

    n_sell = sum(o["action"] == "sell" for o in orders)
    n_buy = len(orders) - n_sell
    view = (f"Regelstrategie (ohne KI): {kept} Positionen bleiben, {n_sell} Verkäufe, {n_buy} Käufe. "
            f"Bester Titel: {universe[ranked[0]]['name']}." if ranked else "Regelstrategie: keine Kursdaten.")
    return {"market_view": view, "orders": orders}
