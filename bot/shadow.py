"""Schattendepot: Claudes eigene Auswahl gegen die Regeln, vollautomatisch.

Claude entscheidet heute nur mit dem Regelvorschlag in der Hand. Ob er allein besser wählt, lässt sich historisch nicht prüfen (es gibt keine alten Nachrichten). Deshalb wird es
nach vorn gemessen: An jedem Handelstag wählt Claude ohne Regelvorschlag 6 Titel aus denselben Kandidaten (Papierdepot, es wird nichts gekauft). Daneben steht die Auswahl der
Regeln vom selben Tag (die 6 stärksten kaufbaren Titel) und als Maßstab der Durchschnitt aller Titel. Nach 14, 28 und 56 Tagen wird jede Gruppe mit den Kursen von heute verglichen.

Weil die täglichen Gruppen sich zeitlich überlappen, zählt für die Sicherheit nur die Zahl unabhängiger Zeitfenster (Zeitspanne geteilt durch die Haltedauer), nicht die Zahl der Tage.
Ergebnis ist ein Urteil, das der Bot selbst nutzt: Erst wenn Claudes Auswahl die Regeln sicher schlägt, darf er sie freier ergänzen (Einstellung "freiheit": auto/aus,
siehe brain.decide). Zeigt der Vergleich nichts, bleibt es bei den Regeln als Grundlage."""
import json
import math
import os
from datetime import date, datetime

from . import config, rules

HORIZONS = (14, 28, 56)   # Kalendertage
HORIZON = 14              # Haltedauer, nach der das Urteil gefällt wird (kürzer = früher ein Ergebnis in einem Spiel von nur 16 Wochen)
TOLERANCE = 7             # so viele Tage nach dem Zeitpunkt darf der Kurs noch als Ergebnis eingetragen werden
MIN_WINDOWS = 3.0         # so viele unabhängige Zeitfenster braucht das Urteil
MIN_T = 1.65              # t-Wert (einseitig etwa 95 %), ab dem Claudes Vorsprung als sicher gilt
PICKS = 6


def _path() -> str:
    return os.path.join(config.DATA_DIR, "shadow.json")


def load() -> list:
    try:
        return json.load(open(_path()))
    except (OSError, json.JSONDecodeError):
        return []


def save(rows: list) -> None:
    os.makedirs(config.DATA_DIR, exist_ok=True)
    json.dump(rows, open(_path(), "w"), ensure_ascii=False)


def rule_picks(snap: dict, universe: dict, k: int = PICKS) -> list:
    """Auswahl der Regeln: die k stärksten kaufbaren Titel nach dem Score des eingestellten Stils."""
    score = rules.active_score()
    ranked = sorted(snap, key=lambda i: score(snap[i], universe[i].get("stars", 0)), reverse=True)
    return [i for i in ranked if rules.can_buy(snap[i], "risk_on", rules.PARAMS)][:k]


def has_today(rows: list, today: date) -> bool:
    return any(r["datum"] == today.isoformat() for r in rows)


def add(rows: list, today: date, claude: dict, rule_isins: list, prices: dict) -> bool:
    """Neue Gruppe des Tages: Claudes Titel (mit Begründung), Auswahl der Regeln und alle Kurse als Maßstab. False, wenn schon eine existiert oder Angaben fehlen."""
    picks = {i: t for i, t in claude.items() if i in prices}
    rule_isins = [i for i in rule_isins if i in prices]
    if has_today(rows, today) or len(picks) < 3 or len(rule_isins) < 3:
        return False
    rows.append({"datum": today.isoformat(), "claude": {i: prices[i] for i in picks}, "begruendung": picks,
                 "regeln": {i: prices[i] for i in rule_isins}, "markt": dict(prices), "ergebnis": {}})
    return True


def _mean_return(start: dict, prices: dict):
    r = [prices[i] / p - 1 for i, p in start.items() if i in prices and p]
    return sum(r) / len(r) if r else None


def update(rows: list, prices: dict, today: date) -> int:
    """Trägt bei jeder Gruppe die Entwicklung seit dem Tag der Auswahl ein, sobald 14, 28 oder 56 Tage um sind. Gibt die Zahl neuer Ergebnisse zurück."""
    n = 0
    for r in rows:
        age = (today - datetime.fromisoformat(r["datum"]).date()).days
        for h in HORIZONS:
            if str(h) in r["ergebnis"] or not (h <= age <= h + TOLERANCE):
                continue
            res = {g: _mean_return(r[g], prices) for g in ("claude", "regeln", "markt")}
            if all(v is not None for v in res.values()):
                r["ergebnis"][str(h)] = {g: round(v, 4) for g, v in res.items()}
                n += 1
    return n


