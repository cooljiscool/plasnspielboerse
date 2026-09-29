from datetime import date

import pandas as pd
import pytest

from bot import analysts, config

TODAY = date(2026, 9, 29)


def trend(cur_0y, d30_0y, d90_0y=None, cur_1y=10.0, d30_1y=10.0):
    return pd.DataFrame({"current": [cur_0y, cur_1y], "30daysAgo": [d30_0y, d30_1y], "90daysAgo": [d90_0y or d30_0y, d30_1y]}, index=["0y", "+1y"])


def revs(up30, down30):
    return pd.DataFrame({"upLast7days": [0], "upLast30days": [up30], "downLast30days": [down30], "downLast7Days": [0]}, index=["0y"])


def updown(rows):
    idx = pd.to_datetime([r[0] for r in rows])
    return pd.DataFrame({"Firm": "X", "Action": [r[1] for r in rows], "priceTargetAction": [r[2] for r in rows]}, index=idx)


def reco(now, before):
    cols = ["strongBuy", "buy", "hold", "sell", "strongSell"]
    return pd.DataFrame([dict(period="0m", **dict(zip(cols, now))), dict(period="-3m", **dict(zip(cols, before)))])


def test_estimates_cut_flag():
    m = analysts.metrics(trend(9.0, 10.0), revs(0, 4), None, None, None, TODAY)
    assert m["eps_jahr_aenderung_30d"] == pytest.approx(-0.10) and m["revisionen_30d"] == {"erhoeht": 0, "gesenkt": 4}
    assert m["schaetzungen_gesenkt"] is True and "schaetzungen_angehoben" not in m


def test_small_cut_or_mixed_revisions_do_not_flag():
    assert "schaetzungen_gesenkt" not in analysts.metrics(trend(9.8, 10.0), revs(0, 4), None, None, None, TODAY)      # nur 2 % gesenkt
    assert "schaetzungen_gesenkt" not in analysts.metrics(trend(9.0, 10.0), revs(3, 4), None, None, None, TODAY)      # gemischte Revisionen
    assert "schaetzungen_gesenkt" not in analysts.metrics(trend(9.0, 10.0), revs(0, 2), None, None, None, TODAY)      # zu wenige Senkungen


def test_estimates_raised_flag():
    m = analysts.metrics(trend(10.8, 10.0), revs(5, 0), None, None, None, TODAY)
    assert m["schaetzungen_angehoben"] is True and "schaetzungen_gesenkt" not in m


def test_rating_changes_only_recent_and_downgrade_flag():
    ud = updown([("2026-09-20", "down", "Lowers"), ("2026-09-10", "down", "Lowers"), ("2026-08-01", "down", "Lowers"),
                 ("2026-07-15", "up", "Raises"), ("2025-01-01", "down", "Lowers"), ("2026-09-01", "main", "Maintains")])
    m = analysts.metrics(None, None, ud, None, None, TODAY)
    assert m["ratings_90d"] == {"herauf": 1, "herab": 3, "kursziel_erhoeht": 1, "kursziel_gesenkt": 3}   # das Jahr alte Rating fehlt
    assert m["herabstufungen_ueberwiegen"] is True


def test_recommendation_trend_and_target_dispersion():
    m = analysts.metrics(None, None, None, reco([6, 19, 13, 3, 3], [6, 22, 16, 1, 2]), {"mean": 100.0, "high": 140.0, "low": 60.0}, TODAY)
    assert m["kauf_anteil"] == pytest.approx(25 / 44, abs=0.01) and m["kauf_anteil_aenderung_3m"] < 0
    assert m["kursziel_streuung"] == 0.8


def test_missing_data_gives_empty_result_and_handles_nan():
    assert analysts.metrics(None, None, None, None, None, TODAY) == {}
    nan_trend = pd.DataFrame({"current": [float("nan")], "30daysAgo": [10.0], "90daysAgo": [10.0]}, index=["0y"])
    assert analysts.metrics(nan_trend, None, None, None, None, TODAY) == {}
    assert analysts.metrics(trend(9.0, -1.0), None, None, None, None, TODAY).get("eps_jahr_aenderung_30d") is None    # negative Vorschätzung: kein Prozentwert


def test_get_caches_per_day_and_survives_errors(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", str(tmp_path))
    calls = []

    def fake(sym):
        calls.append(sym)
        if sym == "BAD":
            raise OSError("gesperrt")
        return {"schaetzungen_gesenkt": True}
    uni = {"A": {"yf": "A"}, "B": {"yf": "BAD"}, "C": {}}
    out = analysts.get(uni, ["A", "B", "C"], TODAY, fake)
    assert out == {"A": {"schaetzungen_gesenkt": True}} and sorted(calls) == ["A", "BAD"]
    analysts.get(uni, ["A", "B"], TODAY, fake)
    assert len(calls) == 2
    analysts.get(uni, ["A"], date(2026, 9, 30), fake)
    assert len(calls) == 3
