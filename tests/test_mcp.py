import json
import os
import stat
from datetime import date

import pytest

from bot import brain, config, mcp, research

LIQUID = {"mcpServers": {"liquid": {"type": "http", "url": "https://coinvest.liquid.trade/mcp"}}}


def write_cfg(tmp_path, cfg=None, name="mcp.json"):
    p = tmp_path / name
    p.write_text(json.dumps(LIQUID if cfg is None else cfg))
    return str(p)


@pytest.mark.parametrize("name", ["mcp__liquid__get_markets", "mcp__liquid__list_traders", "mcp__liquid__search_assets", "mcp__liquid__getMarkets",
                                  "mcp__liquid__get-open-positions", "mcp__my_server__describe_account_limits", "mcp__x1__query_price_history"])
def test_read_only_tool_names_are_accepted(name):
    assert mcp.check_tool(name) in ("liquid", "my_server", "x1")


@pytest.mark.parametrize("name", [
    "mcp__liquid__place_order", "mcp__liquid__create_order", "mcp__liquid__submit_trade", "mcp__liquid__close_position", "mcp__liquid__transfer_funds",
    "mcp__liquid__get_and_execute_trade", "mcp__liquid__list_then_buy", "mcp__liquid__getAndSellAll",      # Lese-Verb vorn, aber Handelswort darin
    "mcp__liquid__update_settings", "mcp__liquid__withdraw_usdc", "mcp__liquid__confirm_pending",
    "mcp__liquid__*", "mcp__liquid__get_*", "mcp__liquid", "mcp__liquid__get", "mcp__liquid__markets",       # Platzhalter, unvollständig, kein Lese-Verb
    "liquid__get_markets", "mcp__liquid__get__markets", "Bash", "WebSearch", "mcp__liquid__get_markets(*)", "mcp__li quid__get_x"])
def test_trading_wildcard_and_malformed_tool_names_are_rejected(name):
    with pytest.raises(mcp.McpError):
        mcp.check_tool(name)


def test_config_must_be_https_remote_servers_only(tmp_path):
    assert mcp.load_config(write_cfg(tmp_path))["mcpServers"]["liquid"]["type"] == "http"
    bad = [{"mcpServers": {"x": {"type": "stdio", "command": "rm", "args": ["-rf", "/"]}}},
           {"mcpServers": {"x": {"type": "http", "url": "http://coinvest.liquid.trade/mcp"}}},            # kein https
           {"mcpServers": {"x": {"type": "http", "url": "https://a.b/mcp", "command": "evil"}}},           # lokales Programm dazu
           {"mcpServers": {}}, {"servers": {}}, [], {"mcpServers": {"bad name": {"type": "http", "url": "https://a.b"}}}]
    for i, cfg in enumerate(bad):
        with pytest.raises(mcp.McpError):
            mcp.load_config(write_cfg(tmp_path, cfg, f"bad{i}.json"))
    with pytest.raises(mcp.McpError):
        mcp.load_config(str(tmp_path / "gibt-es-nicht.json"))


def test_setup_default_loads_no_servers_at_all():
    args, tools = mcp.setup("", "")
    assert tools == [] and args == ["--strict-mcp-config", "--mcp-config", '{"mcpServers": {}}']


def test_setup_with_config_uses_file_path_and_lists_exact_tools(tmp_path):
    path = write_cfg(tmp_path)
    args, tools = mcp.setup(path, "mcp__liquid__get_markets, mcp__liquid__list_traders")
    assert tools == ["mcp__liquid__get_markets", "mcp__liquid__list_traders"]
    assert args == ["--strict-mcp-config", "--mcp-config", os.path.abspath(path)]      # Datei statt Text: Zugangsdaten erscheinen nicht in der Prozessliste


def test_setup_rejects_half_configured_unknown_server_and_trade_tools(tmp_path):
    path = write_cfg(tmp_path)
    for cfg, tools in [(path, ""), ("", "mcp__liquid__get_markets"), (path, "mcp__anderer__get_markets"),
                       (path, "mcp__liquid__get_markets,mcp__liquid__place_order"), (path, "mcp__liquid__*")]:
        with pytest.raises(mcp.McpError):
            mcp.setup(cfg, tools)


