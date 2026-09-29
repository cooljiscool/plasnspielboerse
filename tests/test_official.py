import json

import pytest

from bot import fx, official


@pytest.fixture(autouse=True)
def _no_pause(monkeypatch):
    monkeypatch.setattr(official, "SEARCH_PAUSE", 0)

LIST = """Planspiel Börse 2026 - Handelbare Wertpapiere

(Stand: 14.09.2026 -- Änderungen vorbehalten)

                                                                                             Börse       NH*
       Wertpapierart / Index / Titel                              Kennzeichnung
                                                                                             Land        Wertung
I      Aktien (aus Index) -- siehe Components
       DAX 40                                                     gelistete Wertpapiere in   Stuttgart
       Global Challenges Index 50                                 gelistete Wertpapiere in   Stuttgart      X
II     Fonds
       DEKAFONDS CF                                               DE0008474503               Stuttgart
       DEKA-ESG BASISSTR.REN.CF                                   DE0005896872               Stuttgart      X
V      Kryptowährungen (Handel im Trainingsdepot)
       Austauschkurs Bitcoin/Euro                                 EU000A2YZK67

Components

       DAX

      1 ADIDAS AG NA O.N.                                        DE000A1EWWW0
      2 AIRBUS GROUP                                             NL0000235190
      3 KAPUTT AG                                                DE000A1EWWW9

                                                Seite 2 von 19
Planspiel Börse 2026 - Handelbare Wertpapiere

(Stand: 14.09.2026 -- Änderungen vorbehalten)

                                                                                 Börse   NH*
       Wertpapierart / Index / Titel                             Kennzeichnung
                                                                                 Land    Wertung
      4 ALLIANZ                                                  DE0008404005

       EuroStoxx50

    1 AIRBUS GROUP                                               NL0000235190
    2 NORDEA BANK ABP                                            FI4000297767

       Selection Europe (Auswahl aus Stoxx Europe 600)

    1 KESKO B                                                    FI0009000202    Finnland
    2 NORDEA BANK ABP                                            FI4000297767    Schweden
    3 HENNES + MAURITZ B SK-125                                  SE0000106270    Schweden

       Nasdaq100




                                                Seite 10 von 19
Planspiel Börse 2026 - Handelbare Wertpapiere

    1 APPLE                                                      US0378331005
    2 SHOPIFY A SUB.VTG                                          CA82509L1076

       Global Challenges

    1 AURUBIS                                                    DE0006766504               X
   45 STMICROELECTRONICS                                         NL0000226223                  X
*Nachhaltigkeit

       ETC

       AMUNDI PHYSICAL GOLD ETC                                  FR0013416716
    9 BNP GOLD                                                   DE000PS7G0L8
"""


def by_isin(entries):
    return {e["isin"]: e for e in entries}


@pytest.mark.parametrize("isin", ["DE000A1EWWW0", "US0378331005", "AT0000BAWAG2", "FI4000297767", "NL0000235190", "JP3973400009", "BG1100003166"])
def test_valid_isins(isin):
    assert official.valid_isin(isin)


@pytest.mark.parametrize("isin", ["DE000A1EWWW9", "US0378331006", "de000a1ewww0", "DE000A1EWWW", "", None, "DE000A1EWWW00"])
def test_invalid_isins(isin):
    assert not official.valid_isin(isin)


def test_parse_reads_index_components_across_page_breaks_and_ignores_the_rest():
    e = by_isin(official.parse(LIST))
    assert set(e) == {"DE000A1EWWW0", "NL0000235190", "DE0008404005", "FI4000297767", "FI0009000202", "SE0000106270", "US0378331005", "CA82509L1076",
                      "DE0006766504", "NL0000226223"}
    assert e["DE000A1EWWW0"]["indices"] == ["dax"] and e["DE0008404005"]["indices"] == ["dax"]         # Zeile nach dem Seitenumbruch gehört noch zum DAX
    assert e["US0378331005"]["indices"] == ["nasdaq100"]                                                # Überschrift am Seitenende, Zeilen auf der nächsten Seite
    assert "DE0008474503" not in e and "FR0013416716" not in e and "DE000PS7G0L8" not in e            # Fonds, ETC: nicht Teil der Index-Listen
    assert "DE000A1EWWW9" not in e                                                                      # ungültige Prüfziffer


