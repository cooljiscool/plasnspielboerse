import json
import os
import stat
from datetime import date

import pytest

from bot import brain, config, rules

UNI = {i: {"name": f"Titel {i}", "stars": 0} for i in "ABCDEFGHIJKLMN"}


def snapshot(**over):
    base = {i: {"price": 100.0, "ret_5d": 0.0, "ret_20d": 0.02, "ret_60d": 0.05 + k * 0.01, "vol_20d": 0.25}
            for k, i in enumerate(UNI)}
    base.update(over)
    return base


def pf(positions=None, cash=50000.0):
    return {"cash": cash, "positions": positions or {}, "buy_orders_executed": 0}


# --- Regelstrategie ---
def test_rules_buys_top_momentum_up_to_six_positions():
    out = rules.decide(pf(), UNI, snapshot(), 50000.0)
    buys = [o for o in out["orders"] if o["action"] == "buy"]
    assert [o["isin"] for o in buys] == ["N", "M", "L", "K", "J", "I"]
    assert all(o["amount_eur"] == round(50000 * 0.97 / 6) for o in buys)   # gleich gewichtet


def test_rules_skips_falling_and_wild_stocks():
    snap = snapshot(N={"price": 100.0, "ret_5d": 0, "ret_20d": -0.15, "ret_60d": 0.9, "vol_20d": 0.2},
                    M={"price": 100.0, "ret_5d": 0, "ret_20d": 0.05, "ret_60d": 0.8, "vol_20d": 0.9})
    picked = [o["isin"] for o in rules.decide(pf(), UNI, snap, 50000.0)["orders"]]
    assert "N" not in picked and "M" not in picked


def test_rules_stop_loss_and_hold():
    pos = {"A": {"shares": 50, "avg_price": 100.0, "bought": "2026-10-01"},
           "N": {"shares": 50, "avg_price": 100.0, "bought": "2026-10-01"}}
    snap = snapshot(A={"price": 70.0, "ret_5d": 0, "ret_20d": 0.01, "ret_60d": 0.2, "vol_20d": 0.2})
    orders = rules.decide(pf(pos), UNI, snap, 50000.0)["orders"]
    sells = {o["isin"]: o for o in orders if o["action"] == "sell"}
    assert sells["A"]["stop"] is True and "Notfall-Stopp" in sells["A"]["reason"]
    assert "N" not in sells  # Spitzenreiter bleibt


def test_rules_no_orders_without_data():
    assert rules.decide(pf(), UNI, {}, 50000.0)["orders"] == []


# --- Quellenwahl ---
def test_resolve_provider(monkeypatch):
    for k in ("CLAUDE_CODE_OAUTH_TOKEN", "ANTHROPIC_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr(config, "PROVIDER", "auto")
    assert brain.resolve_provider() == "rules"
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    assert brain.resolve_provider() == "api"
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "t")
    assert brain.resolve_provider() == "claude_cli"
    monkeypatch.setattr(config, "PROVIDER", "rules")
    assert brain.resolve_provider() == "rules"


