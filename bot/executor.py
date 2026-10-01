"""Ausführung: Simulation (DryRun) oder echte Plattform (Playwright, konfiguriert über data/selectors.json)."""
import json
import os
import re
from datetime import date, datetime

from . import config


ISIN_RE = re.compile(r"\b[A-Z]{2}[A-Z0-9]{9}\d\b")
PLACEHOLDER_RE = re.compile(r"\{(\w+)\}")
LOAD_TRIES, LOAD_WAIT_MS = 8, 1500   # so oft (und mit dieser Pause) wird ein halb geladenes Depot neu gelesen
LOGIN_TRIES, LOGIN_WAIT_MS = 1, 15000   # genau ein Anmeldeversuch: Die Plattform sperrt das Konto nach mehr als 3 falschen Passwörtern
OPTIONAL_TIMEOUT_MS = 4000   # so lange wird auf einen Schritt mit "optional": true gewartet (etwa ein Bestätigungsfenster, das nicht immer erscheint)


def fill_placeholders(text, values: dict) -> str:
    """Ersetzt {isin} {name} {search} {shares} {stop} {tab} in Selektoren und Werten. Andere geschweifte Klammern (z. B. in regulären Ausdrücken) bleiben unberührt."""
    return PLACEHOLDER_RE.sub(lambda m: str(values[m.group(1)]) if m.group(1) in values else m.group(0), str(text))


def find_isin(text: str) -> str:
    """Zelle 'Name / ISIN / Branche' (mehrere Zeilen) -> die ISIN; ohne Treffer der bereinigte Text."""
    m = ISIN_RE.search(text)
    return m.group(0) if m else text.strip()


def parse_de_number(text: str) -> float:
    """'1.234,56 €' -> 1234.56"""
    m = re.search(r"-?[\d.]*\d(?:,\d+)?", text.replace(" ", " "))
    if not m:
        raise ValueError(f"keine Zahl in {text!r}")
    return float(m.group(0).replace(".", "").replace(",", "."))


class DryRunExecutor:
    """Bucht Orders lokal zum letzten Kurs inkl. Gebühr. Für Tests und den Trockenlauf."""

    def __init__(self, pf: dict):
        self.pf = pf

    def get_portfolio(self) -> dict:
        return self.pf

    def place(self, order: dict, today: date) -> None:
        pf, isin, sh, px = self.pf, order["isin"], order["shares"], order["est_price"]
        value = sh * px
        pos = pf["positions"].get(isin)
        if order["action"] == "buy":
            pf["cash"] -= value + config.fee(value)
            if pos:
                total = pos["shares"] + sh
                pos["avg_price"] = (pos["avg_price"] * pos["shares"] + value) / total
                pos["shares"] = total
            else:
                pf["positions"][isin] = {"shares": sh, "avg_price": px, "bought": today.isoformat(), "peak": px}
            pf["buy_orders_executed"] = pf.get("buy_orders_executed", 0) + 1
        else:
            pf["cash"] += value - config.fee(value)
            pos["shares"] -= sh
            if pos["shares"] == 0:
                del pf["positions"][isin]


