import json
from datetime import date

from bot import config, quiver

TODAY = date(2026, 9, 29)


def test_summarize_congress_recent_only():
    rows = [{"Representative": "A", "Transaction": "Purchase", "TransactionDate": "2026-09-10"},
            {"Representative": "B", "Transaction": "Purchase", "TransactionDate": "2026-08-20"},
            {"Representative": "B", "Transaction": "Sale (Partial)", "TransactionDate": "2026-09-01"},
            {"Representative": "C", "Transaction": "Purchase", "TransactionDate": "2025-01-01"}]        # zu alt
    assert quiver.summarize("kongress", rows, TODAY) == {"kaeufe_90d": 2, "kaeufer": 2, "verkaeufe_90d": 1, "verkaeufer": 1}
    assert quiver.summarize("kongress", [{"Transaction": "Purchase", "TransactionDate": "2020-01-01"}], TODAY) == {}


def test_summarize_amounts_wikipedia_and_dark_pool():
    gov = [{"Date": "2026-06-30", "Amount": "1,500,000"}, {"Date": "2026-03-31", "Amount": 500000}, {"Date": "2024-03-31", "Amount": 9e9}]
    assert quiver.summarize("regierung", gov, TODAY) == {"summe_12m_usd": 2000000, "eintraege_12m": 2}
    wiki = [{"Date": f"2026-09-{d:02d}", "Views": 200} for d in range(16, 29)] + [{"Date": f"2026-09-{d:02d}", "Views": 100} for d in range(1, 14)]
    w = quiver.summarize("wikipedia", wiki, TODAY)
    assert w["aufrufe_14d_schnitt"] == 200 and w["veraenderung_zu_vorher"] == 1.0
    assert quiver.summarize("leerverkauf", [{"Date": "2026-09-28", "DPI": 0.52}, {"Date": "2026-09-27", "DPI": 0.48}], TODAY) == {"dark_pool_index_10d": 0.5}


def test_summarize_tolerates_unknown_shapes():
    for name in quiver.PATHS:
        assert quiver.summarize(name, None, TODAY) == {} and quiver.summarize(name, [], TODAY) == {}
        assert quiver.summarize(name, [{"irgendwas": 1}, "text", 5], TODAY) == {}
    assert quiver.summarize("unbekannt", [{"a": 1}], TODAY) == {}


def test_get_without_token_does_nothing(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", str(tmp_path))
    boom = lambda *a: (_ for _ in ()).throw(AssertionError("darf nicht abgerufen werden"))  # noqa: E731
    assert quiver.get({"A": {"yf": "NVDA"}}, ["A"], TODAY, token="", fetch=boom) == ({}, None)


def test_get_fetches_us_titles_caches_and_skips_datasets_outside_plan(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", str(tmp_path))
    calls = []

    def fetch(path, token):
        calls.append(path)
        assert token == "geheim"
        if "congress" in path:
            return [{"Representative": "A", "Transaction": "Purchase", "TransactionDate": "2026-09-10"}]
        if "lobbying" in path:
            return None                                                    # nicht im Tarif
        return []
    uni = {"A": {"yf": "NVDA"}, "B": {"yf": "SAP.DE"}}
    data, err = quiver.get(uni, ["A", "B"], TODAY, "geheim", fetch)
    assert err is None and data == {"A": {"kongress": {"kaeufe_90d": 1, "kaeufer": 1, "verkaeufe_90d": 0, "verkaeufer": 0}}}
    assert all(p.endswith("/NVDA") for p in calls) and len(calls) == len(quiver.PATHS)          # deutsche Titel werden nicht abgefragt
    quiver.get(uni, ["A", "B"], TODAY, "geheim", fetch)
    assert len(calls) == len(quiver.PATHS)                                                        # Zwischenspeicher


def test_get_reports_rejected_key_and_stops(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", str(tmp_path))
    calls = []

    def fetch(path, token):
        calls.append(path)
        raise quiver.AuthError("HTTP 403")
    data, err = quiver.get({"A": {"yf": "NVDA"}, "B": {"yf": "AMD"}}, ["A", "B"], TODAY, "falsch", fetch)
    assert data == {} and "lehnt den Schlüssel ab" in err and len(calls) == 1                     # nach dem ersten Fehler kein weiterer Abruf


def test_get_survives_single_dataset_error(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", str(tmp_path))

    def fetch(path, token):
        raise OSError("Zeitüberschreitung")
    data, err = quiver.get({"A": {"yf": "NVDA"}}, ["A"], TODAY, "x", fetch)
    assert data == {} and "gescheitert" in err


def test_default_fetch_sends_token_header_and_detects_upgrade_notice(monkeypatch):
    seen = {}

    class R:
        def __init__(self, body): self.body = body
        def read(self): return self.body.encode()
    def fake_open(req, timeout):
        seen["auth"], seen["url"] = req.get_header("Authorization"), req.full_url
        return R(seen.get("body", "[]"))
    monkeypatch.setattr(quiver.urllib.request, "urlopen", fake_open)
    monkeypatch.setattr(quiver.time, "sleep", lambda s: None)
    assert quiver._default_fetch("/historical/lobbying/NVDA", "tok") == []
    assert seen["auth"] == "Token tok" and seen["url"] == "https://api.quiverquant.com/beta/historical/lobbying/NVDA"
    seen["body"] = json.dumps("Upgrade your subscription plan to access this dataset.")
    assert quiver._default_fetch("/x", "tok") is None
