import numpy as np
import pandas as pd

from bot import macro


def fake_fetch(sid):
    daily = pd.bdate_range("2019-01-01", "2021-12-31")
    month = pd.date_range("2018-01-01", "2021-12-01", freq="MS")
    series = {
        "T10Y2Y": pd.Series(np.linspace(1.0, -0.5, len(daily)), index=daily),
        "T10Y3M": pd.Series(1.0, index=daily),
        "BAA10Y": pd.Series(np.r_[np.full(len(daily) - 60, 2.0), np.full(60, 3.0)], index=daily),
        "DGS10": pd.Series(2.0, index=daily),
        "DFF": pd.Series(1.0, index=daily),
        "UNRATE": pd.Series(np.r_[np.full(len(month) - 3, 4.0), [5.0, 6.0, 6.0]], index=month),
        "CPIAUCSL": pd.Series(np.linspace(250, 280, len(month)), index=month),
    }
    return series[sid]


def test_frame_uses_only_published_values():
    dates = pd.bdate_range("2021-09-01", "2021-12-31")
    f = macro.frame(dates, fetch=fake_fetch)
    # Arbeitslosenquote für Oktober (Wert steht auf 2021-10-01) erscheint erst 35 Tage später
    assert f.loc["2021-10-15", "unrate"] == 4.0                      # noch der Septemberwert (4.0), nicht der Oktoberwert
    assert f.loc["2021-11-30", "unrate"] == 5.0                      # Oktoberwert seit 5. November bekannt
    assert f["sahm"].loc["2021-10-01":"2021-10-29"].max() < 0.5      # Sahm-Signal erst nach Veröffentlichung
    assert f["sahm"].iloc[-1] >= 0.5


def test_frame_has_no_gaps_and_expected_columns():
    dates = pd.bdate_range("2020-01-01", "2020-12-31")
    f = macro.frame(dates, fetch=fake_fetch)
    assert {"curve", "curve3m", "credit", "credit_widening", "y10_chg63", "dff_chg126", "unrate", "sahm", "cpi_yoy"} <= set(f.columns)
    assert f["curve"].notna().all() and f["curve"].iloc[0] > f["curve"].iloc[-1]


def test_flags_translate_thresholds():
    assert macro.flags({}) == []
    got = macro.flags({"curve": -0.3, "credit_widening": 0.8, "y10_chg63": 1.0, "dff_chg126": 1.5, "sahm": 0.6})
    assert len(got) == 5 and any("invers" in g for g in got) and any("Sahm" in g for g in got)
    assert macro.flags({"curve": 0.3, "credit_widening": 0.2}) == []


def test_snapshot_survives_missing_sources():
    def broken(sid):
        raise OSError("kein Netz")
    out = macro.snapshot(fetch=broken, ecb=lambda: (_ for _ in ()).throw(OSError("kein Netz")))
    assert "fehler_fred" in out
    ok = macro.snapshot(fetch=fake_fetch, ecb=lambda: pd.Series([2.0], index=[pd.Timestamp("2021-01-01")]))
    assert ok["leitzins_ezb_einlagesatz"] == 2.0 and "kurve_10y_2y" in ok and isinstance(ok["warnsignale"], list)


def test_get_retries_then_uses_stale_cache(tmp_path, monkeypatch):
    from bot import config
    monkeypatch.setattr(config, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(macro.time, "sleep", lambda s: None)
    calls = []

    def flaky(req, timeout):
        calls.append(1)
        if len(calls) < 3:
            raise TimeoutError("langsam")
        class R:
            def read(self): return b"date,v\n2020-01-01,1.5\n"
        return R()
    monkeypatch.setattr(macro.urllib.request, "urlopen", flaky)
    assert macro._get("http://x", "t.csv").startswith("date,v") and len(calls) == 3      # dritter Versuch klappt
    # Quelle dauerhaft weg: alter Zwischenspeicher wird benutzt statt Fehler
    import os, time
    os.utime(tmp_path / "cache" / "t.csv", (time.time() - 10 ** 6, time.time() - 10 ** 6))
    monkeypatch.setattr(macro.urllib.request, "urlopen", lambda req, timeout: (_ for _ in ()).throw(OSError("weg")))
    assert "2020-01-01" in macro._get("http://x", "t.csv")
    with __import__("pytest").raises(OSError):
        macro._get("http://x", "nie-gespeichert.csv")
