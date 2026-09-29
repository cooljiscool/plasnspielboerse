"""Ausführung: Simulation (DryRun) oder echte Plattform (Playwright)."""
import json
import os
from datetime import date

from . import config


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
                pf["positions"][isin] = {"shares": sh, "avg_price": px, "bought": today.isoformat()}
            pf["buy_orders_executed"] = pf.get("buy_orders_executed", 0) + 1
        else:
            pf["cash"] += value - config.fee(value)
            pos["shares"] -= sh
            if pos["shares"] == 0:
                del pf["positions"][isin]


class PlaywrightExecutor:
    """Bedient die Weboberfläche des Planspiels. Selektoren stehen in data/selectors.json und
    müssen einmalig mit `playwright codegen` ermittelt werden (siehe README)."""

    def __init__(self):
        path = os.path.join(config.DATA_DIR, "selectors.json")
        if not os.path.exists(path):
            raise RuntimeError("data/selectors.json fehlt – Live-Modus braucht die Selektoren (README, Schritt 2).")
        self.sel = json.load(open(path))
        self.user = os.environ["PSB_USER"]
        self.password = os.environ["PSB_PASSWORD"]

    def __enter__(self):
        from playwright.sync_api import sync_playwright

        self._pw = sync_playwright().start()
        self.browser = self._pw.chromium.launch()
        self.page = self.browser.new_page()
        self.page.goto(self.sel["login_url"])
        self.page.fill(self.sel["user_field"], self.user)
        self.page.fill(self.sel["password_field"], self.password)
        self.page.click(self.sel["login_button"])
        self.page.wait_for_selector(self.sel["logged_in_marker"])
        return self

    def __exit__(self, *exc):
        self.browser.close()
        self._pw.stop()

    def get_portfolio(self) -> dict:
        raise NotImplementedError("Depotansicht auslesen: Selektoren aus codegen-Aufzeichnung eintragen.")

    def place(self, order: dict, today: date) -> None:
        raise NotImplementedError("Orderformular ausfüllen und Bestätigung prüfen (codegen-Aufzeichnung).")
