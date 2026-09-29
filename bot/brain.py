"""Entscheidungsschicht: Claude bekommt Depot + Marktdaten und liefert strukturierte Orders."""
import json
from datetime import date

import anthropic

from . import config

SYSTEM = f"""Du bist der Portfoliomanager eines Teams im Planspiel Börse der Sparkassen (virtuelles Depot, echte Kurse).
Ziel: maximaler Rang in der Depotgesamtwertung bis {config.GAME_END} (Zwischenwertung {config.INTERIM_EVAL}) und
zugleich in der Nachhaltigkeitswertung (nur Titel mit Stern: 1 = Deka-Kriterien, 2 = Global Challenges Index).

Regeln der Plattform: Gebühr {config.FEE_RATE:.1%} vom Kurswert, mind. {config.FEE_MIN_EUR:.0f} EUR pro Order. Max. 20 % des Depotwerts pro
Wertpapier, kein Leerverkauf, keine Hebelprodukte, keine Kredite. Mindestens {config.MIN_BUY_ORDERS} ausgeführte Käufe bis {config.BUY_DEADLINE}.

Leitlinien:
- Gewertet wird der Rang, nicht der Erwartungswert: Konzentriere dich auf 5-7 überzeugte Positionen, bleibe fast voll investiert (Cash < 5 %).
- Jede Runde Kauf+Verkauf kostet ca. 0,6 %. Handle nur bei klarem Vorteil, keine Kleinorders (< {config.MIN_ORDER_EUR:.0f} EUR).
- Bevorzuge Titel mit Momentum und Nachrichtenlage, achte auf Volatilität. Bevorzuge Sterntitel bei gleicher Qualität.
- Hältst du eine Position, setze Verluste mit einem Stop (stop_price, gilt bis 14 Tage auf der Plattform) begrenzt, z. B. 10-12 % unter Kurs.
- Nichtstun ist eine gültige Entscheidung: gib dann eine leere Orderliste zurück.
Antworte ausschließlich über das Tool submit_orders."""

TOOL = {
    "name": "submit_orders",
    "description": "Gibt die Marktsicht und die Orders für diesen Lauf ab.",
    "input_schema": {
        "type": "object",
        "properties": {
            "market_view": {"type": "string", "description": "Kurze Begründung der Gesamtlage"},
            "orders": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "action": {"type": "string", "enum": ["buy", "sell"]},
                        "isin": {"type": "string"},
                        "amount_eur": {"type": "number", "description": "nur Kauf: Zielbetrag in EUR"},
                        "shares": {"type": "integer", "description": "nur Verkauf: Stückzahl, leer = alles"},
                        "stop_price": {"type": "number", "description": "optional: Stop-Loss-Kurs nach Kauf"},
                        "reason": {"type": "string"},
                    },
                    "required": ["action", "isin", "reason"],
                },
            },
        },
        "required": ["market_view", "orders"],
    },
}


def decide(pf: dict, universe: dict, snap: dict, news: dict, today: date, total: float) -> dict:
    ranked = sorted(snap, key=lambda i: snap[i]["ret_60d"], reverse=True)
    context = {
        "heute": today.isoformat(),
        "tage_bis_ende": (config.GAME_END - today).days,
        "depotgesamtwert": round(total, 2),
        "cash": round(pf["cash"], 2),
        "ausgefuehrte_kaeufe": pf.get("buy_orders_executed", 0),
        "positionen": {
            i: {**p, "name": universe[i]["name"], "kurs": snap.get(i, {}).get("price")}
            for i, p in pf["positions"].items()
        },
        "kandidaten": {
            i: {"name": universe[i]["name"], "sterne": universe[i].get("stars", 0), **snap[i]}
            for i in ranked
        },
        "schlagzeilen": news,
    }
    client = anthropic.Anthropic()
    resp = client.messages.create(
        model=config.MODEL,
        max_tokens=4000,
        system=SYSTEM,
        tools=[TOOL],
        tool_choice={"type": "tool", "name": "submit_orders"},
        messages=[{"role": "user", "content": json.dumps(context, ensure_ascii=False)}],
    )
    for block in resp.content:
        if block.type == "tool_use":
            return block.input
    return {"market_view": "keine Antwort", "orders": []}
