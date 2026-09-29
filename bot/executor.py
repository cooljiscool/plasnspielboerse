"""Ausführung: Simulation (DryRun) oder echte Plattform (Playwright, konfiguriert über data/selectors.json)."""
import json
import os
import re
from datetime import date

from . import config


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

    def __enter__(self):
        from playwright.sync_api import sync_playwright

        self._pw = sync_playwright().start()
        self.browser = self._pw.chromium.launch()
        self.page = self.browser.new_page(viewport={"width": 1400, "height": 1000})
        self.page.set_default_timeout(20000)
        self.page.goto(self.sel["login_url"])
        self.page.fill(self.sel["user_field"], self.user)
        self.page.fill(self.sel["password_field"], self.password)
        self.page.click(self.sel["login_button"])
        self.page.wait_for_selector(self.sel["logged_in_marker"])
        return self

    def __exit__(self, *exc):
        self.browser.close()
        self._pw.stop()

    # --- Lesen ---
    def get_portfolio(self, previous: dict | None = None) -> dict:
        s, page = self.sel["portfolio"], self.page
        page.goto(s["url"])
        page.wait_for_selector(s["cash_selector"])
        cash = parse_de_number(page.inner_text(s["cash_selector"]))
        positions = {}
        page.wait_for_load_state("networkidle")
        prev = (previous or {}).get("positions", {})
        for row in page.locator(s["row_selector"]).all():
            isin = row.locator(s["isin_cell"]).inner_text().strip()
            shares = int(parse_de_number(row.locator(s["shares_cell"]).inner_text()))
            avg = parse_de_number(row.locator(s["avg_price_cell"]).inner_text())
            bought = prev.get(isin, {}).get("bought", date.today().isoformat())
            positions[isin] = {"shares": shares, "avg_price": avg, "bought": bought}
        return {"cash": cash, "positions": positions,
                "buy_orders_executed": (previous or {}).get("buy_orders_executed", 0)}

    # --- Schreiben ---
    def _run_steps(self, steps: list, values: dict) -> None:
        for st in steps:
            val = str(st.get("value", "")).format(**values)
            act, target = st["do"], st.get("selector")
            if act == "goto":
                self.page.goto(val)
            elif act == "click":
                self.page.click(target)
            elif act == "fill":
                self.page.fill(target, val)
            elif act == "press":
                self.page.press(target, val)
            elif act == "select":
                self.page.select_option(target, label=val)
            elif act == "wait":
                self.page.wait_for_selector(target)
            else:
                raise ValueError(f"unbekannter Schritt: {act}")

    def place(self, order: dict, today: date) -> None:
        key = "buy_steps" if order["action"] == "buy" else "sell_steps"
        values = {"isin": order["isin"], "name": order.get("name", ""), "search": order.get("search") or order.get("name", ""),
                  "shares": order["shares"],
                  "stop": f'{order["stop_price"]:.2f}'.replace(".", ",") if order.get("stop_price") else ""}
        self._run_steps(self.sel["order"][key], values)
        self.page.wait_for_selector(self.sel["order"]["confirmation_marker"])
        if order["action"] == "buy" and order.get("stop_price") and self.sel["order"].get("stop_steps"):
            self._run_steps(self.sel["order"]["stop_steps"], values)