class PlaywrightExecutor:
    """Bedient die Weboberfläche des Planspiels. Alle Selektoren und Klickfolgen stehen in
    data/selectors.json (Vorlage: data/selectors.example.json) und werden einmalig per
    `playwright codegen` ermittelt (siehe README). Der Code selbst kennt keine Seitenstruktur."""

    def __init__(self):
        path = os.path.join(config.DATA_DIR, "selectors.json")
        if not os.path.exists(path):
            raise RuntimeError("data/selectors.json fehlt – siehe README, Schritt 3.")
        self.sel = json.load(open(path))
        self.user = os.environ["PSB_USER"]
        self.password = os.environ["PSB_PASSWORD"]
        self.prev = {}

    def _launch(self):
        """Startet den Browser aus config.BROWSER: firefox (Standard), chromium oder chrome (installiertes Google Chrome). Die Plattform wies die Anmeldung
        im Chromium von Playwright ab, im normalen Browser und in Firefox klappte sie."""
        if config.BROWSER == "firefox":
            return self._pw.firefox.launch()
        if config.BROWSER == "chrome":
            return self._pw.chromium.launch(channel="chrome")
        return self._pw.chromium.launch()

    def __enter__(self):
        from playwright.sync_api import sync_playwright

        self._pw = sync_playwright().start()
        self.browser = self._launch()
        self.page = self.browser.new_context(viewport={"width": 1400, "height": 1000}, locale="de-DE", timezone_id="Europe/Berlin").new_page()
        self.page.set_default_timeout(20000)
        try:
            self._login()
            self._select_depot()
        except Exception:
            self._dump("login")
            self._dump_text()
            print("Antworten der Plattform auf die Anmeldung: " + (" | ".join(getattr(self, "answers", [])[-6:]) or "keine (der Klick löste keine Anfrage aus)"))
            self.browser.close()
            self._pw.stop()
            raise
        return self

    def _login(self) -> None:
        """Anmelden (LOGIN_TRIES Versuche). Wiederholt wird nur, wenn gar nichts geschah; bei falschem Passwort gilt jeder Versuch, nach mehr als 3 sperrt die Plattform das Konto."""
        self.answers = []
        self.page.on("response", lambda r: self.answers.append(f"{r.request.method} {r.url.split('?')[0][-60:]} -> {r.status}") if r.request.method in ("POST", "PUT") else None)
        for attempt in range(LOGIN_TRIES):
            self.page.goto(self.sel["login_url"])
            self._run_steps(self.sel.get("pre_login_steps", []), {})
            self.page.wait_for_selector(self.sel["login_button"])
            self.page.wait_for_timeout(1500)
            self.page.fill(self.sel["user_field"], self.user)
            self.page.fill(self.sel["password_field"], self.password)
            self.page.click(self.sel["login_button"])
            try:
                self.page.wait_for_selector(self.sel["logged_in_marker"], timeout=LOGIN_WAIT_MS)
                return
            except Exception as e:  # noqa: BLE001
                if type(e).__name__ != "TimeoutError" or attempt == LOGIN_TRIES - 1:
                    raise
                self.page.wait_for_timeout(3000)

    def _select_depot(self) -> None:
        """Wählt nach der Anmeldung das Depot, in dem gehandelt wird (config.DEPOT: test oder echt), und prüft es an einem Erkennungsmerkmal. Ohne Abschnitt `depot_switch`
        in selectors.json wird nicht gehandelt: Sonst könnten Orders im falschen Depot landen (Testdepot zählt nicht für den Rang). Wer nur ein Depot hat, trägt {"skip": true} ein."""
        sw = self.sel.get("depot_switch")
        if not isinstance(sw, dict):
            raise RuntimeError("selectors.json enthält keinen Abschnitt 'depot_switch' (Umschalten zwischen Test- und Wettbewerbsdepot, siehe data/selectors.example.json). "
                               'Hat die Plattform nur ein Depot, trage "depot_switch": {"skip": true} ein.')
        if sw.get("skip"):
            return
        want, other = config.DEPOT, ("echt" if config.DEPOT == "test" else "test")
        steps = sw.get(f"{want}_steps")
        if not steps:
            raise RuntimeError(f"depot_switch.{want}_steps fehlt in selectors.json")
        self._run_steps(steps, {})
        marker = sw.get(f"{want}_marker")
        if marker:
            self.page.wait_for_selector(marker, state="attached")   # Zustandsmerkmal (z. B. angehaktes Optionsfeld), muss nicht sichtbar sein
        if sw.get(f"{want}_content"):                # erst wenn der Inhalt des gewählten Depots wirklich da ist, sonst wird kurz noch der Bildschirm des anderen Depots gelesen
            self.page.wait_for_selector(sw[f"{want}_content"], state="attached")
            if sw.get(f"{other}_content"):
                self.page.wait_for_selector(sw[f"{other}_content"], state="detached")
        if sw.get(f"{other}_marker") and self.page.locator(sw[f"{other}_marker"]).count():
            raise RuntimeError(f"Es ist das {'Wettbewerbsdepot' if other == 'echt' else 'Testdepot'} aktiv, gewollt ist das {'Wettbewerbsdepot' if want == 'echt' else 'Testdepot'}. Es wird nicht gehandelt.")

    def __exit__(self, *exc):
        self.browser.close()
        self._pw.stop()

    # --- Lesen ---
    def _read_positions(self, prev: dict) -> dict:
        s = self.sel["portfolio"]
        positions = {}
        for row in self.page.locator(s["row_selector"]).all():
            if not row.locator(s["isin_cell"]).count():   # Zusatz- oder Detailzeile ohne Namensspalte: keine Position
                continue
            isin = find_isin(row.locator(s["isin_cell"]).inner_text())
            shares = int(parse_de_number(row.locator(s["shares_cell"]).inner_text()))
            avg = parse_de_number(row.locator(s["avg_price_cell"]).inner_text())
            if isin in positions:                     # mehrere Zeilen desselben Titels (etwa getrennte Käufe): zusammenfassen
                old = positions[isin]
                total = old["shares"] + shares
                old["avg_price"] = (old["avg_price"] * old["shares"] + avg * shares) / total if total else avg
                old["shares"] = total
                continue
            positions[isin] = {"shares": shares, "avg_price": avg, "bought": prev.get(isin, {}).get("bought", date.today().isoformat())}
        return positions

    def get_portfolio(self, previous: dict | None = None) -> dict:
        s, page = self.sel["portfolio"], self.page
        try:
            page.goto(s["url"])
            self._select_depot()                      # nach dem Neuladen der Seite gilt wieder das Standarddepot
            self._run_steps(s.get("steps", []), {})
            page.wait_for_selector(s["cash_selector"])
            cash = parse_de_number(page.inner_text(s["cash_selector"]))
            if s.get("ready_selector"):               # Tabelle (oder ihr Leer-Hinweis) ist da; "networkidle" kommt bei Seiten mit laufenden Kursen nicht zuverlässig
                page.wait_for_selector(s["ready_selector"], state="attached")
            else:
                page.wait_for_load_state("networkidle")
            prev = (previous or {}).get("positions", {})
            for _ in range(LOAD_TRIES):
                positions = self._read_positions(prev)
                # Sicherung gegen ein halb geladenes Depot: Zeigt die Tabelle nichts, der Gesamtwert aber mehr als das Bargeld, fehlen die Positionen noch. Sonst hielte der Bot das Depot für leer und kaufte doppelt.
                if positions or not s.get("total_selector"):
                    break
                if parse_de_number(page.inner_text(s["total_selector"])) - cash <= 1.0:
                    break
                page.wait_for_timeout(LOAD_WAIT_MS)
                cash = parse_de_number(page.inner_text(s["cash_selector"]))
            else:
                raise RuntimeError("Das Depot ist nicht vollständig geladen: Gesamtwert über dem Barbestand, aber keine Positionen in der Tabelle. Es wird nicht gehandelt.")
        except Exception:
            self._dump("depot")
            raise
        return {"cash": cash, "positions": positions,
                "buy_orders_executed": (previous or {}).get("buy_orders_executed", 0)}

    def _dump(self, tag: str) -> None:
        """Bei einem Fehler Bild und Seitenquelltext ablegen (logs/debug/), damit sich die Selektoren gezielt nachbessern lassen. Fehler hier bleiben folgenlos."""
        try:
            folder = os.path.join(config.LOG_DIR, "debug")
            os.makedirs(folder, exist_ok=True)
            stem = os.path.join(folder, f"{datetime.now().strftime('%Y%m%d-%H%M%S')}-{tag}")
            self.page.screenshot(path=stem + ".png", full_page=True)
            open(stem + ".html", "w", encoding="utf-8").write(self.page.content())
        except Exception:  # noqa: BLE001
            pass

    def _dump_text(self) -> None:
        """Sichtbarer Text der Seite, in die Ausgabe (kurz, ohne Passwörter): zeigt etwa 'Zugangsdaten falsch' oder eine Einblendung."""
        try:
            print("Sichtbarer Text der Seite: " + " ".join(self.page.inner_text("body").split())[:600])
        except Exception:  # noqa: BLE001
            pass

    # --- Schreiben ---
    def _run_steps(self, steps: list, values: dict) -> None:
        """Führt die Schritte aus selectors.json aus. Schritt-Felder: do, selector, value, optional (true: erscheint das Element nicht binnen weniger Sekunden, weiter),
        state (nur bei wait: attached, visible, hidden, detached)."""
        for st in steps:
            val = fill_placeholders(st.get("value", ""), values)
            act = st["do"]
            target = fill_placeholders(st["selector"], values) if st.get("selector") else None
            if target and "{tab}" in st["selector"] and not values.get("tab"):
                raise RuntimeError(f"Für {values.get('isin')} ist in selectors.json (order.tabs) kein Marktreiter hinterlegt")
            opt = {"timeout": OPTIONAL_TIMEOUT_MS} if st.get("optional") else {}
            try:
                if act == "goto":
                    self.page.goto(val)
                elif act == "click":
                    self.page.click(target, **opt)
                elif act == "fill":
                    self.page.fill(target, val, **opt)
                elif act == "press":
                    self.page.press(target, val, **opt)
                elif act == "select":
                    self.page.select_option(target, label=val, **opt)
                elif act == "wait":
                    self.page.wait_for_selector(target, **({"state": st["state"]} if st.get("state") else {}), **opt)
                else:
                    raise ValueError(f"unbekannter Schritt: {act}")
            except Exception as e:  # noqa: BLE001
                if st.get("optional") and type(e).__name__ == "TimeoutError":
                    continue
                raise

    def _tab(self, order: dict) -> str:
        """Marktreiter der Marktübersicht, in dem das Wertpapier steht: erster Index des Titels (Universum) mit Eintrag in selectors.json (order.tabs)."""
        tabs = self.sel["order"].get("tabs") or {}
        return next((tabs[i] for i in order.get("indices") or [] if i in tabs), "")

    def _confirm(self) -> str:
        """Wartet auf die Rückmeldung der Plattform nach dem Ordern und bricht ab, wenn sie wie eine Fehlermeldung klingt (order.error_pattern)."""
        o = self.sel["order"]
        el = self.page.wait_for_selector(o["confirmation_marker"])
        text = (el.inner_text() if el else "").strip()
        if o.get("error_pattern") and re.search(o["error_pattern"], text, re.I):
            raise RuntimeError(f"Die Plattform meldet: {text[:200]}")
        return text

    def place(self, order: dict, today: date) -> str:
        """Gibt die Rückmeldung der Plattform (Text der Bestätigung) zurück."""
        key = "buy_steps" if order["action"] == "buy" else "sell_steps"
        values = {"isin": order["isin"], "name": order.get("name", ""), "search": order.get("search") or order.get("name", ""),
                  "shares": order["shares"], "tab": self._tab(order),
                  "stop": f'{order["stop_price"]:.2f}'.replace(".", ",") if order.get("stop_price") else ""}
        try:
            self._select_depot()                      # immer im gewollten Depot, auch wenn eine frühere Order die Seite verlassen hat
            self._run_steps(self.sel["order"][key], values)
            text = self._confirm()
            if order["action"] == "buy" and order.get("stop_price") and self.sel["order"].get("stop_steps"):
                self._run_steps(self.sel["order"]["stop_steps"], values)
        except Exception:
            self._dump(f"order-{order['action']}-{order['isin']}")
            raise
        return text
