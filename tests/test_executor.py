"""Executor und Selektoren-Datei: Platzhalter, ISIN-Zellen, optionale Schritte, Marktreiter und Vollständigkeit von data/selectors.json."""
import json
import os
import re

import pytest

from bot import config
from bot.executor import PlaywrightExecutor, fill_placeholders, find_isin

ROOT = os.path.dirname(os.path.dirname(__file__))


class TimeoutError(Exception):   # heißt wie die Ausnahme von Playwright; der Executor erkennt optionale Schritte am Namen
    pass


class Page:
    def __init__(self, missing=()):
        self.calls, self.missing = [], set(missing)

    def _do(self, what, sel, **kw):
        self.calls.append((what, sel, kw))
        if sel in self.missing:
            raise TimeoutError(sel)

    def click(self, sel, **kw): self._do("click", sel, **kw)
    def dispatch_event(self, sel, ev, **kw): self._do("dispatch:" + ev, sel, **kw)
    def fill(self, sel, val, **kw): self._do("fill", sel, value=val, **kw)
    def wait_for_selector(self, sel, **kw): self._do("wait", sel, **kw)


def executor(sel=None, page=None):
    ex = object.__new__(PlaywrightExecutor)
    ex.sel, ex.page = sel or {"order": {"tabs": {"dax": "DAX", "nasdaq100": "Nasdaq 100", "europa": "Selection Europe"}}}, page or Page()
    return ex


def test_placeholders_fill_known_names_and_leave_other_braces_alone():
    v = {"isin": "DE000A1EWWW0", "shares": 30, "tab": "Nasdaq 100"}
    assert fill_placeholders('label[for="{tab}"]', v) == 'label[for="Nasdaq 100"]'
    assert fill_placeholders("{shares}", v) == "30"
    assert fill_placeholders("text=/^A{2,3}$/ {unbekannt}", v) == "text=/^A{2,3}$/ {unbekannt}"


def test_isin_is_found_in_a_multiline_name_cell():
    assert find_isin("ADIDAS AG NA O.N.\nDE000A1EWWW0\nConsumer staples") == "DE000A1EWWW0"
    assert find_isin("  US0378331005 ") == "US0378331005"
    assert find_isin(" Ohne Kennung ") == "Ohne Kennung"


def test_optional_steps_are_skipped_on_timeout_but_required_ones_fail():
    page = Page(missing={"#dialog-ok"})
    executor(page=page)._run_steps([{"do": "click", "selector": "#a"}, {"do": "click", "selector": "#dialog-ok", "optional": True}, {"do": "click", "selector": "#b"}], {})
    assert [c[1] for c in page.calls] == ["#a", "#dialog-ok", "#b"] and page.calls[1][2]["timeout"] == 4000 and "timeout" not in page.calls[0][2]
    with pytest.raises(TimeoutError):
        executor(page=Page(missing={"#x"}))._run_steps([{"do": "click", "selector": "#x"}], {})
    with pytest.raises(ValueError):
        executor(page=Page(missing=set()))._run_steps([{"do": "tanzen", "selector": "#x"}, ], {})


def test_steps_take_placeholders_in_selectors_and_values_and_wait_states():
    page = Page()
    executor(page=page)._run_steps([{"do": "click", "selector": 'tr:has-text("{isin}") button'}, {"do": "fill", "selector": "#q", "value": "{shares}"},
                                    {"do": "wait", "selector": "#m", "state": "attached"}], {"isin": "DE0005140008", "shares": 7})
    assert page.calls == [("click", 'tr:has-text("DE0005140008") button', {}), ("fill", "#q", {"value": "7"}), ("wait", "#m", {"state": "attached"})]


def test_market_tab_is_taken_from_the_first_known_index_and_required_when_used():
    ex = executor()
    assert ex._tab({"indices": ["tecdax", "dax"]}) == "DAX"          # tecdax ist nicht eingetragen, dax schon
    assert ex._tab({"indices": ["nasdaq100", "gci"]}) == "Nasdaq 100"
    assert ex._tab({"indices": []}) == ""
    with pytest.raises(RuntimeError, match="Marktreiter"):
        ex._run_steps([{"do": "click", "selector": 'label[for="{tab}"]'}], {"isin": "XX", "tab": ""})


def test_confirmation_with_an_error_text_aborts_the_order():
    class El:
        def __init__(self, t): self.t = t
        def inner_text(self): return self.t
    ex = executor({"order": {"confirmation_marker": ".x", "error_pattern": "fehler|nicht genug"}})
    ex.page = type("P", (), {"wait_for_selector": staticmethod(lambda sel, **k: El("Order wurde entgegengenommen"))})
    assert ex._confirm() == "Order wurde entgegengenommen"
    ex.page = type("P", (), {"wait_for_selector": staticmethod(lambda sel, **k: El("Fehler: nicht genug Kapital"))})
    with pytest.raises(RuntimeError, match="nicht genug Kapital"):
        ex._confirm()


# --- die mitgelieferte data/selectors.json ---
@pytest.fixture(scope="module")
def sel():
    return json.load(open(os.path.join(ROOT, "data", "selectors.json")))


