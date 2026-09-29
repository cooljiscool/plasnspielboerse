import json
from datetime import date

from bot import config, edgar


def form4(owner="Jane Doe", title="Chief Executive Officer", planned=False, txns=()):
    rows = "".join(f"""<nonDerivativeTransaction><securityTitle><value>Common Stock</value></securityTitle>
        <transactionDate><value>{d}</value></transactionDate>
        <transactionCoding><transactionFormType>4</transactionFormType><transactionCode>{code}</transactionCode><equitySwapInvolved>0</equitySwapInvolved></transactionCoding>
        <transactionAmounts><transactionShares><value>{sh}</value></transactionShares><transactionPricePerShare><value>{px}</value></transactionPricePerShare>
        <transactionAcquiredDisposedCode><value>{'A' if code == 'P' else 'D'}</value></transactionAcquiredDisposedCode></transactionAmounts>
        </nonDerivativeTransaction>""" for d, code, sh, px in txns)
    return f"""<?xml version="1.0"?><ownershipDocument><schemaVersion>X0609</schemaVersion><documentType>4</documentType>
    <issuer><issuerCik>0000002488</issuerCik><issuerTradingSymbol>TEST</issuerTradingSymbol></issuer>
    <reportingOwner><reportingOwnerId><rptOwnerCik>1</rptOwnerCik><rptOwnerName>{owner}</rptOwnerName></reportingOwnerId>
    <reportingOwnerRelationship><isDirector>0</isDirector><isOfficer>1</isOfficer><isTenPercentOwner>0</isTenPercentOwner><officerTitle>{title}</officerTitle></reportingOwnerRelationship></reportingOwner>
    <aff10b5One>{1 if planned else 0}</aff10b5One><nonDerivativeTable>{rows}</nonDerivativeTable></ownershipDocument>"""


def test_parse_form4_purchase_and_planned_sale():
    xml = form4(txns=[("2026-09-10", "P", "1000", "50.0"), ("2026-09-11", "S", "200", "51.5")], planned=True)
    t = edgar.parse_form4(xml)
    assert len(t) == 2 and t[0]["code"] == "P" and t[0]["aktien"] == 1000 and t[0]["preis"] == 50.0
    assert t[0]["insider"] == "Jane Doe" and t[0]["rolle"] == "Chief Executive Officer" and t[1]["geplant"] is True
    assert t[1]["richtung"] == "D"


def test_parse_form4_rejects_hostile_or_broken_xml():
    assert edgar.parse_form4("<ownershipDocument><unclosed>") == []
    assert edgar.parse_form4('<!DOCTYPE x [<!ENTITY a "aaaa">]><ownershipDocument>&a;</ownershipDocument>') == []
    assert edgar.parse_form4("x" * (edgar.MAX_XML_BYTES + 1)) == []
    assert edgar.parse_form4(form4(txns=[("2026-09-10", "M", "abc", "1")])) == []          # unlesbare Stückzahl wird übersprungen


def tx(day, code, insider, shares=1000, price=10.0, planned=False, role="CEO"):
    return {"datum": day, "code": code, "aktien": shares, "preis": price, "insider": insider, "rolle": role, "geplant": planned, "richtung": "A"}


def test_summary_detects_cluster_of_open_market_buys():
    s = edgar.summarize([tx("2026-09-01", "P", "A", 100, 10), tx("2026-09-20", "P", "B", 200, 10, role="CFO"), tx("2026-09-21", "S", "C", planned=True)])
    assert s["kaeufe"] == 2 and s["kaeufer"] == 2 and s["kaufvolumen_usd"] == 3000 and s["cluster_kauf"] is True
    assert "Cluster" in s["signal"] and s["verkaeufe_geplant_10b5_1"] == 1 and s["letzter_kauf"] == "2026-09-20"


def test_summary_no_cluster_for_single_buyer_or_far_apart_buys():
    assert edgar.summarize([tx("2026-09-01", "P", "A"), tx("2026-09-05", "P", "A")])["cluster_kauf"] is False
    far = edgar.summarize([tx("2026-07-01", "P", "A"), tx("2026-09-20", "P", "B")])
    assert far["cluster_kauf"] is False and far["signal"] == "Insider-Kauf am offenen Markt"