def test_parse_merges_titles_in_several_indices_and_reads_country_and_star():
    e = by_isin(official.parse(LIST))
    assert e["NL0000235190"]["indices"] == ["dax", "eurostoxx50"]
    n = e["FI4000297767"]
    assert n["indices"] == ["eurostoxx50", "europa"] and n["land"] == "Schweden"
    assert e["FI0009000202"]["land"] == "Finnland" and e["FI0009000202"]["stars"] == 0
    assert e["DE0006766504"]["stars"] == 1 and e["DE0006766504"]["indices"] == ["gci"] and e["NL0000226223"]["stars"] == 1   # X in der Spalte Nachhaltigkeit


def test_groups_for_the_evaluation():
    assert official.group_of(["dax", "eurostoxx50"], "DE000A1EWWW0") == "dax"
    assert official.group_of(["tecdax", "sdax"], "DE0005089031") == "sdax"
    assert official.group_of(["nasdaq100"], "US0378331005") == "us" and official.group_of(["dow"], "US88579Y1010") == "us"
    assert official.group_of(["gci"], "US9078181081") == "us" and official.group_of(["gci"], "DE0006766504") == "europa"
    assert official.group_of(["europa", "eurostoxx50"], "FR0000120073") == "europa"


def q(sym, typ="EQUITY", **kw):
    return {"symbol": sym, "quoteType": typ, **kw}


def test_pick_symbol_prefers_the_home_exchange_of_the_isin():
    assert official.pick_symbol("DE0005190003", [q("BMW.F"), q("BMW.DE")])["symbol"] == "BMW.DE"
    assert official.pick_symbol("US0378331005", [q("APC.DE"), q("AAPL")])["symbol"] == "AAPL"
    assert official.pick_symbol("NL0000235190", [q("AIR.PA"), q("AIR.DE")])["symbol"] == "AIR.PA"      # Niederländische ISIN, Notiz in Paris
    assert official.pick_symbol("SE0000106270", [q("HM-B.ST")])["symbol"] == "HM-B.ST"
    assert official.pick_symbol("JP3973400009", [q("7752.T")])["symbol"] == "7752.T"


def test_pick_symbol_falls_back_to_euro_exchanges_and_ignores_non_equities():
    assert official.pick_symbol("LU0088087324", [q("SESG.PA")])["symbol"] == "SESG.PA"
    assert official.pick_symbol("XX0000000000", [q("ABC.ZZ"), q("ABC.DE")])["symbol"] == "ABC.DE"      # unbekannte Endung: Euro-Börse
    assert official.pick_symbol("DE0005190003", [q("BMW", "ETF"), q("BMW.DE", "FUTURE")]) is None
    assert official.pick_symbol("DE0005190003", []) is None
    assert official.pick_symbol("XX0000000000", [q("ABC.ZZ")]) is None                                   # keine bekannte Währung: nicht raten


def test_resolve_one_by_isin_uses_long_name_and_asks_currency_only_outside_the_euro_area():
    asked = []
    search = lambda query: [q("HM-B.ST", longname="H & M Hennes & Mauritz AB (publ)")] if query == "SE0000106270" else []      # noqa: E731
    r = official.resolve_one({"isin": "SE0000106270", "name": "HENNES + MAURITZ B SK-125"}, search, lambda s: asked.append(s) or "SEK")
    assert r == {"yf": "HM-B.ST", "currency": "SEK", "name": "H & M Hennes & Mauritz AB (publ)"} and asked == ["HM-B.ST"]
    asked.clear()
    r = official.resolve_one({"isin": "DE000A1EWWW0", "name": "ADIDAS"}, lambda x: [q("ADS.DE", shortname="adidas AG")], lambda s: asked.append(s) or "EUR")
    assert r["currency"] == "EUR" and asked == []                                                        # .DE bedeutet immer Euro
    r = official.resolve_one({"isin": "US0378331005", "name": "APPLE"}, lambda x: [q("AAPL", shortname="Apple Inc.")], lambda s: asked.append(s) or "USD")
    assert r["currency"] == "USD" and asked == []                                                        # US-Symbol: Dollar, keine Abfrage
    r = official.resolve_one({"isin": "GB0006776081", "name": "PEARSON"}, lambda x: [q("PSON.L", shortname="Pearson plc")], lambda s: "GBp")
    assert r["currency"] == "GBp"
    r = official.resolve_one({"isin": "GB0006776081", "name": "PEARSON"}, lambda x: [q("PSON.L", shortname="Pearson plc")], lambda s: 1 / 0)
    assert r["currency"] == "GBp"                                                                        # Abfrage scheitert: Währung aus der Endung


