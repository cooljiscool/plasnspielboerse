import json
import os
import stat
from datetime import datetime

import pytest

from dashboard.app import create_app
from dashboard.runner import TZ, next_run

PW = "test-passwort-123"
H = {"X-Requested-With": "dashboard"}


@pytest.fixture
def app(tmp_path):
    a = create_app(PW, state_dir=str(tmp_path / "state"), data_dir=str(tmp_path / "data"),
                   log_dir=str(tmp_path / "logs"), autostart=False)
    (tmp_path / "data").mkdir()
    (tmp_path / "logs").mkdir()
    return a


@pytest.fixture
def c(app):
    return app.test_client()


@pytest.fixture
def authed(c):
    assert c.post("/api/login", json={"password": PW}).status_code == 200
    return c


def test_short_password_refused(tmp_path):
    with pytest.raises(SystemExit):
        create_app("kurz", state_dir=str(tmp_path), autostart=False)


def test_requires_login(c):
    assert c.get("/api/status").status_code == 401
    assert c.get("/api/depot").status_code == 401
    assert c.post("/api/login", json={"password": "falsch"}).status_code == 401


def test_login_rate_limit(c):
    for _ in range(5):
        c.post("/api/login", json={"password": "falsch"})
    assert c.post("/api/login", json={"password": PW}).status_code == 429


def test_post_needs_csrf_header(authed):
    assert authed.post("/api/control", json={"action": "start"}).status_code == 400
    assert authed.post("/api/control", json={"action": "start"}, headers=H).status_code == 200


def test_secrets_stored_privately_and_never_returned(authed, app):
    r = authed.post("/api/settings", headers=H, json={"secrets": {"PSB_USER": "team42", "PSB_PASSWORD": "geheim-xyz",
                                                                   "ANTHROPIC_API_KEY": "sk-ant-abc123"}})
    body = r.get_data(as_text=True)
    assert "geheim-xyz" not in body and "sk-ant-abc123" not in body
    assert r.get_json()["secrets"] == {"ANTHROPIC_API_KEY": True, "PSB_USER": True, "PSB_PASSWORD": True,
                                       "CLAUDE_CODE_OAUTH_TOKEN": False, "QUIVER_API_TOKEN": False, "SEC_USER_AGENT": False}
    path = os.path.join(app.store.dir, "secrets.json")
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600
    # leeres Feld ändert nichts
    authed.post("/api/settings", headers=H, json={"secrets": {"PSB_USER": ""}})
    assert app.store.secrets()["PSB_USER"] == "team42"


def test_output_scrubs_secrets(authed, app):
    app.store.update_secrets({"PSB_PASSWORD": "geheim-xyz"})
    open(app.runner.output_path, "w").write("Login mit geheim-xyz fehlgeschlagen\n")
    assert "geheim-xyz" not in authed.get("/api/output").get_data(as_text=True)


def test_times_validated(authed):
    assert authed.post("/api/settings", headers=H, json={"times": ["25:00"]}).status_code == 400
    r = authed.post("/api/settings", headers=H, json={"times": ["13:30", "09:20"]})
    assert r.get_json()["times"] == ["09:20", "13:30"]


def test_live_needs_confirmation_secrets_and_selectors(authed, app, tmp_path):
    assert authed.post("/api/live", headers=H, json={"live": True}).status_code == 400
    assert authed.post("/api/live", headers=H, json={"live": True, "confirm": "LIVE"}).status_code == 400  # Secrets fehlen
    app.store.update_secrets({"PSB_USER": "u", "PSB_PASSWORD": "p", "ANTHROPIC_API_KEY": "k"})
    assert authed.post("/api/live", headers=H, json={"live": True, "confirm": "LIVE"}).status_code == 400  # Selektoren fehlen
    (tmp_path / "data" / "selectors.json").write_text("{}")
    assert authed.post("/api/live", headers=H, json={"live": True, "confirm": "LIVE"}).get_json()["live"] is True
    assert authed.post("/api/live", headers=H, json={"live": False}).get_json()["live"] is False


def test_start_stop_kills_running_process(authed, app, tmp_path):
    fake = tmp_path / "fakepython"
    fake.write_text("#!/bin/sh\nsleep 30\n")
    fake.chmod(0o755)
    app.runner.python = str(fake)
    assert authed.post("/api/control", headers=H, json={"action": "run"}).get_json()["running"] is True
    assert authed.post("/api/control", headers=H, json={"action": "run"}).status_code == 409
    authed.post("/api/control", headers=H, json={"action": "start"})
    st = authed.post("/api/control", headers=H, json={"action": "stop"}).get_json()
    assert st["enabled"] is False and st["running"] is False


def test_files_validated(authed, tmp_path):
    assert authed.post("/api/file/selectors", headers=H, json={"text": "{kaputt"}).status_code == 400
    assert authed.post("/api/file/universe", headers=H, json={"text": "[1]"}).status_code == 400
    assert authed.post("/api/file/../etc", headers=H, json={"text": "{}"}).status_code == 404
    ok = json.dumps([{"isin": "A", "name": "Alpha"}])
    assert authed.post("/api/file/universe", headers=H, json={"text": ok}).status_code == 200
    assert json.loads(authed.get("/api/file/universe").get_json()["text"])[0]["isin"] == "A"


