import json
import os
import stat
import sys
from datetime import date

from bot import config, research

UNI = {f"T{i}": {"name": f"Titel {i}", "yf": f"T{i}"} for i in range(7)}
TODAY = date(2026, 10, 5)


def fake_claude(tmp_path, monkeypatch, skip=(), fail=()):
    """Ein claude, das für jeden Titel der Eingabe eine Notiz liefert (außer skip) und bei einem Titel aus fail scheitert. Protokolliert die Pakete."""
    log = tmp_path / "calls.log"
    exe = tmp_path / "claude"
    exe.write_text(f"""#!{sys.executable}
import json, sys
items = json.load(sys.stdin)
ids = [i["isin"] for i in items]
open({str(log)!r}, "a").write(json.dumps(ids) + "\\n")
if set(ids) & set({list(fail)!r}):
    sys.stderr.write("Limit erreicht"); sys.exit(1)
notes = [{{"isin": i, "sentiment": 1, "summary": "Nachricht zu " + i}} for i in ids if i not in {list(skip)!r}]
print(json.dumps({{"is_error": False, "total_cost_usd": 0.05, "duration_ms": 20400, "num_turns": 4,
                  "structured_output": {{"market": "Markt " + ids[0], "macro_view": "Makro " + ids[0], "notes": notes}}}}))
""")
    exe.chmod(exe.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", f"{tmp_path}:{os.environ['PATH']}")
    return lambda: [json.loads(x) for x in log.read_text().splitlines()] if log.exists() else []


def setup(tmp_path, monkeypatch, batch=3):
    monkeypatch.setattr(config, "DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setattr(config, "RESEARCH_BATCH", batch)


def test_titles_are_researched_in_small_batches_and_merged(tmp_path, monkeypatch):
    setup(tmp_path, monkeypatch)
    calls = fake_claude(tmp_path, monkeypatch)
    out = research.get(UNI, list(UNI), TODAY)
    assert calls() == [["T0", "T1", "T2"], ["T3", "T4", "T5"], ["T6"]]
    assert set(out["notes"]) == set(UNI) and "error" not in out
    assert out["market"] == "Markt T0" and out["macro"] == "Makro T0"        # Marktlage aus dem ersten Paket


def test_failing_batch_keeps_earlier_results_and_next_run_only_asks_for_missing_titles(tmp_path, monkeypatch):
    setup(tmp_path, monkeypatch)
    calls = fake_claude(tmp_path, monkeypatch, fail=["T4"])
    out = research.get(UNI, list(UNI), TODAY)
    assert set(out["notes"]) == {"T0", "T1", "T2"} and "Limit erreicht" in out["error"]
    assert calls() == [["T0", "T1", "T2"], ["T3", "T4", "T5"]]                              # zweites Paket scheitert, drittes wird gar nicht erst versucht
    fake_claude(tmp_path, monkeypatch)                                                      # Limit wieder frei
    out = research.get(UNI, list(UNI), TODAY)
    assert calls()[2:] == [["T3", "T4", "T5"], ["T6"]] and set(out["notes"]) == set(UNI) and "error" not in out
    assert research.get(UNI, list(UNI), TODAY)["cached"] is True and len(calls()) == 4      # danach ist alles im Zwischenspeicher


def test_omitted_titles_get_a_placeholder_and_are_not_asked_again_today(tmp_path, monkeypatch):
    setup(tmp_path, monkeypatch, batch=4)
    calls = fake_claude(tmp_path, monkeypatch, skip=["T1"])
    out = research.get(UNI, ["T0", "T1", "T2"], TODAY)
    assert "keine Angabe" in out["notes"]["T1"]["summary"] and out["notes"]["T0"]["summary"] == "Nachricht zu T0"
    assert out["notes"]["T1"].get("sentiment") is None                                       # kein erfundener Befund
    research.get(UNI, ["T0", "T1", "T2"], TODAY)
    assert len(calls()) == 1


def test_cache_from_yesterday_is_ignored(tmp_path, monkeypatch):
    setup(tmp_path, monkeypatch)
    calls = fake_claude(tmp_path, monkeypatch)
    research.get(UNI, ["T0"], date(2026, 10, 4))
    research.get(UNI, ["T0"], TODAY)
    assert len(calls()) == 2


def test_batch_size_is_configurable_and_at_least_one(tmp_path, monkeypatch):
    setup(tmp_path, monkeypatch, batch=1)
    calls = fake_claude(tmp_path, monkeypatch)
    research.get(UNI, ["T0", "T1"], TODAY)
    assert calls() == [["T0"], ["T1"]]
    monkeypatch.setenv("BOT_RESEARCH_BATCH", "0")
    import importlib
    try:
        assert importlib.reload(config).RESEARCH_BATCH == 1
    finally:
        monkeypatch.delenv("BOT_RESEARCH_BATCH")
        importlib.reload(config)


def test_prompt_demands_a_search_per_title():
    assert "mindestens eine eigene Websuche" in research.SYSTEM and "Keine belastbaren Nachrichten" in research.SYSTEM


def test_usage_of_all_batches_is_summed_and_cached_runs_use_nothing(tmp_path, monkeypatch):
    setup(tmp_path, monkeypatch)
    fake_claude(tmp_path, monkeypatch)
    out = research.get(UNI, list(UNI), TODAY)
    assert out["verbrauch"] == {"aufrufe": 3, "kosten_usd": 0.15, "dauer_s": 60, "runden": 12}
    assert "verbrauch" not in research.get(UNI, list(UNI), TODAY)


def test_usage_tolerates_missing_fields():
    assert research.usage({}) == {"kosten_usd": 0.0, "dauer_s": 0, "runden": 0}
    assert research.usage({"total_cost_usd": None, "duration_ms": "1500", "num_turns": 2}) == {"kosten_usd": 0.0, "dauer_s": 2, "runden": 2}