def test_resolve_one_falls_back_to_the_name_but_only_with_home_exchange_and_plausible_name():
    def search(query):
        if query == "FI0009000202":
            return []
        return [q("KESKOB.HE", shortname="Kesko Oyj", longname="Kesko Oyj"), q("KES.F", shortname="Kesko")]
    r = official.resolve_one({"isin": "FI0009000202", "name": "KESKO B"}, search, lambda s: "EUR")
    assert r["yf"] == "KESKOB.HE"
    wrong = lambda query: [] if query.startswith("FI") else [q("NOKIA.HE", shortname="Nokia Oyj")]      # noqa: E731
    assert official.resolve_one({"isin": "FI0009000202", "name": "KESKO B"}, wrong, lambda s: "EUR") is None          # anderes Unternehmen: nicht raten
    other = lambda query: [] if query.startswith("FI") else [q("KESKO.ST", shortname="Kesko")]           # noqa: E731
    assert official.resolve_one({"isin": "FI0009000202", "name": "KESKO B"}, other, lambda s: "SEK") is None         # falsche Börse für das Land


def test_resolve_caches_successes_only_and_retries_failures(tmp_path):
    entries = [{"isin": "DE000A1EWWW0", "name": "ADIDAS", "indices": ["dax"], "stars": 0}, {"isin": "FI0009000202", "name": "KESKO B", "indices": ["europa"], "stars": 0},
               {"isin": "SE0000106270", "name": "H&M", "indices": ["europa"], "stars": 0}]
    calls = []

    def search(query):
        calls.append(query)
        if query == "SE0000106270":
            raise RuntimeError("Yahoo down")
        return [q("ADS.DE", longname="adidas AG")] if query == "DE000A1EWWW0" else []
    path = str(tmp_path / "isin_map.json")
    ok, missing = official.resolve(entries, search, lambda s: "EUR", workers=1, cache_path=path)
    assert [e["yf"] for e in ok] == ["ADS.DE"] and {e["isin"] for e in missing} == {"FI0009000202", "SE0000106270"}
    assert set(json.load(open(path))) == {"DE000A1EWWW0"}                                                # nur der Erfolg wird gemerkt
    calls.clear()
    official.resolve(entries, search, lambda s: "EUR", workers=1, cache_path=path)
    assert "DE000A1EWWW0" not in calls and "FI0009000202" in calls and "SE0000106270" in calls           # Fehlschläge werden erneut versucht


def test_to_universe_keeps_first_of_duplicate_symbols_and_uses_the_isin_as_search_term():
    res = [{"isin": "US02079K3059", "name": "Alphabet A", "yf": "GOOGL", "currency": "USD", "indices": ["nasdaq100"], "stars": 0, "land": None},
           {"isin": "DE000A1EWWW0", "name": "adidas AG", "yf": "ADS.DE", "currency": "EUR", "indices": ["dax", "eurostoxx50"], "stars": 0, "land": None},
           {"isin": "US02079K1079", "name": "Alphabet C", "yf": "GOOGL", "currency": "USD", "indices": ["nasdaq100"], "stars": 0, "land": None},
           {"isin": "DE0006766504", "name": "Aurubis", "yf": "NDA.DE", "currency": "EUR", "indices": ["mdax", "gci"], "stars": 1, "land": None, "liste": "x"}]
    rows = official.to_universe(res)
    assert [r["yf"] for r in rows] == ["ADS.DE", "NDA.DE", "GOOGL"]                                       # DAX vor MDAX vor US
    assert rows[0]["search"] == "DE000A1EWWW0" and rows[0]["markt"] == "dax" and rows[1]["stars"] == 1 and rows[1]["markt"] == "mdax"
    assert rows[2]["isin"] == "US02079K1079" and rows[2]["currency"] == "USD" and rows[2]["markt"] == "us"