def test_shipped_selectors_have_every_section_the_executor_reads(sel):
    for k in ("login_url", "user_field", "password_field", "login_button", "logged_in_marker"):
        assert sel[k]
    assert all(sel["portfolio"][k] for k in ("url", "cash_selector", "row_selector", "isin_cell", "shares_cell", "avg_price_cell"))
    assert all(sel["order"][k] for k in ("buy_steps", "sell_steps", "confirmation_marker"))
    sw = sel["depot_switch"]
    assert sw["test_steps"] and sw["echt_steps"] and sw["test_marker"] != sw["echt_marker"]


def test_shipped_selector_steps_use_only_known_placeholders_and_actions(sel):
    steps = sel["order"]["buy_steps"] + sel["order"]["sell_steps"] + sel["depot_switch"]["test_steps"] + sel["depot_switch"]["echt_steps"] + sel["pre_login_steps"]
    for st in steps:
        assert st["do"] in ("click", "fill", "press", "select", "wait", "goto")
        for name in re.findall(r"\{(\w+)\}", json.dumps(st, ensure_ascii=False)):
            assert name in ("isin", "name", "search", "shares", "stop", "tab"), (name, st)
    assert any("{shares}" in st.get("value", "") for st in sel["order"]["buy_steps"])      # die Stückzahl wird eingetragen
    assert any("{tab}" in st["selector"] for st in sel["order"]["buy_steps"])


def test_every_index_of_the_universe_has_a_market_tab(sel):
    indices = {i for u in json.load(open(os.path.join(ROOT, "data", "universe.json"))) for i in u.get("indices", [])}
    assert indices <= set(sel["order"]["tabs"]), indices - set(sel["order"]["tabs"])


def test_browser_setting_defaults_to_firefox_and_ignores_unknown_values(monkeypatch):
    import importlib
    for val, want in ((None, "firefox"), ("chromium", "chromium"), ("chrome", "chrome"), ("opera", "firefox")):
        monkeypatch.delenv("BOT_BROWSER", raising=False)
        if val:
            monkeypatch.setenv("BOT_BROWSER", val)
        assert importlib.reload(config).BROWSER == want
    monkeypatch.delenv("BOT_BROWSER", raising=False)
    importlib.reload(config)


