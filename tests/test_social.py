import json

from bot import brain, config, social


def payload(bull, bear, untagged=0, watch=1000):
    msgs = ([{"entities": {"sentiment": {"basic": "Bullish"}}, "created_at": "2026-09-29T20:00:00Z"}] * bull
            + [{"entities": {"sentiment": {"basic": "Bearish"}}, "created_at": "2026-09-29T19:00:00Z"}] * bear
            + [{"entities": {}, "created_at": "2026-09-29T18:00:00Z"}] * untagged)
    return {"symbol": {"watchlist_count": watch}, "messages": msgs}


def test_us_symbol_detection():
    assert social.us_symbol("NVDA") and social.us_symbol("F") and social.us_symbol("GOOGL")
    assert not any(social.us_symbol(s) for s in ("SAP.DE", "MC.PA", "^GDAXI", "", None, "BRK-B", "1U1.DE"))


def test_summarize_counts_and_labels():
    s = social.summarize(payload(8, 2, 20))
    assert s["beitraege"] == 30 and s["bullish"] == 8 and s["bearish"] == 2 and s["bullish_anteil"] == 0.8
    assert s["stimmung"] == "überwiegend positiv" and s["beobachter"] == 1000 and s["zeitspanne_stunden"] == 2.0
    assert social.summarize(payload(2, 8))["stimmung"] == "überwiegend negativ"
    assert social.summarize(payload(5, 5))["stimmung"] == "gemischt"


def test_summarize_needs_enough_tagged_posts_and_passes_no_text():
    few = social.summarize(payload(2, 1, 20))
    assert "bullish_anteil" not in few and few["beitraege"] == 23
    assert social.summarize({}) == {} and social.summarize({"messages": []}) == {}
    assert "body" not in json.dumps(social.summarize(payload(8, 2)))   # Fremdtext der Beiträge wird nie weitergegeben


def test_get_only_us_titles_caches_and_survives_errors(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", str(tmp_path))
    uni = {"A": {"yf": "NVDA"}, "B": {"yf": "SAP.DE"}, "C": {"yf": "AAPL"}, "D": {"yf": "TSLA"}}
    calls = []

    def fake(sym):
        calls.append(sym)
        if sym == "TSLA":
            raise OSError("gesperrt")
        return {"beitraege": 30, "bullish": 9, "bearish": 1, "bullish_anteil": 0.9, "stimmung": "überwiegend positiv"}
    out = social.get(uni, ["A", "B", "C", "D"], fake)
    assert set(out) == {"A", "C"} and sorted(calls) == ["AAPL", "NVDA", "TSLA"]     # deutsche Titel übersprungen, Fehler geschluckt
    social.get(uni, ["A", "C"], fake)
    assert len(calls) == 3                                                          # zweiter Aufruf: Zwischenspeicher
    # nach Ablauf der Frist wird neu abgefragt
    cache = json.load(open(tmp_path / "social.json")); cache["time"] -= 4 * 3600
    json.dump(cache, open(tmp_path / "social.json", "w"))
    social.get(uni, ["A"], fake)
    assert len(calls) == 4


def test_prompt_mentions_social_as_neutral_information():
    assert "StockTwits" in brain.SYSTEM and "Weder Kaufgrund noch Veto-Grund" in brain.SYSTEM