def test_build_reports_what_was_dropped(tmp_path):
    def search(query):
        return {"DE000A1EWWW0": [q("ADS.DE", longname="adidas AG")], "DE0008404005": [q("ALV.DE", longname="Allianz SE")],
                "US0378331005": [q("AAPL", longname="Apple Inc.")], "NL0000235190": [q("AIR.PA", longname="Airbus SE")]}.get(query, [])
    rows, rep = official.build(LIST, search, lambda s: "EUR", download=lambda syms: {s for s in syms if s != "ALV.DE"}, cache_path=str(tmp_path / "m.json"))
    assert {r["yf"] for r in rows} == {"ADS.DE", "AAPL", "AIR.PA"}
    assert rep["aus_liste"] == 10 and rep["universum"] == 3 and rep["ohne_kurse"] == ["Allianz SE (ALV.DE)"]
    assert any("KESKO" in x for x in rep["ohne_kuerzel"]) and rep["je_gruppe"]["us"] == 1 and rep["waehrungen"] == {"EUR": 2, "USD": 1}


def test_latest_url_finds_the_pdf_link_and_makes_it_absolute():
    html = '<a href="https://www.planspiel-boerse.de/wertpapierliste.html">x</a><a href="/api/download/1355/PB26_Wertpapierliste.pdf?hash=abc&amp;x=1">PDF</a>'
    assert official.latest_url(lambda url: html) == "https://www.planspiel-boerse.de/api/download/1355/PB26_Wertpapierliste.pdf?hash=abc&x=1"
    with pytest.raises(RuntimeError):
        official.latest_url(lambda url: "<html>nichts</html>")


def test_pdf_text_reads_text_files_and_explains_missing_pdftotext(tmp_path, monkeypatch):
    f = tmp_path / "liste.txt"
    f.write_text("DAX\n", encoding="utf-8")
    assert official.pdf_text(str(f)) == "DAX\n"
    monkeypatch.setattr(official.subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(FileNotFoundError()))
    with pytest.raises(RuntimeError, match="poppler-utils"):
        official.pdf_text(str(tmp_path / "x.pdf"))


def test_currencies_of_the_official_list_are_convertible():
    for ccy in ("EUR", "USD", "SEK", "DKK", "NOK", "CHF", "GBp", "CAD", "JPY"):
        assert fx.rate_symbol(ccy).startswith("EUR")


# --- Zuordnung: Heimatbörse statt Nebenplätze ---
def test_frankfurt_only_hits_are_replaced_by_the_xetra_symbol_when_it_exists():
    search = lambda query: [q("DWS.F", longname="DWS Group GmbH & Co. KGaA")]      # noqa: E731
    r = official.resolve_one({"isin": "DE000DWS1007", "name": "DWS GROUP GMBH+CO.KGAA ON"}, search, lambda s: "EUR", exists=lambda sym: sym == "DWS.DE")
    assert r["yf"] == "DWS.DE" and r["name"] == "DWS Group GmbH & Co. KGaA" and r["currency"] == "EUR"
    r = official.resolve_one({"isin": "DE000DWS1007", "name": "DWS GROUP GMBH+CO.KGAA ON"}, search, lambda s: "EUR", exists=lambda sym: False)
    assert r["yf"] == "DWS.F"                                                          # Xetra nicht vorhanden: Frankfurt ist besser als nichts


