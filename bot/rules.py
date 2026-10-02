"""Regelstrategie ohne KI und ohne Kosten. Zugleich Vergleichsbasis im Backtest und Rückfall, wenn die KI ausfällt.

Aufbau nach Tests in 22 Planspiel-Jahren (jeweils 1.10. bis 25.1., 2004/05 bis 2025/26; zuerst 214 Titel aus DAX, MDAX, Europa und USA in Heimatwährung,
zuletzt das amtliche Universum von 511 Titeln in Euro; siehe bot/lab.py), nicht nach Bauchgefühl:
- Ranking nach mittelfristigem Momentum: Mittel aus 60-Tage-, 120-Tage- und 12-1-Monats-Rendite. Das beste Signal von rund 20 getesteten
  (Reversal, 52-Wochen-Hoch, niedrige Volatilität, Residual-Momentum und Mischungen waren gleich gut oder schlechter).
- 6 gleich große Positionen, kaum umschichten: Gehalten wird, solange ein Titel in den oberen 70 % des Rankings bleibt (Gebühren).
- Volatilitäts-Skalierung (Daniel/Moskowitz): Ist der Markt sehr unruhig (Schwankung über 20 % pro Jahr), sinkt die investierte Quote.
  Kostete im Test keinen Rang, senkte aber den schlechtesten Fall von -12,8 % auf -9,9 %.
- Nachhaltigkeit (Parameter nh_slots, Standard 0): reserviert Plätze für Titel mit Stern; kostet Rang in der Gesamtwertung, siehe README.
- Getestet und verworfen: Trendfilter beim Kauf, Marktumfeld-Filter (DAX unter SMA200, VIX, Ampel), Trailing-Stops, enge Stopps,
  Verkauf unter SMA50, Gewichtung nach Volatilität. Sie senkten den Rang. Über PARAMS bleiben sie schaltbar.
Erwartung: Am amtlichen Universum in Euro schlug die Strategie im exakten Planspiel-Fenster 67 % zufälliger 6-Titel-Depots, bei um Wochen verschobenen Fenstern
im Mittel 61 % (im früheren, kleineren Testuniversum in Heimatwährung 81 % bzw. 63 %). Rechnet man mit dem zweiten Wert. Die Tests nutzen heutige
Indexmitglieder (zu optimistisch).
Nicht testbar (keine historischen Daten): Termine, Fundamentaldaten, Web-Recherche; sie gelten als Vorsichtsregeln."""
from . import config, signals

PARAMS = {"trend_filter": False, "rsi_filter": True, "hard_stop": True, "trailing": False, "trend_break": False,
          "sma50_sell": False, "vol_weight": False, "regime": False, "earnings_blackout": True, "vol_scale": True,
          "keep_frac": 0.7, "n_positions": 6, "min_score": None, "kronos_weight": 0.0, "nh_slots": config.NH_SLOTS, "style": config.STYLE}

# Stil "angriff" (Einstellung BOT_STYLE): 5 statt 6 Titel (mehr als 20 % je Titel sind verboten), keine Volatilitätsbremse, auch sehr schwankende Titel (bis 150 % Volatilität),
# Ranking nach Momentum plus Beta. Im Test (22 Planspiel-Jahre): Rang 72 % statt 67 %, 10 statt 7 Jahre unter den besten 10 %, aber tieferer schlechtester Fall; siehe README.
ATTACK = {"n_positions": 5, "vol_scale": False, "max_vol": 1.5}
BEHIND, BEHIND_AFTER_DAYS = 0.35, 35   # Stil "turnier": hinten liegt man ab Rang 35 % gegen Zufallsdepots, frühestens 35 Tage nach dem Start

VOL_TARGET = 0.20        # Zielschwankung des Marktes; darüber sinkt die investierte Quote
VOL_FLOOR = 0.40         # mindestens 40 % investiert
MIN_SLOT_EUR = 5500.0    # jede Position mindestens so groß (Plattform: Order mindestens 5.000 €)

CASH_FLOOR = 0.03
HARD_STOP = 0.25         # Notfall-Stopp: Verkauf, wenn der Kurs 25 % unter dem Einstand liegt
TREND_BREAK = -0.08      # nur aktiv mit PARAMS["trend_break"]
MAX_VOL = 0.55           # Titel über 55 % Jahresvolatilität werden nicht neu gekauft
RSI_MAX = 85
EARNINGS_BLACKOUT = 3    # Tage vor der Gewinnmeldung ohne Neukauf
MIN_KEEP = 12


