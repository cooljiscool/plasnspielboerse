import json
import os
import stat
import subprocess
import sys
import importlib.util

SPEC = importlib.util.spec_from_file_location("check_mcp_denial", os.path.join(os.path.dirname(__file__), "..", "scripts", "check_mcp_denial.py"))
script = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(script)


def rpc(proc, obj):
    proc.stdin.write(json.dumps(obj) + "\n")
    proc.stdin.flush()
    return json.loads(proc.stdout.readline())


def test_fake_server_lists_both_tools_and_logs_calls(tmp_path):
    server = tmp_path / "fake_server.py"
    server.write_text(script.SERVER)
    p = subprocess.Popen([sys.executable, str(server)], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    try:
        assert rpc(p, {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}})["result"]["serverInfo"]["name"] == "fake"
        assert [t["name"] for t in rpc(p, {"jsonrpc": "2.0", "id": 2, "method": "tools/list"})["result"]["tools"]] == ["get_price", "place_order"]
        assert "231.5" in rpc(p, {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "get_price", "arguments": {"symbol": "AAPL"}}})["result"]["content"][0]["text"]
    finally:
        p.stdin.close()
        p.wait(timeout=5)
    assert (tmp_path / "calls.log").read_text().split() == ["get_price"]


def fake_cli(tmp_path, called, denied):
    """Ein claude, das den Attrappen-Server nachahmt: protokolliert die genannten Aufrufe im Ordner der Konfiguration und meldet Ablehnungen."""
    exe = tmp_path / "claude"
    exe.write_text(f"""#!{sys.executable}
import json, os, sys
cfg = sys.argv[sys.argv.index("--mcp-config") + 1]
with open(os.path.join(os.path.dirname(cfg), "calls.log"), "w") as f:
    f.write("\\n".join({called!r}))
print(json.dumps({{"is_error": False, "permission_denials": [{{"tool_name": t}} for t in {denied!r}]}}))
""")
    exe.chmod(exe.stat().st_mode | stat.S_IEXEC)
    return str(exe)


def test_check_passes_only_when_write_tool_is_denied_and_read_tool_ran(tmp_path):
    ok, why = script.check(claude=fake_cli(tmp_path, ["get_price"], ["mcp__fake__place_order"]))
    assert ok and "abgelehnt" in why


def test_check_fails_loudly_if_the_write_tool_ran(tmp_path):
    ok, why = script.check(claude=fake_cli(tmp_path, ["get_price", "place_order"], []))
    assert not ok and "GEFAHR" in why


def test_check_is_inconclusive_if_read_tool_never_ran_or_no_denial_reported(tmp_path):
    ok, why = script.check(claude=fake_cli(tmp_path, [], []))
    assert not ok and "nicht aussagekräftig" in why
    ok, why = script.check(claude=fake_cli(tmp_path, ["get_price"], []))
    assert not ok and "nicht als abgelehnt gemeldet" in why


def test_check_reports_cli_failure(tmp_path):
    exe = tmp_path / "claude"
    exe.write_text("#!/bin/sh\necho 'Login expired' >&2\nexit 1\n")
    exe.chmod(exe.stat().st_mode | stat.S_IEXEC)
    ok, why = script.check(claude=str(exe))
    assert not ok and "Code 1" in why