def test_summary_sales_only_and_irrelevant_codes():
    planned = edgar.summarize([tx("2026-09-01", "S", "A", planned=True), tx("2026-09-02", "S", "B", planned=True), tx("2026-09-03", "S", "C")])
    assert planned["kaeufe"] == 0 and "geplant" in planned["signal"]
    unplanned = edgar.summarize([tx("2026-09-01", "S", "A"), tx("2026-09-02", "S", "B")])
    assert "ohne Plan" in unplanned["signal"]
    assert edgar.summarize([tx("2026-09-01", "M", "A"), tx("2026-09-01", "A", "B"), tx("2026-09-01", "F", "C")]) == {}   # Grants, Optionen, Steuerabzug zählen nicht


def make_fetch(pages):
    calls = []

    def fetch(url):
        calls.append(url)
        for key, body in pages.items():
            if key in url:
                return body
        raise OSError("nicht gefunden: " + url)
    fetch.calls = calls
    return fetch


SUBMISSIONS = json.dumps({"filings": {"recent": {
    "form": ["4", "8-K", "4", "4"], "filingDate": ["2026-09-25", "2026-09-24", "2026-09-10", "2025-01-01"],
    "accessionNumber": ["0000002488-26-000001", "0000002488-26-000002", "0000002488-26-000003", "0000002488-25-000009"],
    "primaryDocument": ["xslF345X06/wk-form4_a.xml", "x.htm", "xslF345X05/wk-form4_b.xml", "xslF345X05/old.xml"]}}})


def test_recent_form4_filters_by_form_and_date_and_strips_stylesheet_folder():
    fetch = make_fetch({"submissions/CIK0000002488": SUBMISSIONS,
                        "/000000248826000001/wk-form4_a.xml": form4(txns=[("2026-09-24", "P", "100", "10")]),
                        "/000000248826000003/wk-form4_b.xml": form4(owner="Max", txns=[("2026-09-09", "P", "50", "11")])})
    out = edgar.recent_form4("0000002488", date(2026, 9, 29), fetch=fetch)
    assert {t["insider"] for t in out} == {"Jane Doe", "Max"} and len(out) == 2
    urls = " ".join(fetch.calls)
    assert "xslF345" not in urls and "old.xml" not in urls and "x.htm" not in urls        # Rohdatei, kein 8-K, keine alte Meldung
    assert "/data/2488/" in urls                                                          # CIK ohne führende Nullen


def test_recent_form4_survives_one_broken_filing():
    fetch = make_fetch({"submissions/": SUBMISSIONS, "/000000248826000003/": form4(txns=[("2026-09-09", "P", "5", "1")])})   # erste Meldung fehlt
    assert len(edgar.recent_form4("0000002488", date(2026, 9, 29), fetch=fetch)) == 1


def test_get_caches_skips_non_us_and_missing_cik(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", str(tmp_path))
    fetch = make_fetch({"company_tickers": json.dumps({"0": {"cik_str": 2488, "ticker": "TEST", "title": "Test Inc"}}),
                        "submissions/CIK0000002488": SUBMISSIONS,
                        "/000000248826000001/": form4(txns=[("2026-09-24", "P", "100", "10")]),
                        "/000000248826000003/": form4(owner="Max", txns=[("2026-09-09", "P", "50", "11")])})
    uni = {"A": {"yf": "TEST"}, "B": {"yf": "SAP.DE"}, "C": {"yf": "NIX"}}
    out = edgar.get(uni, ["A", "B", "C"], date(2026, 9, 29), fetch)
    assert list(out) == ["A"] and out["A"]["kaeufer"] == 2
    n = len(fetch.calls)
    edgar.get(uni, ["A", "B", "C"], date(2026, 9, 29), fetch)
    assert len(fetch.calls) == n                                                            # zweiter Aufruf am selben Tag: Zwischenspeicher
    assert (tmp_path / "cache" / "sec_tickers.json").exists()
