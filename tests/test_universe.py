from bot import universe_tool, universes


def test_build_tested_uses_lookup_and_drops_dead_symbols():
    alive = set(universes.DAX[:3] + universes.US[:2])
    fake = {s: {"name": f"Name {s}", "isin": ("DE000" + s if s.endswith(".DE") else None)} for s in alive}
    rows = universe_tool.build_tested(lookup=lambda s: fake[s], alive=alive)
    assert {r["yf"] for r in rows} == alive
    de = next(r for r in rows if r["yf"] == universes.DAX[0])
    us = next(r for r in rows if r["yf"] == universes.US[0])
    assert de["isin"] == "DE000" + universes.DAX[0] and de["name"].startswith("Name") and de["markt"] == "dax"
    assert us["isin"] == universes.US[0] and us["markt"] == "us"          # ohne ISIN dient das Symbol als Platzhalter
    assert all(r["stars"] == 0 for r in rows)


def test_universe_lists_have_no_duplicates_within_groups():
    for g, lst in universes.GROUPS.items():
        assert len(lst) == len(set(lst)), g


def test_search_term_strips_legal_forms():
    st = universe_tool.search_term
    assert st("Siemens Aktiengesellschaft") == "Siemens"
    assert st("Eckert & Ziegler SE") == "Eckert Ziegler"
    assert st("Deere & Company") == "Deere"
    assert st("DWS Group GmbH & Co. KGaA") == "DWS"
    assert st("Deutsche Telekom AG") == "Deutsche Telekom"
    assert st("Lockheed Martin Corporation") == "Lockheed Martin"
    assert st("AG") == "AG"   # nichts übrig: Original behalten
