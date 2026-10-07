"""Statusbericht: ein Textblock zum Kopieren, der den Zustand des Bots auf einen Blick zeigt (Läufe, Depot, Auffälligkeiten). Enthält nie Zugangsdaten, nur ob sie gesetzt sind."""
import glob
import json
import os
import shutil
import subprocess
from collections import Counter
from datetime import datetime

from .runner import TZ

KINDS = {"run": "Lauf", "selftest": "Selbsttest", "testorder": "Test-Order", "universe": "Wertpapierliste"}
DEPOTS = {"test": "Test-Depot", "echt": "Wettbewerbsdepot", "lokal": "Trockenlauf"}


def _eur(x) -> str:
    return f"{x:,.0f} €".replace(",", ".")


def _when(iso) -> str:
    try:
        d = datetime.fromisoformat(iso)
        return d.astimezone(TZ).strftime("%d.%m. %H:%M") if d.tzinfo else d.strftime("%d.%m. %H:%M")
    except (TypeError, ValueError):
        return "?"


def _version(base: str) -> str:
    try:
        out = subprocess.run(["git", "-C", base, "log", "-1", "--format=%h %s"], capture_output=True, text=True, timeout=3)
        return out.stdout.strip() or "unbekannt"
    except Exception:  # noqa: BLE001 – ohne git im Container
        return "unbekannt"


def _logs(log_dir: str, n: int) -> list:
    out = []
    for p in sorted(glob.glob(os.path.join(log_dir, "*.json")))[-n:]:
        try:
            out.append(json.load(open(p)))
        except (OSError, json.JSONDecodeError):
            continue
    return out