# --- geführte Testorder (python -m bot.selftest --testorder) ---
def fake_platform(monkeypatch, tmp_path, fills=True, fail=None):
    from bot import selftest
    (tmp_path / "universe.json").write_text(json.dumps([{"isin": "DE000BASF111", "name": "BASF SE", "search": "DE000BASF111", "indices": ["dax"]}]))
    monkeypatch.setattr(config, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(config, "DEPOT", "echt")
    seen = {"orders": [], "depot": []}
    held = {"n": 0}

    class Fake:
        def __enter__(self): seen["depot"].append(config.DEPOT); return self
        def __exit__(self, *a): return False
        page = type("P", (), {"locator": staticmethod(lambda s: type("L", (), {"all_inner_texts": staticmethod(lambda: ["Order aufgegeben"])}))})
        def get_portfolio(self, prev=None):
            return {"cash": 50000.0, "positions": ({"DE000BASF111": {"shares": held["n"], "avg_price": 45.0}} if held["n"] else {}), "buy_orders_executed": 0}
        def place(self, o, today):
            if fail:
                raise RuntimeError(fail)
            seen["orders"].append(o["action"])
            if fills:
                held["n"] += 1 if o["action"] == "buy" else -1
            return "Order wurde entgegengenommen"
    monkeypatch.setattr("bot.executor.PlaywrightExecutor", Fake)
    return selftest, seen


def test_testorder_buys_and_sells_one_share_and_always_uses_the_test_depot(monkeypatch, tmp_path, capsys):
    selftest, seen = fake_platform(monkeypatch, tmp_path)
    assert selftest.testorder() == 0
    out = capsys.readouterr().out
    assert seen["orders"] == ["buy", "sell"] and seen["depot"] == ["test"]        # trotz Einstellung "echt" nur das Testdepot
    assert "Order wurde entgegengenommen" in out and "FAIL" not in out and "WARN" not in out


def test_testorder_warns_instead_of_selling_when_the_order_is_still_open(monkeypatch, tmp_path, capsys):
    selftest, seen = fake_platform(monkeypatch, tmp_path, fills=False)
    assert selftest.testorder() == 0
    assert seen["orders"] == ["buy"] and "WARN" in capsys.readouterr().out


def test_testorder_reports_failures_and_unknown_isins(monkeypatch, tmp_path, capsys):
    selftest, seen = fake_platform(monkeypatch, tmp_path, fail="Zeitüberschreitung bei label[for=type2]")
    assert selftest.testorder() == 1
    out = capsys.readouterr().out
    assert "FAIL" in out and "type2" in out and "debug" in out
    assert selftest.testorder("XX0000000000") == 1


class Req:
    def __init__(self, method="POST", url="https://x.example/api/authenticate"):
        self.method, self.url = method, url


class Resp:
    def __init__(self, status, req):
        self.status, self.request, self.url = status, req, req.url


class LoginPage(Page):
    """Anmeldeseite mit Ereignissen. behaviour(versuch, weg) -> HTTP-Status, wenn dabei eine Anfrage hinausgeht, sonst None (weg: "click" oder "enter"; versuch zählt ab 1).
    Die Anmeldung gilt als gelungen, wenn dabei eine Anfrage mit Status 200 hinausging."""
    def __init__(self, behaviour, text=""):
        super().__init__()
        self.behaviour, self.text, self.handlers, self.fired, self.log = behaviour, text, {}, [], []

    def on(self, event, fn): self.handlers.setdefault(event, []).append(fn)
    def goto(self, url, **kw): self.calls.append(("goto", url, {}))
    def wait_for_load_state(self, state, **kw): pass
    def wait_for_timeout(self, ms): pass
    def inner_text(self, sel): return self.text
    def type(self, sel, text, **kw): self.log.append(("type", sel))

    @property
    def attempt(self): return len([c for c in self.calls if c[0] == "goto"])

    def _fire(self, via):
        status = self.behaviour(self.attempt, via)
        self.log.append((via, status))
        if status is not None:
            r = Req()
            for h in self.handlers.get("request", []): h(r)
            for h in self.handlers.get("response", []): h(Resp(status, r))
            self.fired.append(status)

    def click(self, sel, **kw): self._fire("click")
    def press(self, sel, key, **kw): self._fire("enter")

    def wait_for_selector(self, sel, **kw):
        if sel == "#in" and 200 not in self.fired:
            raise TimeoutError(sel)


def never_logged_in(sel, **kw):
    """Ersetzt wait_for_selector: nur das Erkennungsmerkmal der Anmeldung erscheint nie."""
    if sel == "#in":
        raise TimeoutError(sel)


def login_executor(page, **extra):
    ex = executor({"login_url": "u", "user_field": "#u", "password_field": "#p", "login_button": "#b", "logged_in_marker": "#in", "login_request": "authenticate", **extra}, page)
    ex.user, ex.password = "a", "b"
    return ex


def test_login_types_like_a_person_and_clicks_once_when_the_request_goes_out():
    page = LoginPage(lambda attempt, via: 200)
    login_executor(page)._login()
    assert [x[1] for x in page.log if x[0] == "type"] == ["#u", "#p"] and [x[0] for x in page.log if x[0] in ("click", "enter")] == ["click"] and page.attempt == 1


def test_login_presses_enter_when_the_click_has_no_effect_and_reloads_when_that_fails_too():
    page = LoginPage(lambda attempt, via: 200 if via == "enter" else None)       # Klick ignoriert, Enter wirkt
    login_executor(page)._login()
    assert page.attempt == 1 and [x[0] for x in page.log if x[0] in ("click", "enter")] == ["click", "enter"]
    page = LoginPage(lambda attempt, via: 200 if attempt == 2 else None)         # erster Versuch ganz wirkungslos, zweiter klappt
    login_executor(page)._login()
    assert page.attempt == 2 and page.fired == [200]


def test_login_gives_up_with_a_clear_message_when_nothing_can_be_sent():
    page = LoginPage(lambda attempt, via: None)
    with pytest.raises(RuntimeError, match="ließ sich nicht abschicken"):
        login_executor(page)._login()
    assert page.attempt == 3                                                      # nie eine Anfrage, also nie ein gezähltes Passwort


def test_login_is_never_repeated_after_it_was_sent_so_a_wrong_password_cannot_lock_the_account():
    page = LoginPage(lambda attempt, via: 200)
    page.fired = []                                                              # abgeschickt, aber ohne Erfolg: die Seite zeigt nichts an
    page.wait_for_selector = never_logged_in
    with pytest.raises(TimeoutError):
        login_executor(page)._login()
    assert page.attempt == 1 and [x[0] for x in page.log if x[0] in ("click", "enter")] == ["click"]


def test_login_rejection_is_recognised_from_the_answer_or_the_message_on_the_page():
    from bot.executor import LoginRejected
    page = LoginPage(lambda attempt, via: 401)
    with pytest.raises(LoginRejected, match="Anmeldung abgelehnt"):
        login_executor(page)._login()
    assert page.attempt == 1
    page = LoginPage(lambda attempt, via: 200, text="Ihr Konto ist gesperrt, weil Sie mehr als 3 Mal das falsche Passwort eingegeben haben.")
    page.wait_for_selector = never_logged_in
    with pytest.raises(LoginRejected, match="gesperrt"):
        login_executor(page)._login()
    assert page.attempt == 1


def test_only_requests_to_the_login_address_count_as_sent():
    class Noise(LoginPage):
        def _fire(self, via):               # eine fremde Anfrage (etwa Statistik) darf nicht als Anmeldung zählen
            r = Req(url="https://x.example/api/track")
            for h in self.handlers.get("request", []): h(r)
            self.log.append((via, None))
    page = Noise(lambda attempt, via: None)
    with pytest.raises(RuntimeError, match="ließ sich nicht abschicken"):
        login_executor(page)._login()
