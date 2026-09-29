"""Harte Risikoregeln in Code. Das LLM schlägt vor, diese Schicht entscheidet."""
import math
from datetime import date

from . import config


def portfolio_value(pf: dict, prices: dict) -> float:
    total = pf["cash"]
    for isin, pos in pf["positions"].items():
        total += pos["shares"] * prices.get(isin, pos["avg_price"])
    return total


def validate(proposed: list, pf: dict, prices: dict, universe: dict, today: date):
    """Gibt (freigegebene Orders mit ganzzahliger Stückzahl, abgelehnte mit Grund) zurück."""
    approved, rejected = [], []
    cash = pf["cash"]
    held = {i: p["shares"] for i, p in pf["positions"].items()}
    total = portfolio_value(pf, prices)

    # Verkäufe zuerst, damit freigewordenes Geld für Käufe zählt.
    ordered = sorted(proposed, key=lambda o: 0 if o.get("action") == "sell" else 1)
    for o in ordered:
        if len(approved) >= config.MAX_ORDERS_PER_RUN:
            rejected.append((o, "max. Orders pro Lauf erreicht"))
            continue
        isin, action = o.get("isin"), o.get("action")
        if isin not in universe or isin not in prices:
            rejected.append((o, "unbekanntes Wertpapier oder kein Kurs"))
            continue
        price = prices[isin]
        if action == "sell":
            have = held.get(isin, 0)
            if have <= 0:
                rejected.append((o, "nicht im Depot"))
                continue
            bought = date.fromisoformat(pf["positions"][isin]["bought"])
            if (today - bought).days < config.MIN_HOLD_DAYS and not o.get("stop"):
                rejected.append((o, "Mindesthaltedauer nicht erreicht"))
                continue
            shares = min(int(o.get("shares") or have), have)
            value = shares * price
            if value < config.MIN_ORDER_EUR and shares < have:
                rejected.append((o, "Teilverkauf zu klein (Gebühr)"))
                continue
            held[isin] = have - shares
            cash += value - config.fee(value)
            approved.append({**o, "shares": shares, "est_price": price})
        elif action == "buy":
            if price < config.MIN_PRICE_EUR:
                rejected.append((o, "Penny Stock (< 1 €)"))
                continue
            amount = float(o.get("amount_eur") or 0)
            if amount < config.MIN_ORDER_EUR:
                rejected.append((o, f"Order unter {config.MIN_ORDER_EUR:.0f} € (Gebühr)"))
                continue
            sector = universe[isin].get("sector")
            if sector and held.get(isin, 0) == 0 and sum(
                    1 for i, sh in held.items() if sh > 0 and universe.get(i, {}).get("sector") == sector
            ) >= config.MAX_PER_SECTOR:
                rejected.append((o, f"Branche {sector} bereits mit {config.MAX_PER_SECTOR} Titeln im Depot"))
                continue
            already = held.get(isin, 0) * price
            room = config.POSITION_CAP * total - already
            amount = min(amount, room, cash - config.FEE_MIN_EUR - 1)
            # Gebühr einrechnen, damit das Geld sicher reicht.
            while amount > 0 and amount + config.fee(amount) > cash:
                amount -= 100
            shares = math.floor(amount / price)
            value = shares * price
            if value < config.MIN_ORDER_EUR:
                rejected.append((o, "nach Limits (20 %-Regel/Cash) zu klein"))
                continue
            held[isin] = held.get(isin, 0) + shares
            cash -= value + config.fee(value)
            approved.append({**o, "shares": shares, "est_price": price})
        else:
            rejected.append((o, "unbekannte Aktion"))
    return approved, rejected