def build(store, runner, base: str, log_dir: str, now: datetime = None) -> str:
    now = now or datetime.now(TZ)
    s = store.settings()
    st = runner.status()
    hist = store._read("run_history.json", [])
    logs = _logs(log_dir, 60)
    last = logs[-1] if logs else None
    warn, lines = [], []
    add = lines.append

    add(f"STATUSBERICHT {now.strftime('%d.%m.%Y %H:%M')} (Berliner Zeit)")
    add(f"Software: {_version(base)}")
    add("")
    add("EINSTELLUNGEN")
    add(f"Modus: {'LIVE' if s['live'] else 'Trockenlauf'} | Depot: {DEPOTS.get(s['depot'], s['depot'])} | Stil: {s['style']} | Claude-Freiheit: {s['freiheit']}")
    add(f"Entscheidung: {s['provider']} ({s['model']}) | Recherche: {'an' if s['research'] else 'aus'} | Sternplätze: {s['nh_slots']}")
    add(f"Zeitplan: {'AN' if s['enabled'] else 'AUS'} {', '.join(s['times'])} (Mo–Fr)" + (f" | nächster Lauf: {_when(st['next_run'])}" if st.get("next_run") else ""))
    have = store.secret_status()
    add("Zugangsdaten gesetzt: " + ", ".join(f"{k} {'ja' if v else 'NEIN'}" for k, v in have.items()))
    if s["live"] and not (have["PSB_USER"] and have["PSB_PASSWORD"]):
        warn.append("Live-Modus, aber Planspiel-Zugangsdaten fehlen")
    if s["live"] and s["depot"] == "echt":
        add("Achtung: Orders gehen ins WETTBEWERBSDEPOT (zählt für den Rang)")

    add("")
    add("LETZTE VORGÄNGE (neueste zuerst)")
    if st.get("running"):
        add(f"Es läuft gerade: {KINDS.get((st.get('last') or {}).get('kind'), '?')} seit {_when((st.get('last') or {}).get('start'))}")
    for h in reversed(hist[-12:]):
        code = h.get("code")
        res = "läuft" if h.get("end") is None else ("ok" if code == 0 else ("abgebrochen" if (code or 0) < 0 else f"FEHLER (Code {code})"))
        where = f" {DEPOTS.get(h.get('depot'), '')}" if (h.get("live") or h.get("kind") == "testorder") and h.get("depot") else ""
        add(f"- {_when(h.get('start'))} {KINDS.get(h.get('kind'), h.get('kind'))}{' live' if h.get('live') else ''}{where}: {res}")
        if h.get("tail") and code not in (0, None):
            add("    " + h["tail"].replace("\n", "\n    "))
    if not hist:
        add("(noch keine aufgezeichnet; die Aufzeichnung beginnt mit dem nächsten Vorgang)")
    failed = [h for h in hist if h.get("end") and h.get("code") not in (0, None) and (h.get("code") or 0) > 0]
    if failed:
        warn.append(f"{len(failed)} fehlgeschlagene Vorgänge in der Aufzeichnung, zuletzt {_when(failed[-1].get('start'))}")

    add("")
    add("DEPOT (nach dem letzten Lauf)")
    if last:
        add(f"Lauf {_when(last.get('time'))} | {DEPOTS.get(last.get('depot'), last.get('depot'))}{' live' if last.get('live') else ''} | Stil {last.get('stil')}")
        tot, cash = last.get("total_after"), last.get("cash")
        add(f"Gesamtwert {_eur(tot)} ({tot / 50000 - 1:+.1%} gegen 50.000 €) | Bargeld {_eur(cash)} ({cash / tot:.0%})")
        same = [e for e in logs if e.get("depot") == last.get("depot") and e.get("total_after") is not None]
        if len(same) > 1:
            pts = same[-10:]
            add("Verlauf: " + " → ".join(f"{_when(e['time'])} {_eur(e['total_after'])}" for e in pts[::max(1, len(pts) // 6)]) + f" → {_when(pts[-1]['time'])} {_eur(pts[-1]['total_after'])}")
        for isin, p in (last.get("holdings") or {}).items():
            chg = p["price"] / p["avg_price"] - 1 if p.get("avg_price") else 0
            add(f"- {p['name'][:30]:30s} {p['shares']:5d} Stück  Einstand {p['avg_price']:9.2f}  Kurs {p['price']:9.2f}  {chg:+.1%}")
            if chg <= -0.15:
                warn.append(f"{p['name']} liegt {chg:+.0%} zum Einstand (Stopp bei −25 %)")
            elif chg <= -0.10:
                warn.append(f"{p['name']} liegt {chg:+.0%} zum Einstand")
        age = (now.replace(tzinfo=None) - datetime.fromisoformat(last["time"])).total_seconds() / 3600 if last.get("time") else None
        if s["enabled"] and age is not None and (age > 72 or (now.weekday() in (1, 2, 3, 4) and age > 30)):
            warn.append(f"Seit {age:.0f} Stunden kein Lauf, obwohl der Zeitplan an ist")
    else:
        add("(noch kein Lauf mit Protokoll)")

    add("")
    add("LETZTE ENTSCHEIDUNGEN")
    for e in reversed(logs[-5:]):
        ap, rej = e.get("approved") or [], e.get("rejected") or []
        buys, sells = sum(o["action"] == "buy" for o in ap), sum(o["action"] == "sell" for o in ap)
        add(f"- {_when(e.get('time'))} {DEPOTS.get(e.get('depot'), e.get('depot'))}: {buys} Käufe, {sells} Verkäufe, {len(rej)} abgelehnt | {e.get('provider')}" + (f" (Ausweichen auf Regeln: {e['fallback_reason']})" if e.get("fallback_reason") else ""))
        if e.get("market_view"):
            add("    " + e["market_view"][:260].replace("\n", " "))
        if e.get("fallback_reason"):
            warn.append(f"Claude fiel aus, es galten die Regeln ({_when(e.get('time'))}): {str(e['fallback_reason'])[:120]}")
        r = e.get("research") or {}
        if r.get("error"):
            warn.append(f"Recherche-Fehler ({_when(e.get('time'))}): {str(r['error'])[:120]}")
    why = Counter(x.get("why", "") for e in logs[-5:] for x in (e.get("rejected") or []))
    if why:
        add("Abgelehnte Orders (letzte 5 Läufe): " + "; ".join(f"{n}× {w}" for w, n in why.most_common(3)))
    cost = sum(((e.get("verbrauch") or {}).get("entscheidung") or {}).get("kosten_usd", 0) or 0 for e in logs[-21:])
    add(f"Claude-Verbrauch der letzten {min(len(logs), 21)} Läufe (Rechenwert zu API-Preisen, zählt gegen das Abo-Limit): {cost:.2f} $")
    if last and last.get("vergleich"):
        add(f"Claude gegen Regeln (Schattendepot): {last['vergleich'].get('urteil')} – {last['vergleich'].get('text', '')[:160]}")

    add("")
    add("AUFFÄLLIGKEITEN")
    try:
        free = shutil.disk_usage(base).free / 1e9
        if free < 2:
            warn.append(f"Wenig Speicherplatz frei: {free:.1f} GB")
    except OSError:
        pass
    add("\n".join(f"- {w}" for w in dict.fromkeys(warn)) or "keine")

    text = "\n".join(lines)
    for v in store.secrets().values():   # Zugangsdaten nie ausgeben
        if v and len(v) >= 4:
            text = text.replace(v, "***")
    return text