def score(m: dict, stars: int = 0) -> float:
    """Mittelfristiges Momentum: Mittel aus 60-Tage-, 120-Tage- und 12-1-Monats-Rendite (fehlt eine, zählt die nächstkürzere).
    Der kleine Sternbonus bedient die Nachhaltigkeitswertung."""
    r120 = m.get("ret_120d", m["ret_60d"])
    return (m["ret_60d"] + r120 + m.get("mom_12_1", r120)) / 3 + 0.01 * stars


def score_attack(m: dict, stars: int = 0) -> float:
    """Stil Angriff: Mittel aus 60- und 120-Tage-Rendite plus Zuschlag für hohes Beta (Titel, die den Markt überproportional mitnehmen)."""
    return 0.5 * m["ret_60d"] + 0.5 * m.get("ret_120d", m["ret_60d"]) + 0.03 * m.get("beta", 1.0) + 0.01 * stars


def score_mom60(m: dict, stars: int = 0) -> float:
    """Stil Jackpot: nur die 60-Tage-Rendite (kurzes Momentum, sucht die heißesten Titel)."""
    return m["ret_60d"] + 0.01 * stars


# Strategie-Stile. Messwerte: `python -m bot.lab --strategien` (amtliches Universum in Euro, 22 Planspiel-Jahre, 50.000 €, Gebühren). Rang = Anteil zufälliger 6-Titel-Depots, die geschlagen werden.
STYLES = {
    "sicher": {"label": "Sicher: Momentum, 6 Titel, Volatilitätsbremse", "risiko": 2, "params": {}, "score": score,
               "text": "Standard. 6 stärkste Titel nach mittelfristigem Momentum, bei unruhigem Markt weniger investiert. Rang 69 % (früh 72 / spät 66), schlechtestes Jahr −7.598 €, bestes +20.194 €."},
    "breit": {"label": "Breit gestreut: Momentum, 8 Titel", "risiko": 2, "params": {"n_positions": 8, "vol_scale": False}, "score": score,
              "text": "Dasselbe Signal, 8 statt 6 Titel: ein einzelner Fehlgriff zählt weniger. Rang 70 % (früh 76 / spät 65), schlechtestes Jahr −6.621 €, bestes +19.626 €. Kaum Unterschied zu „sicher“."},
    "turnier": {"label": "Aufholjagd: sicher, aber hinten mehr Risiko", "risiko": 3, "params": {}, "score": score,
                "text": "Wie „sicher“, wechselt aber zu „angriff“, sobald der Bot nach 35 Tagen im geschätzten Rang unter 35 % liegt (Turnier-Logik: wer hinten liegt, hat wenig zu verlieren). Rang 68 % (früh 65 / spät 70), schlechtestes Jahr −7.598 €, bestes +21.238 €. Im Test kein messbarer Vorteil gegenüber „sicher“."},
    "angriff": {"label": "Angriff: 5 volatile Titel mit hohem Beta", "risiko": 4, "params": ATTACK, "score": score_attack,
                "text": "5 Titel, keine Volatilitätsbremse, auch sehr schwankende Titel. Rang 67 % (früh 58 / spät 75), Ø Gewinn +9.227 € gegen +5.778 € bei „sicher“, aber schlechtestes Jahr −10.260 €, bestes +56.478 €: höhere Streuung, der Rang ist nicht besser."},
    "jackpot": {"label": "Jackpot: 5 heiße Titel, nur 60-Tage-Momentum", "risiko": 5, "params": ATTACK, "score": score_mom60,
                "text": "Für die Chance auf Platz 1 bei hohem Verlustrisiko. Rang nur 61 % (früh 51 / spät 71), 10 von 22 Jahren unter den besten 10 %, aber 5 unter den schlechtesten 10 %, schlechtestes Jahr −8.469 €, bestes +33.748 €."},
}