def summary(rows: list, horizon: int = HORIZON) -> dict:
    """Vergleich für eine Haltedauer: mittlere Rendite von Claude, Regeln und Markt, Vorsprung von Claude vor den Regeln, unabhängige Zeitfenster und t-Wert."""
    done = sorted(((r["datum"], r["ergebnis"][str(horizon)]) for r in rows if str(horizon) in r["ergebnis"]))
    if not done:
        return {"n": 0, "horizont_tage": horizon}
    ex = [x["claude"] - x["regeln"] for _, x in done]
    mean = sum(ex) / len(ex)
    span = (datetime.fromisoformat(done[-1][0]).date() - datetime.fromisoformat(done[0][0]).date()).days + 1
    windows = max(1.0, span / horizon)   # unabhängige Zeitfenster: die Gruppen der Tage dazwischen überlappen sich
    sd = math.sqrt(sum((e - mean) ** 2 for e in ex) / (len(ex) - 1)) if len(ex) > 1 else 0.0
    t = mean / (sd / math.sqrt(windows)) if sd > 0 else 0.0
    avg = lambda g: sum(x[g] for _, x in done) / len(done)
    return {"n": len(done), "horizont_tage": horizon, "fenster": round(windows, 1), "claude": round(avg("claude"), 4), "regeln": round(avg("regeln"), 4),
            "markt": round(avg("markt"), 4), "vorsprung_claude": round(mean, 4), "t": round(t, 2),
            "tage_claude_besser": round(sum(e > 0 for e in ex) / len(ex), 2)}


def verdict(s: dict) -> dict:
    """Urteil aus der Zusammenfassung: 'zu_frueh', 'claude_besser', 'regeln_besser' oder 'gleichauf'. Claudes Auswahl muss die Regeln UND den Markt schlagen, mit sicherem t-Wert."""
    if s.get("n", 0) == 0 or s.get("fenster", 0) < MIN_WINDOWS:
        have = s.get("fenster", 0)
        return {"urteil": "zu_frueh", "text": f"Zu früh für ein Urteil: {have:.1f} von {MIN_WINDOWS:.0f} unabhängigen Zeitfenstern ({s.get('n', 0)} ausgewertete Tage). Es bleibt bei den Regeln."}
    if s["vorsprung_claude"] > 0 and s["t"] >= MIN_T and s["claude"] >= s["markt"]:
        return {"urteil": "claude_besser", "text": f"Claudes eigene Auswahl schlägt die Regeln (+{s['vorsprung_claude'] * 100:.1f} % je {s['horizont_tage']} Tage, t = {s['t']:.1f}) und den Markt."}
    if s["vorsprung_claude"] < 0 and s["t"] <= -MIN_T:
        return {"urteil": "regeln_besser", "text": f"Die Regeln schlagen Claudes eigene Auswahl ({s['vorsprung_claude'] * 100:+.1f} % je {s['horizont_tage']} Tage, t = {s['t']:.1f}). Es bleibt bei den Regeln."}
    return {"urteil": "gleichauf", "text": f"Kein sicherer Unterschied ({s['vorsprung_claude'] * 100:+.1f} % je {s['horizont_tage']} Tage, t = {s['t']:.1f}). Es bleibt bei den Regeln."}


def report(rows: list) -> dict:
    """Vergleich über alle Haltedauern und Urteil (bei der Haltedauer HORIZON), einschließlich der Zahl der Gruppen."""
    sums = {f"nach_{h}_tagen": summary(rows, h) for h in HORIZONS}
    v = verdict(sums[f"nach_{HORIZON}_tagen"])
    return {"gruppen": len(rows), "letzte_gruppe": rows[-1]["datum"] if rows else None, **v, "vergleich": sums}


def freedom(rep: dict = None) -> bool:
    """Darf Claude freier wählen? Nur bei Einstellung auto und wenn sein Schattendepot die Regeln und den Markt sicher geschlagen hat."""
    if config.FREEDOM != "auto":
        return False
    return (rep if rep is not None else report(load())).get("urteil") == "claude_besser"


def main():
    rows = load()
    rep = report(rows)
    print(f"{rep['gruppen']} Gruppen im Schattendepot. {rep['text']}")
    for k, s in rep["vergleich"].items():
        if s["n"]:
            print(f"  {k}: {s['n']} Gruppen, Claude {s['claude'] * 100:+.1f} %, Regeln {s['regeln'] * 100:+.1f} %, Markt {s['markt'] * 100:+.1f} %, "
                  f"Vorsprung {s['vorsprung_claude'] * 100:+.1f} %, {s['fenster']} Zeitfenster, t = {s['t']}")


if __name__ == "__main__":
    main()