# --- Anbindung an die Recherche und die Entscheidung ---
def fake_claude(tmp_path, monkeypatch, body):
    exe = tmp_path / "claude"
    exe.write_text("#!/bin/sh\n" + body)
    exe.chmod(exe.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", f"{tmp_path}:{os.environ['PATH']}")


PAYLOAD = json.dumps({"is_error": False, "structured_output": {"market": "m", "notes": [{"isin": "A", "sentiment": 0, "summary": "s"}]}})


def run_research(tmp_path, monkeypatch, mcp_config="", mcp_tools=""):
    monkeypatch.setattr(config, "DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setattr(config, "MCP_CONFIG", mcp_config)
    monkeypatch.setattr(config, "MCP_TOOLS", mcp_tools)
    args = tmp_path / "args.txt"
    fake_claude(tmp_path, monkeypatch, f"cat >/dev/null\nfor a in \"$@\"; do printf '%s\\0' \"$a\"; done > {args}\necho '{PAYLOAD}'\n")
    out = research.get({"A": {"name": "Alpha", "yf": "A"}}, ["A"], date(2026, 10, 5))
    return out, args.read_text().split("\0")[:-1]


def value_after(argv, flag):
    return argv[argv.index(flag) + 1]


def test_research_by_default_starts_no_mcp_server_and_allows_only_web_tools(tmp_path, monkeypatch):
    out, argv = run_research(tmp_path, monkeypatch)
    assert "error" not in out and "warning" not in out
    assert "--strict-mcp-config" in argv and json.loads(value_after(argv, "--mcp-config")) == {"mcpServers": {}}
    assert value_after(argv, "--allowedTools") == "WebSearch,WebFetch" and value_after(argv, "--permission-mode") == "dontAsk"


def test_research_allows_exactly_the_listed_read_tools_and_tells_claude(tmp_path, monkeypatch):
    path = write_cfg(tmp_path)
    out, argv = run_research(tmp_path, monkeypatch, path, "mcp__liquid__get_markets")
    assert "error" not in out and "warning" not in out
    assert value_after(argv, "--allowedTools") == "WebSearch,WebFetch,mcp__liquid__get_markets"
    assert value_after(argv, "--mcp-config") == os.path.abspath(path) and "--strict-mcp-config" in argv
    assert value_after(argv, "--tools") == "WebSearch,WebFetch"
    assert "mcp__liquid__get_markets" in value_after(argv, "--system-prompt") and "dürfen nur lesen" in value_after(argv, "--system-prompt")


def test_research_with_invalid_mcp_setting_runs_without_mcp_and_warns(tmp_path, monkeypatch):
    path = write_cfg(tmp_path)
    out, argv = run_research(tmp_path, monkeypatch, path, "mcp__liquid__place_order")
    assert out["notes"]["A"]["sentiment"] == 0 and "MCP ignoriert" in out["warning"] and "place" in out["warning"]
    assert value_after(argv, "--allowedTools") == "WebSearch,WebFetch" and json.loads(value_after(argv, "--mcp-config")) == {"mcpServers": {}}


def test_decision_call_never_loads_mcp_servers_even_if_research_has_them(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "MCP_CONFIG", write_cfg(tmp_path))
    monkeypatch.setattr(config, "MCP_TOOLS", "mcp__liquid__get_markets")
    monkeypatch.setattr(config, "PROVIDER", "claude_cli")
    args = tmp_path / "args.txt"
    payload = json.dumps({"is_error": False, "structured_output": {"market_view": "x", "orders": []}})
    fake_claude(tmp_path, monkeypatch, f"cat >/dev/null\nfor a in \"$@\"; do printf '%s\\0' \"$a\"; done > {args}\necho '{payload}'\n")
    out = brain._decide_cli({"heute": "2026-10-05"})
    argv = args.read_text().split("\0")[:-1]
    assert out["orders"] == [] and json.loads(value_after(argv, "--mcp-config")) == {"mcpServers": {}} and "--strict-mcp-config" in argv
    assert value_after(argv, "--tools") == "" and "mcp__" not in " ".join(argv)


def test_module_documents_the_read_only_rule_and_the_read_scope():
    assert "read" in mcp.__doc__ and "trade" in mcp.__doc__ and "dontAsk" in mcp.__doc__