def effective_style(P: dict = None, regime: dict = None) -> str:
    """Stil, der jetzt gilt: bei "turnier" der Angriff, wenn der Bot hinten liegt (geschätzter Rang unter BEHIND, frühestens BEHIND_AFTER_DAYS nach dem Start), sonst "sicher"."""
    style = (P or PARAMS).get("style", "sicher")
    if style == "turnier":
        r = regime or {}
        return "angriff" if r.get("rang_proxy") is not None and r.get("tage_seit_start", 0) >= BEHIND_AFTER_DAYS and r["rang_proxy"] <= BEHIND else "sicher"
    return style if style in STYLES else "sicher"


def active_score(P: dict = None, regime: dict = None):
    """Bewertungsformel des eingestellten Stils; überall dort, wo die Kandidaten gerankt werden."""
    return STYLES[effective_style(P, regime)]["score"]


def score_60_120(m: dict, stars: int = 0) -> float:
    """Frühere Formel (Vergleich im Backtest): Mittel aus 60- und 120-Tage-Rendite."""
    return 0.5 * m["ret_60d"] + 0.5 * m.get("ret_120d", m["ret_60d"]) + 0.01 * stars


def score_mix(m: dict, stars: int = 0) -> float:
    """Frühere Mischformel (Vergleich im Backtest): kurzfristige Anteile, relative Stärke, Abschläge."""
    s = 0.45 * m["ret_60d"] + 0.30 * m["ret_20d"] + 0.10 * m["ret_5d"] + 0.15 * m.get("ret_120d", m["ret_60d"])
    s += 0.25 * m.get("rel_60d", 0.0) + (0.03 if m.get("trend_up") and m.get("above_sma50") else 0.0)
    s -= 0.05 * max(0.0, (m.get("rsi14", 50) - 75) / 10) + 0.05 * max(0.0, m.get("vol_20d", 0) - 0.35)
    return s + 0.01 * stars


def can_buy(m: dict, regime_label: str = "risk_on", P: dict = None) -> bool:
    P = P or PARAMS
    if m["price"] < config.MIN_PRICE_EUR or m["vol_20d"] > P.get("max_vol", MAX_VOL) or m["ret_20d"] <= -0.10:
        return False
    if P.get("gap_stop") and m.get("ret_5d", 0.0) <= -P["gap_stop"]:
        return False   # nach einem Absturz in den letzten 5 Tagen nicht (wieder) kaufen
    if P["trend_filter"] and (m.get("above_sma50") is False or m.get("trend_up") is False):
        return False
    if P["rsi_filter"] and m.get("rsi14", 50) > RSI_MAX:
        return False
    if P["earnings_blackout"] and (0 <= m.get("days_to_earnings", 99) <= EARNINGS_BLACKOUT or m.get("event_soon")):
        return False
    if regime_label == "risk_off" and P["regime"] and m.get("rel_60d", 1.0) <= 0:
        return False
    return True


def kronos_reorder(ranked: list, snap: dict, weight: float, k: int = 15) -> list:
    """Zweite Meinung: Innerhalb der k stärksten Momentum-Titel entscheidet zu `weight` die Kronos-Prognose über die Reihenfolge.
    Titel außerhalb der k und Titel ohne Prognose bleiben unverändert (Momentum bleibt die Auswahl, Kronos sortiert nur um)."""
    top = ranked[:k]
    have = [i for i in top if "kronos_ret" in snap[i]]
    if weight <= 0 or len(have) < 5:
        return ranked
    pos = {i: r for r, i in enumerate(have)}                                          # Momentum-Rang innerhalb der Gruppe
    kr = {i: r for r, i in enumerate(sorted(have, key=lambda i: snap[i]["kronos_ret"], reverse=True))}
    blended = sorted(have, key=lambda i: (1 - weight) * pos[i] + weight * kr[i])
    slots = iter(blended)
    return [next(slots) if i in pos else i for i in top] + ranked[k:]


def trail_pct(m: dict) -> float:
    """Abstand des Trailing-Stops: 2,5 ATR, mindestens 8 %, höchstens 15 %."""
    return min(0.15, max(0.08, 2.5 * m.get("atr_pct", 0.03)))


def _regime(regime: dict = None, use: bool = True) -> dict:
    on = dict(zip(("exposure", "positions"), signals.REGIME_TABLE["risk_on"]))
    if not regime or not use:
        return {"score": "-", **(regime or {}), "label": "risk_on", **on}
    return regime


