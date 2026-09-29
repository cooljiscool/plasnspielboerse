"""Gedächtnis: die letzten ausgeführten Orders mit dem, was seither aus ihnen wurde.

Idee aus TradingAgents (Erinnerung an frühere Entscheidungen samt Ergebnis, die in die nächste Entscheidung einfließt).
Sie wird nur als Information an Claude gegeben, damit systematische Fehler auffallen, etwa Verkäufe, nach denen der Kurs weiter stieg."""
import glob
import json
import os


def recent(log_dir: str, snap: dict, n: int = 10) -> list:
    """Neueste zuerst: Datum, Aktion, Titel, Quelle, Kurs bei der Order und Kursänderung seither (bei Verkäufen: Kurs seit dem Verkauf)."""
    out = []
    for path in sorted(glob.glob(os.path.join(log_dir, "*.json")), reverse=True):
        try:
            log = json.load(open(path))
        except (OSError, json.JSONDecodeError):
            continue
        for o in log.get("approved", []):
            price0, now = o.get("est_price"), snap.get(o["isin"], {}).get("price")
            if not price0 or not now:
                continue
            change = now / price0 - 1
            out.append({"datum": log["time"][:10], "aktion": "Kauf" if o["action"] == "buy" else "Verkauf",
                        "titel": o.get("name", o["isin"]), "quelle": log.get("provider") or "?",
                        "kurs_bei_order": price0,
                        ("rendite_seither" if o["action"] == "buy" else "kurs_seit_verkauf"): round(change, 4)})
            if len(out) >= n:
                return out
    return out