def test_fantasy_symbols_made_of_the_isin_and_otc_symbols_are_never_used():
    junk = lambda query: [q("DE000A2YNT30.SG", longname="AlzChem Group AG")] if query.startswith("DE0") else [q("ACT.DE", longname="AlzChem Group AG")]      # noqa: E731
    r = official.resolve_one({"isin": "DE000A2YNT30", "name": "ALZCHEM GROUP AG INH O.N."}, junk, lambda s: "EUR", exists=lambda sym: False)
    assert r["yf"] == "ACT.DE"                                                         # über den Namen gefunden statt des Fantasiesymbols
    otc = lambda query: [q("KLKNF", exchange="PNK", longname="Klöckner & Co SE")]      # noqa: E731
    assert official.resolve_one({"isin": "DE000KC01000", "name": "KLOECKNER & CO SE"}, otc, lambda s: "USD", exists=lambda sym: False) is None
    assert official.pick_symbol("DE000KC01000", [q("KLKNF", exchange="PNK")]) is None
    assert official.pick_symbol("US0000000000", [q("ABCD", exchange="PNK")]) is None                    # auch für US-ISIN kein Freiverkehr
    assert official.pick_symbol("US7223041028", [q("PDD", exchange="NMS")])["symbol"] == "PDD"         # bei US-Titeln ist das Symbol ohne Endung richtig


def test_us_primary_listings_of_european_companies_use_the_us_ticker():
    nxp = [q("NXPI", exchange="NMS", shortname="NXP Semiconductors N.V.")]
    assert official.pick_symbol("NL0009538784", nxp)["symbol"] == "NXPI"                              # niederländische ISIN, primär an der Nasdaq notiert
    r = official.resolve_one({"isin": "NL0009538784", "name": "NXP SEMICONDUCTORS"}, lambda x: nxp, lambda s: "USD", exists=lambda sym: False)
    assert r["yf"] == "NXPI" and r["currency"] == "USD"
    both = [q("NXP.DE", exchange="GER"), q("NXPI", exchange="NMS")]
    assert official.pick_symbol("NL0009538784", both)["symbol"] == "NXPI"                             # Hauptnotiz vor Nebenplatz in Euro
    assert official.pick_symbol("NL0000235190", [q("AIR.PA", exchange="PAR"), q("AIRP", exchange="PNK")])["symbol"] == "AIR.PA"   # Heimatbörse zuerst


def test_clean_name_drops_par_values_and_currency_codes():
    assert official.clean_name("QIAGEN NV EO -,01") == "QIAGEN NV"
    assert official.clean_name("ALPHABET INC.CL.A DL-,001") == "ALPHABET INC.CL.A"
    assert official.clean_name("KINNEVIK B SK 0,025") == "KINNEVIK B"
    assert official.clean_name("HENNES + MAURITZ B SK-125") == "HENNES MAURITZ B"
    assert official.clean_name("1+1 AG INH O.N.") == "AG"                               # nichts Sinnvolles übrig: Rest bleibt, Suche liefert höchstens nichts
    assert official.clean_name("0,5") == "0,5"


def test_alive_drops_thinly_traded_listings(monkeypatch):
    import types

    import numpy as np
    import pandas as pd
    idx = pd.bdate_range("2026-09-01", periods=21)
    cols = pd.MultiIndex.from_product([["BUSY.DE", "THIN.F", "DEAD.SG"], ["Close"]])
    data = pd.DataFrame({("BUSY.DE", "Close"): np.arange(21.0) + 100, ("THIN.F", "Close"): [1.0] + [np.nan] * 19 + [1.1],
                         ("DEAD.SG", "Close"): [np.nan] * 21}, index=idx)[cols]
    monkeypatch.setitem(__import__("sys").modules, "yfinance", types.SimpleNamespace(download=lambda *a, **k: data))
    rows = [{"yf": "BUSY.DE"}, {"yf": "THIN.F"}, {"yf": "DEAD.SG"}]
    assert official.alive(rows) == [{"yf": "BUSY.DE"}]


def test_empty_search_is_retried_once_because_yahoo_throttles():
    calls = []

    def search(query):
        calls.append(query)
        return [] if len(calls) == 1 else [q("ADS.DE", longname="adidas AG")]
    r = official.resolve_one({"isin": "DE000A1EWWW0", "name": "ADIDAS"}, search, lambda s: "EUR", exists=lambda s: False)
    assert r["yf"] == "ADS.DE" and calls == ["DE000A1EWWW0", "DE000A1EWWW0"]