def vol_scaled(mkt_vol, n: int, capital: float) -> tuple:
    """Volatilitäts-Skalierung: (Anteil investiert, Positionszahl). Bei ruhigem Markt voll investiert."""
    if not mkt_vol:
        return signals.REGIME_TABLE["risk_on"][0], n
    exposure = min(signals.REGIME_TABLE["risk_on"][0], max(VOL_FLOOR, VOL_TARGET / mkt_vol))
    return exposure, max(2, min(n, int(exposure * capital / MIN_SLOT_EUR)))


def decide(pf: dict, universe: dict, snap: dict, total: float, regime: dict = None,
           params: dict = None, score_fn=None) -> dict:
    P = {**PARAMS, **(params or {})}
    style = effective_style(P, regime)
    P = {**P, **{k: v for k, v in STYLES[style]["params"].items() if k not in (params or {})}}   # ausdrücklich übergebene Parameter gehen vor
    score_fn = score_fn or STYLES[style]["score"]
    shown = regime or {"label": "unbekannt", "score": "-"}   # nur zur Anzeige; gesteuert wird nur mit PARAMS["regime"]
    regime = _regime(regime, P["regime"])
    n_target, exposure = P["n_positions"] or regime["positions"], regime["exposure"]
    if P["vol_scale"] and shown.get("mkt_vol_60d"):
        exposure, n_target = vol_scaled(shown["mkt_vol_60d"], n_target, total)
    ranked = sorted(snap, key=lambda i: score_fn(snap[i], universe[i].get("stars", 0)), reverse=True)
    if P.get("kronos_weight"):
        ranked = kronos_reorder(ranked, snap, P["kronos_weight"])
    rank = {isin: r for r, isin in enumerate(ranked)}
    keep_rank = max(MIN_KEEP, int(P["keep_frac"] * len(ranked)))
    orders, sold = [], set()

    # 1. Verkäufe
    for isin, pos in pf["positions"].items():
        m = snap.get(isin)
        if not m:
            continue
        price, reason, stop = m["price"], None, False
        peak = pos.get("peak") or pos["avg_price"]
        if P["hard_stop"] and price <= pos["avg_price"] * (1 - HARD_STOP):
            reason, stop = f"Notfall-Stopp: {price / pos['avg_price'] - 1:+.1%} zum Einstand", True
        elif P.get("gap_stop") and m.get("ret_1d", 0.0) <= -P["gap_stop"]:
            reason, stop = f"Kurslücke: {m['ret_1d']:+.1%} an einem Tag", True
        elif P["trailing"] and peak > pos["avg_price"] * 1.03 and price <= peak * (1 - trail_pct(m)):
            reason, stop = f"Trailing-Stop: {price / peak - 1:+.1%} vom Hoch seit Kauf", True
        elif P["trend_break"] and m["ret_20d"] < TREND_BREAK:
            reason, stop = f"Trendbruch: 20 Tage {m['ret_20d']:+.1%}", True
        elif P["sma50_sell"] and m.get("above_sma50") is False and m["ret_20d"] < 0:
            reason = "Kurs unter der 50-Tage-Linie bei fallendem Trend"
        elif rank.get(isin, 10 ** 6) >= keep_rank:
            reason = f"aus der oberen Hälfte des Rankings gefallen (Rang {rank.get(isin, 0) + 1} von {len(ranked)})"
        if reason:
            orders.append({"action": "sell", "isin": isin, "reason": reason, "stop": stop})
            sold.add(isin)

    # Zu viele Positionen für das Ziel (nur relevant, wenn n_positions/Marktumfeld sinkt): die schwächsten abbauen
    kept = [i for i in pf["positions"] if i not in sold and i in snap]
    for isin in sorted(kept, key=lambda i: rank.get(i, 10 ** 6), reverse=True)[:max(0, len(kept) - n_target)]:
        orders.append({"action": "sell", "isin": isin, "stop": False,
                       "reason": f"Positionen auf {n_target} senken (Marktumfeld {regime['label']})"})
        sold.add(isin)
    kept = [i for i in kept if i not in sold]

    # 1b. Tausch (Option "swap", Standard aus): Ein gehaltener Titel, der in der Rangliste weit zurückgefallen ist, wird durch den stärksten kaufbaren Titel ersetzt,
    # wenn dieser in der Spitze liegt. Je Lauf höchstens "max" Tausche. Die Käufe unten besetzen den frei gewordenen Platz.
    sw = P.get("swap")
    if sw and ranked:
        n_all = len(ranked)
        for _ in range(int(sw.get("max", 1))):
            weak = [i for i in kept if rank.get(i, 10 ** 6) >= sw["hold"] * n_all]
            if not weak:
                break
            worst = max(weak, key=lambda i: rank.get(i, 10 ** 6))
            secs = {}
            for i in kept:
                sec = snap[i].get("sector") or universe[i].get("sector")
                if i != worst and sec:
                    secs[sec] = secs.get(sec, 0) + 1
            def fits(c):
                m = snap[c]
                sec = m.get("sector") or universe[c].get("sector")
                return (c not in pf["positions"] and not any(o["isin"] == c for o in orders) and can_buy(m, regime["label"], P)
                        and (P.get("min_score") is None or score_fn(m, universe[c].get("stars", 0)) > P["min_score"])
                        and not (sec and secs.get(sec, 0) >= config.MAX_PER_SECTOR))
            cand = next((c for c in ranked[:max(1, int(sw["cand"] * n_all))] if fits(c)), None)
            if cand is None:
                break
            orders.append({"action": "sell", "isin": worst, "stop": False,
                           "reason": f"Tausch: Rang {rank[worst] + 1} gegen Rang {rank[cand] + 1} ({universe[cand].get('name', cand)})"})
            sold.add(worst)
            kept.remove(worst)

    # 2. Käufe: freie Plätze mit den stärksten, zulässigen Titeln füllen
    sectors = {}
    for i in kept:
        sec = snap[i].get("sector") or universe[i].get("sector")
        if sec:
            sectors[sec] = sectors.get(sec, 0) + 1
    free = n_target - len(kept)
    slot = total * min(exposure, 1 - CASH_FLOOR) / n_target
    nh_need = max(0, (P.get("nh_slots") or 0) - sum(1 for i in kept if universe.get(i, {}).get("stars")))   # Plätze, die für Titel mit Nachhaltigkeits-Stern reserviert sind

    def consider(isin) -> bool:
        nonlocal free
        m = snap[isin]
        if isin in pf["positions"] or any(o["isin"] == isin for o in orders) or not can_buy(m, regime["label"], P):
            return False
        if P.get("min_score") is not None and score_fn(m, universe[isin].get("stars", 0)) <= P["min_score"]:
            return False   # absolutes Momentum: nur kaufen, wenn der Score über der Schwelle liegt
        sec = m.get("sector") or universe[isin].get("sector")
        if sec and sectors.get(sec, 0) >= config.MAX_PER_SECTOR:
            return False
        weight = min(1.25, max(0.75, 0.30 / max(m["vol_20d"], 0.05))) if P["vol_weight"] else 1.0
        order = {"action": "buy", "isin": isin, "amount_eur": round(slot * weight),
                 "reason": f"Momentum Rang {rank[isin] + 1} von {len(ranked)}: 60 Tage {m['ret_60d']:+.1%}"
                           + (f", 120 Tage {m['ret_120d']:+.1%}" if "ret_120d" in m else "")
                           + (", Nachhaltigkeits-Stern" if universe[isin].get("stars") and P.get("nh_slots") else "")}
        if P["trailing"]:
            order["stop_price"] = round(m["price"] * (1 - trail_pct(m)), 2)
        orders.append(order)
        if sec:
            sectors[sec] = sectors.get(sec, 0) + 1
        free -= 1
        return True

    for isin in ranked:   # zuerst die reservierten Nachhaltigkeitsplätze mit den stärksten Sterntiteln
        if free <= 0 or nh_need <= 0:
            break
        if universe[isin].get("stars") and consider(isin):
            nh_need -= 1
    for isin in ranked:
        if free <= 0:
            break
        consider(isin)

    n_sell = sum(o["action"] == "sell" for o in orders)
    view = (f"Regelstrategie (ohne KI): Momentum 60/120 Tage, {len(kept)} Positionen bleiben, {n_sell} Verkäufe, "
            f"{len(orders) - n_sell} Käufe. Marktumfeld {shown['label']} ({shown['score']}), fließt nicht in die Regeln ein."
            if ranked else "Regelstrategie: keine Kursdaten.")
    return {"market_view": view, "orders": orders}
