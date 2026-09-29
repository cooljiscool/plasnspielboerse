import pytest

from bot import analysts, config, edgar, quiver, selftest, social


def run(capsys, monkeypatch, **cfg):
    for k, v in cfg.items():
        monkeypatch.setattr(config, k, v)
    ok = []
    selftest.extras(lambda name, fn, optional=False: ok.append(selftest.check(name, fn, optional)))
    return ok, capsys.readouterr().out


def test_optional_extras_warn_but_never_fail(capsys, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("Quelle down")
    monkeypatch.setattr(analysts, "_fetch", boom)
    monkeypatch.setattr(social, "_fetch_ape", boom)
    ok, out = run(capsys, monkeypatch, SEC_USER_AGENT="", QUIVER_TOKEN="", MCP_CONFIG="", MCP_TOOLS="")
    assert all(ok) and "[WARN] Zusatzdaten Analysten: Quelle down" in out and "[WARN] Zusatzdaten Reddit: Quelle down" in out
    assert "SEC_USER_AGENT" in out and "QUIVER_API_TOKEN" in out and "[FAIL]" not in out


def test_extras_report_working_sources_and_skip_unconfigured_ones(capsys, monkeypatch):
    monkeypatch.setattr(analysts, "_fetch", lambda sym: {"eps_jahr_aenderung_30d": 0.01})
    monkeypatch.setattr(social, "_fetch_ape", lambda max_pages=1: {"NVDA": {}})
    ok, out = run(capsys, monkeypatch, SEC_USER_AGENT="", QUIVER_TOKEN="", MCP_CONFIG="", MCP_TOOLS="")
    assert "[ OK ] Zusatzdaten Analysten: Yahoo liefert 1 Kennzahlen" in out and "[ OK ] Zusatzdaten Reddit: ApeWisdom liefert 1 Titel" in out
    assert "SEC-Insiderdaten" in out and "übersprungen" in out


def test_extras_probe_sec_and_quiver_when_configured(capsys, monkeypatch):
    monkeypatch.setattr(analysts, "_fetch", lambda sym: {"x": 1})
    monkeypatch.setattr(social, "_fetch_ape", lambda max_pages=1: {"A": {}})
    monkeypatch.setattr(edgar, "cik_map", lambda fetch=None: {"AAPL": "0000320193"})
    monkeypatch.setattr(edgar, "recent_form4", lambda *a, **k: [])
    monkeypatch.setattr(quiver, "_default_fetch", lambda path, token: [{"Transaction": "Purchase"}] if "AAPL" in path and token == "tok" else None)
    ok, out = run(capsys, monkeypatch, SEC_USER_AGENT="Max Muster max@example.org", QUIVER_TOKEN="tok", MCP_CONFIG="", MCP_TOOLS="")
    assert "[ OK ] Zusatzdaten SEC-Insider: SEC erreichbar, 1 Unternehmen" in out and "[ OK ] Zusatzdaten Quiver: Quiver antwortet (1 Zeilen" in out
    monkeypatch.setattr(quiver, "_default_fetch", lambda path, token: None)
    ok, out = run(capsys, monkeypatch, SEC_USER_AGENT="", QUIVER_TOKEN="tok", MCP_CONFIG="", MCP_TOOLS="")
    assert all(ok) and "[WARN] Zusatzdaten Quiver: Datensatz gehört nicht zum gebuchten Tarif" in out


def test_extras_flag_invalid_mcp_setting_as_warning(capsys, monkeypatch, tmp_path):
    monkeypatch.setattr(analysts, "_fetch", lambda sym: {"x": 1})
    monkeypatch.setattr(social, "_fetch_ape", lambda max_pages=1: {"A": {}})
    ok, out = run(capsys, monkeypatch, SEC_USER_AGENT="", QUIVER_TOKEN="", MCP_CONFIG=str(tmp_path / "fehlt.json"), MCP_TOOLS="mcp__liquid__place_order")
    assert all(ok) and "[WARN] Zusatzdaten MCP (nur lesen)" in out


def test_required_checks_still_fail_the_selftest():
    assert selftest.check("x", lambda: 1) is True
    assert selftest.check("x", lambda: 1 / 0) is False
    assert selftest.check("x", lambda: 1 / 0, optional=True) is True


@pytest.fixture(autouse=True)
def _quiet_pause(monkeypatch):
    monkeypatch.setattr(edgar, "PAUSE", 0)
