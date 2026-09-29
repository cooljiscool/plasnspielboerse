import numpy as np
import pandas as pd
import pytest

from bot import config, statements

Q = pd.to_datetime(["2026-06-30", "2026-03-31", "2025-12-31", "2025-09-30", "2025-06-30", "2025-03-31"])   # neuestes zuerst


def frame(rows: dict):
    return pd.DataFrame({k: v for k, v in rows.items()}, index=Q).T


def healthy(**over):
    bs = {"Total Debt": [200.0] * 4 + [260.0] * 2, "Cash And Cash Equivalents": [150.0] * 6, "Stockholders Equity": [800.0] * 6,
          "Total Assets": [2000.0] * 4 + [2100.0] * 2, "Current Assets": [900.0] * 4 + [700.0] * 2, "Current Liabilities": [500.0] * 6,
          "Ordinary Shares Number": [100.0] * 6}
    inc = {"Total Revenue": [1000.0] * 4 + [900.0] * 2, "Gross Profit": [450.0] * 4 + [380.0] * 2, "EBIT": [150.0] * 6, "EBITDA": [200.0] * 6,
           "Net Income": [100.0] * 4 + [70.0] * 2, "Interest Expense": [-10.0] * 6}
    cf = {"Operating Cash Flow": [130.0] * 6, "Free Cash Flow": [100.0] * 6}
    for k, v in over.items():
        for d in (bs, inc, cf):
            if k in d:
                d[k] = v
    return frame(bs), frame(inc), frame(cf)


def test_healthy_company_has_no_warnings_and_high_piotroski():
    m = statements.compute(*healthy())
    assert m["schwer"] is False and "warnungen" not in m
    assert m["nettoschuld_ebitda"] == pytest.approx(50 / 800, abs=0.01) or m["nettoschuld_ebitda"] < 1
    assert m["zinsdeckung"] == pytest.approx(15.0) and m["current_ratio"] == pytest.approx(1.8)
    f, n = map(int, m["piotroski"].split("/"))
    assert n == 9 and f >= 8                       # alle Vorjahresvergleiche verbessert, bis auf höchstens eines
    assert m["fcf_marge"] == pytest.approx(0.1)


def test_distressed_company_gets_severe_warning():
    bs, inc, cf = healthy(**{"Total Debt": [3000.0] * 6, "Cash And Cash Equivalents": [100.0] * 6, "EBIT": [20.0] * 6,
                              "EBITDA": [100.0] * 6, "Interest Expense": [-40.0] * 6})   # 12 Monate: EBITDA 400, Nettoschuld 2.900 = 7,3-fach
    m = statements.compute(bs, inc, cf)
    assert m["schwer"] is True
    assert any("Zinsdeckung" in w for w in m["warnungen"]) and any("Nettoverschuldung" in w for w in m["warnungen"])


def test_negative_equity_and_cash_burn_is_severe():
    m = statements.compute(*healthy(**{"Stockholders Equity": [-50.0] * 6, "Free Cash Flow": [-30.0] * 6, "Operating Cash Flow": [-10.0] * 6}))
    assert m["schwer"] and any("Eigenkapital" in w for w in m["warnungen"]) and any("Cashflow" in w for w in m["warnungen"])


def test_financial_sector_skips_debt_metrics():
    bs, inc, cf = healthy(**{"Total Debt": [9000.0] * 6, "Interest Expense": [-500.0] * 6})
    m = statements.compute(bs, inc, cf, sector="Financial Services")
    assert "nettoschuld_ebitda" not in m and "zinsdeckung" not in m and m["schwer"] is False


def test_missing_data_is_left_empty_not_guessed():
    assert statements.compute(None, None, None) == {}
    bs, inc, cf = healthy()
    inc = inc.iloc[:0]                                 # keine Gewinn- und Verlustrechnung
    m = statements.compute(bs, inc, cf)
    assert "zinsdeckung" not in m and "nettoschuld_ebitda" not in m and "current_ratio" in m
    inc2 = healthy()[1]; inc2.iloc[:, :2] = np.nan     # neueste Quartale fehlen: keine Zwölfmonatssummen
    assert "zinsdeckung" not in statements.compute(bs, inc2, cf)


def test_handles_pandas_na_values():
    bs, inc, cf = healthy()
    bs = bs.astype("object"); bs.iloc[0, 0] = pd.NA
    assert isinstance(statements.compute(bs, inc, cf), dict)


def test_insider_summary_us_style_and_empty():
    df = pd.DataFrame({"Insider Purchases Last 6m": ["Purchases", "Sales", "Net Shares Purchased (Sold)", "Total Insider Shares Held"],
                       "Shares": [400000.0, 100000.0, 300000.0, 2.4e8], "Trans": [10, 4, 14, pd.NA]})
    s = statements.insider_summary(df)
    assert s["kaeufe"] == 10 and s["verkaeufe"] == 4 and s["netto_aktien"] == 300000.0 and "Netto-Käufe" in s["signal"]
    sold = df.copy(); sold.loc[2, "Shares"] = -50000.0
    assert "Netto-Verkäufe" in statements.insider_summary(sold)["signal"]
    empty = pd.DataFrame({"Insider Purchases Last 6m": ["Purchases", "Sales"], "Shares": [0, pd.NA], "Trans": [0, 0]})
    assert statements.insider_summary(empty) == {} and statements.insider_summary(None) == {}   # deutsche Titel: keine Daten


def test_get_caches_per_day_and_passes_sector(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", str(tmp_path))
    from datetime import date
    calls = []
    fake = lambda sym, sector: calls.append((sym, sector)) or {"bilanz": {"schwer": False}}
    uni = {"A": {"yf": "A.DE"}, "B": {"yf": "B.DE"}, "C": {}}
    out = statements.get(uni, ["A", "B", "C"], date(2026, 9, 29), {"A": "Technology"}, fake)
    assert out["A"] == {"bilanz": {"schwer": False}} and out["C"] == {} and calls == [("A.DE", "Technology"), ("B.DE", None)]
    statements.get(uni, ["A", "B"], date(2026, 9, 29), {}, fake)
    assert len(calls) == 2                                            # zweiter Aufruf am selben Tag: Zwischenspeicher
    statements.get(uni, ["A"], date(2026, 9, 30), {}, fake)
    assert len(calls) == 3


def test_weak_interest_cover_with_net_cash_is_only_a_mild_warning():
    bs, inc, cf = healthy(**{"Total Debt": [100.0] * 6, "Cash And Cash Equivalents": [400.0] * 6, "EBIT": [-20.0] * 6, "Interest Expense": [-10.0] * 6})
    m = statements.compute(bs, inc, cf)
    assert m["schwer"] is False and any("Zinsdeckung" in w and "Bargeld" in w for w in m["warnungen"])