def test_alphabet_classes_are_fixed_by_override():
    nothing = lambda query: []      # noqa: E731
    a = official.resolve_one({"isin": "US02079K3059", "name": "ALPHABET INC.CL.A DL-,001"}, nothing, lambda s: "USD")
    c = official.resolve_one({"isin": "US02079K1079", "name": "ALPHABET INC.CL.C DL-,001"}, nothing, lambda s: "USD")
    assert a["yf"] == "GOOGL" and c["yf"] == "GOOG" and a["currency"] == "USD"


def test_us_primary_listing_beats_a_thin_secondary_place_and_the_name_search():
    search = lambda query: [q("MDT", exchange="NYQ", shortname="Medtronic plc."), q("0Y6X.L", exchange="LSE", shortname="MEDTRONIC PLC MEDT")]      # noqa: E731
    r = official.resolve_one({"isin": "IE00BTN1Y115", "name": "MEDTRONIC PLC DL-,0001"}, search, lambda s: "GBp", exists=lambda s: False)
    assert r["yf"] == "MDT" and r["currency"] == "USD"


def test_regional_german_places_are_only_replaced_by_the_same_ticker_on_xetra():
    r = official.resolve_one({"isin": "DE000KC01000", "name": "KLOECKNER"},
                             lambda query: [q("KLKNF", exchange="PNK")] if query.startswith("DE") else [q("KCO.SG", shortname="Kloeckner & Co. SE")],
                             lambda s: "EUR", exists=lambda sym: sym == "KCO.DE")
    assert r["yf"] == "KCO.DE"                                                          # über den Namen zum Nebenplatz, von dort zur Xetra
    # Fremde Kürzel werden nicht geraten: "1FRE.MI" (Mailand) bleibt ohne Xetra-Ableitung
    calls = []
    official.resolve_one({"isin": "DE0005785604", "name": "FRESENIUS SE+CO.KGAA O.N."}, lambda query: [q("1FRE.MI", shortname="Fresenius")], lambda s: "EUR",
                         exists=lambda sym: calls.append(sym) or False)
    assert calls == []


def test_name_search_uses_the_first_word_and_the_share_class():
    def search(query):
        if query == "KESKO":
            return [q("KESKOA.HE", shortname="Kesko Corporation A"), q("KESKOB.HE", shortname="Kesko Corporation B")]
        return []
    r = official.resolve_one({"isin": "FI0009000202", "name": "KESKO B"}, search, lambda s: "EUR", exists=lambda s: False)
    assert r["yf"] == "KESKOB.HE"                                                       # "KESKO B" ergibt keinen Treffer, "KESKO" schon; Gattung B gewählt
    r = official.resolve_one({"isin": "SE0015810247", "name": "KINNEVIK B SK 0,025"},
                             lambda query: [q("KINV-A.ST", shortname="Kinnevik AB ser. A"), q("KINV-B.ST", shortname="Kinnevik AB ser. B")] if query == "KINNEVIK" else [],
                             lambda s: "SEK", exists=lambda s: False)
    assert r["yf"] == "KINV-B.ST" and r["currency"] == "SEK"
    assert official._share_class("KESKO B") == "B" and official._share_class("ALLIANZ") is None and official._share_class("KINNEVIK B SK 0,025") == "B"


def test_dutch_isin_traded_on_xetra_gets_the_xetra_symbol():
    r = official.resolve_one({"isin": "NL0012169213", "name": "QIAGEN NV EO -,01"}, lambda query: [q("QIA.HA", shortname="Qiagen N.V.")], lambda s: "EUR",
                             exists=lambda sym: sym == "QIA.DE")
    assert r["yf"] == "QIA.DE"                                                          # Nebenplatz Hannover: dasselbe Kürzel an der Xetra, auch bei niederländischer ISIN


def test_pinduoduo_override_maps_to_the_us_ticker():
    r = official.resolve_one({"isin": "US7223041028", "name": "PINDUODUO INC. ADR"}, lambda query: [q("9PDA.SG", shortname="Pinduoduo Inc")], lambda s: "USD")
    assert r["yf"] == "PDD" and r["currency"] == "USD"