def test_depot_reads_logs(authed, tmp_path):
    (tmp_path / "data" / "portfolio.json").write_text(json.dumps({"cash": 100.0, "positions": {}}))
    for i, tot in enumerate([50000.0, 51000.0]):
        (tmp_path / "logs" / f"2026100{i}-0900.json").write_text(json.dumps(
            {"time": f"2026-10-0{i + 1}T09:00:00", "live": False, "total_before": tot, "total_after": tot,
             "holdings": {"A": {"name": "Alpha", "shares": 1, "avg_price": 1, "price": 2}},
             "market_view": "x", "approved": [], "rejected": []}))
    d = authed.get("/api/depot").get_json()
    assert [s["v"] for s in d["series"]] == [50000.0, 51000.0]
    assert d["holdings"]["A"]["name"] == "Alpha" and d["decisions"][0]["time"].endswith("09:00:00")


def test_next_run_skips_weekend():
    fr = datetime(2026, 10, 2, 20, 0, tzinfo=TZ)  # Freitag Abend
    assert next_run(fr, ["09:20", "13:30"]) == datetime(2026, 10, 5, 9, 20, tzinfo=TZ)
    assert next_run(datetime(2026, 10, 2, 10, 0, tzinfo=TZ), ["09:20", "13:30"]) == datetime(2026, 10, 2, 13, 30, tzinfo=TZ)


def test_scheduler_fires_once_per_slot(app, monkeypatch):
    calls = []
    monkeypatch.setattr(app.runner, "start", lambda kind: calls.append(kind) or True)
    app.store.save_settings(enabled=True, times=["09:20"])
    mon = datetime(2026, 10, 5, 9, 25, tzinfo=TZ)
    fired = app.runner.tick(mon, "")
    app.runner.tick(mon.replace(minute=27), fired)
    assert calls == ["run"]
    app.store.save_settings(enabled=False)
    app.runner.tick(datetime(2026, 10, 6, 9, 21, tzinfo=TZ), fired)
    assert calls == ["run"]
    app.store.save_settings(enabled=True)
    app.runner.tick(datetime(2026, 10, 10, 9, 21, tzinfo=TZ), "")  # Samstag
    assert calls == ["run"]


def test_provider_setting_validated(authed):
    assert authed.post("/api/settings", headers=H, json={"provider": "gpt"}).status_code == 400
    assert authed.post("/api/settings", headers=H, json={"provider": "claude_cli"}).get_json()["provider"] == "claude_cli"


def test_live_does_not_require_ai_credentials(authed, app, tmp_path):
    app.store.update_secrets({"PSB_USER": "u", "PSB_PASSWORD": "p"})  # kein KI-Token nötig (Regelstrategie)
    (tmp_path / "data" / "selectors.json").write_text("{}")
    assert authed.post("/api/live", headers=H, json={"live": True, "confirm": "LIVE"}).status_code == 200


def test_oauth_token_reaches_bot_env_but_not_output(authed, app):
    app.store.update_secrets({"CLAUDE_CODE_OAUTH_TOKEN": "sk-ant-oat01-abcdef"})
    app.store.save_settings(provider="claude_cli")
    env = app.runner._env(live=False)
    assert env["CLAUDE_CODE_OAUTH_TOKEN"] == "sk-ant-oat01-abcdef" and env["BOT_PROVIDER"] == "claude_cli"
    open(app.runner.output_path, "w").write("Token sk-ant-oat01-abcdef ungültig")
    assert "abcdef" not in authed.get("/api/output").get_data(as_text=True)


def test_research_toggle_reaches_bot_env(authed, app):
    assert authed.post("/api/settings", headers=H, json={"research": False}).get_json()["research"] is False
    assert app.runner._env(live=False)["BOT_RESEARCH"] == "0"
    authed.post("/api/settings", headers=H, json={"research": True})
    assert app.runner._env(live=False)["BOT_RESEARCH"] == "1"


def test_quiver_token_and_sec_contact_are_stored_privately_and_reach_the_bot_env(authed, app):
    r = authed.post("/api/settings", headers=H, json={"secrets": {"QUIVER_API_TOKEN": "qv-geheim-123", "SEC_USER_AGENT": "Max Muster max@example.org"}})
    body = r.get_data(as_text=True)
    assert "qv-geheim-123" not in body and "max@example.org" not in body
    assert r.get_json()["secrets"]["QUIVER_API_TOKEN"] is True and r.get_json()["secrets"]["SEC_USER_AGENT"] is True
    env = app.runner._env(False)
    assert env["QUIVER_API_TOKEN"] == "qv-geheim-123" and env["SEC_USER_AGENT"] == "Max Muster max@example.org"
    assert stat.S_IMODE(os.stat(os.path.join(app.store.dir, "secrets.json")).st_mode) == 0o600


def test_depot_api_exposes_extra_data_line(authed, app, tmp_path):
    log_dir = tmp_path / "logs"
    log_dir.mkdir(exist_ok=True)
    (log_dir / "20261001-0920.json").write_text(json.dumps({"time": "2026-10-01T09:20:00", "total_after": 50000.0, "holdings": {}, "approved": [], "rejected": [],
                                                              "daten": {"analysten": 3, "reddit": 2, "insider_sec": "aus: SEC_USER_AGENT (Name und E-Mail) fehlt"}}))
    d = authed.get("/api/depot").get_json()
    assert d["decisions"][0]["daten"]["analysten"] == 3