def fake_claude(tmp_path, monkeypatch, body: str):
    exe = tmp_path / "claude"
    exe.write_text("#!/bin/sh\n" + body)
    exe.chmod(exe.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", f"{tmp_path}:{os.environ['PATH']}")


def run_decide():
    snap = snapshot()
    return brain.decide(pf(), UNI, snap, {}, date(2026, 10, 5), 50000.0)


def test_cli_provider_parses_structured_output_and_drops_api_key(tmp_path, monkeypatch):
    envfile = tmp_path / "env.txt"
    payload = json.dumps({"is_error": False, "structured_output": {
        "market_view": "gut", "orders": [{"action": "buy", "isin": "N", "amount_eur": 9000, "reason": "x"}]}})
    fake_claude(tmp_path, monkeypatch, f"cat >/dev/null\nenv | grep -c ANTHROPIC_API_KEY > {envfile}\necho '{payload}'\n")
    monkeypatch.setattr(config, "PROVIDER", "claude_cli")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-should-not-leak")
    out = run_decide()
    assert out["provider"] == "claude_cli" and out["orders"][0]["isin"] == "N" and "fallback_reason" not in out
    assert envfile.read_text().strip() == "0"  # API-Key wurde nicht an die CLI weitergegeben


def test_cli_failure_falls_back_to_rules(tmp_path, monkeypatch):
    fake_claude(tmp_path, monkeypatch, "cat >/dev/null\necho 'Login expired' >&2\nexit 1\n")
    monkeypatch.setattr(config, "PROVIDER", "claude_cli")
    out = run_decide()
    assert out["provider"] == "rules" and "claude_cli" in out["fallback_reason"] and out["orders"]


def test_cli_garbage_output_falls_back(tmp_path, monkeypatch):
    fake_claude(tmp_path, monkeypatch, "cat >/dev/null\necho 'kein json'\n")
    monkeypatch.setattr(config, "PROVIDER", "claude_cli")
    assert run_decide()["provider"] == "rules"


def test_cli_error_flag_falls_back(tmp_path, monkeypatch):
    fake_claude(tmp_path, monkeypatch, 'cat >/dev/null\necho \'{"is_error": true, "result": "Rate limit"}\'\n')
    monkeypatch.setattr(config, "PROVIDER", "claude_cli")
    out = run_decide()
    assert out["provider"] == "rules" and "Rate limit" in out["fallback_reason"]


def test_rules_hold_winners_and_sell_ranking_losers():
    pos = {"N": {"shares": 50, "avg_price": 100.0, "bought": "2026-10-01"},   # Rang 1 von 14
           "A": {"shares": 50, "avg_price": 100.0, "bought": "2026-10-01"}}   # Rang 14 von 14 (untere Hälfte)
    sells = {o["isin"] for o in rules.decide(pf(pos), UNI, snapshot(), 50000.0)["orders"] if o["action"] == "sell"}
    assert sells == {"A"}


def test_rules_defaults_follow_backtest():
    P = rules.PARAMS
    assert P["regime"] is False and P["trailing"] is False and P["vol_weight"] is False and P["trend_filter"] is False
    assert P["keep_frac"] == 0.7 and P["n_positions"] == 6 and P["vol_scale"] is True
    m = {"ret_5d": 0.5, "ret_20d": 0.5, "ret_60d": 0.1, "ret_120d": 0.3, "mom_12_1": 0.2, "vol_20d": 0.2}
    assert rules.score(m) == pytest.approx((0.1 + 0.3 + 0.2) / 3)   # kurzfristige Rendite zählt nicht
    assert rules.score({"ret_5d": 0, "ret_20d": 0, "ret_60d": 0.1, "vol_20d": 0.2}) == pytest.approx(0.1)   # Rückfall ohne Historie


def test_vol_scaling_reduces_exposure_only_in_wild_markets():
    assert rules.vol_scaled(0.12, 6, 50000.0) == (0.97, 6)                 # ruhiger Markt: voll investiert
    exp, n = rules.vol_scaled(0.40, 6, 50000.0)                             # Ziel 20 % / 40 % = halb investiert
    assert exp == pytest.approx(0.5) and n == 4 and n * 5500 <= 50000 * exp
    assert rules.vol_scaled(0.90, 6, 50000.0)[0] == rules.VOL_FLOOR         # nie unter 40 %
    assert rules.vol_scaled(None, 6, 50000.0) == (0.97, 6)


def test_rules_use_market_vol_from_regime():
    calm = rules.decide(pf(), UNI, snapshot(), 50000.0, {"label": "risk_on", "score": "5/5", "mkt_vol_60d": 0.10})
    wild = rules.decide(pf(), UNI, snapshot(), 50000.0, {"label": "risk_on", "score": "5/5", "mkt_vol_60d": 0.40})
    n_calm = sum(o["action"] == "buy" for o in calm["orders"])
    n_wild = sum(o["action"] == "buy" for o in wild["orders"])
    assert n_calm == 6 and n_wild == 4
    assert sum(o["amount_eur"] for o in wild["orders"]) <= 50000 * 0.5 + 1


def test_llm_context_contains_rules_baseline(monkeypatch):
    captured = {}
    monkeypatch.setattr(config, "PROVIDER", "claude_cli")
    monkeypatch.setattr(brain, "_decide_cli", lambda ctx: captured.update(ctx) or {"market_view": "", "orders": []})
    brain.decide(pf(), UNI, snapshot(), {}, date(2026, 10, 5), 50000.0)
    assert captured["quant_vorschlag"]["orders"] and "Regelstrategie" in captured["quant_vorschlag"]["market_view"]
