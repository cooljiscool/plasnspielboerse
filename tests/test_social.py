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


# --- Reddit über ApeWisdom ---
ROWS = {"NVDA": {"rank": 3, "ticker": "NVDA", "mentions": 120, "upvotes": 900, "rank_24h_ago": 5, "mentions_24h_ago": 100},
        "MU": {"rank": 60, "ticker": "MU", "mentions": 40, "upvotes": 50, "rank_24h_ago": 90, "mentions_24h_ago": 15},
        "F": {"rank": 200, "ticker": "F", "mentions": 4, "upvotes": 5, "rank_24h_ago": 210, "mentions_24h_ago": 3}}


def test_ape_summary_flags_top_ranks_and_mention_spikes():
    assert social.ape_summary(ROWS, "NVDA")["auffaellig"] is True                      # Rang 3
    mu = social.ape_summary(ROWS, "MU")
    assert mu["auffaellig"] is True and mu["erwaehnungen_24h"] == 40                    # mehr als verdoppelt
    assert social.ape_summary(ROWS, "F")["auffaellig"] is False
    assert social.ape_summary(ROWS, "ZZZ") == {}


def test_reddit_uses_us_titles_only_and_caches(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", str(tmp_path))
    calls = []
    fake = lambda wanted: calls.append(wanted) or ROWS  # noqa: E731
    uni = {"A": {"yf": "NVDA"}, "B": {"yf": "SAP.DE"}, "C": {"yf": "MU"}, "D": {"yf": "ZZZZ"}}
    out = social.reddit(uni, ["A", "B", "C", "D"], fake)
    assert set(out) == {"A", "C"} and calls == [{"NVDA", "MU", "ZZZZ"}]
    social.reddit(uni, ["A", "C"], fake)
    assert len(calls) == 1                                                             # zweiter Aufruf: Zwischenspeicher
    assert social.reddit({"B": {"yf": "SAP.DE"}}, ["B"], fake) == {}                    # keine US-Titel: gar kein Abruf
    assert len(calls) == 1


def test_reddit_failure_gives_empty_result(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", str(tmp_path))
    def broken(wanted):
        raise OSError("gesperrt")
    assert social.reddit({"A": {"yf": "NVDA"}}, ["A"], broken) == {}


def test_fetch_ape_stops_when_all_wanted_symbols_found(monkeypatch):
    pages = {1: {"pages": 3, "results": [{"ticker": "AAA", "rank": 1}]}, 2: {"pages": 3, "results": [{"ticker": "BBB", "rank": 101}]},
             3: {"pages": 3, "results": [{"ticker": "CCC", "rank": 201}]}}
    seen = []

    class R:
        def __init__(self, body): self.body = body
        def read(self): return json.dumps(self.body).encode()
    def fake_open(req, timeout):
        page = int(req.full_url.rsplit("/", 1)[1]); seen.append(page); return R(pages[page])
    monkeypatch.setattr(social.urllib.request, "urlopen", fake_open)
    rows = social._fetch_ape(wanted={"AAA", "BBB"})
    assert seen == [1, 2] and set(rows) == {"AAA", "BBB"}
