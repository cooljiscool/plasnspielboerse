from datetime import date

from bot import config, track


def test_add_once_per_isin_and_day_and_only_with_forecast():
    rows = []
    notes = {"A": {"erwartung_3m_prozent": 8.0, "sentiment": 1}, "B": {"sentiment": 0}, "C": {"erwartung_3m_prozent": -2.0}}
    assert track.add(rows, notes, {"A": 100.0, "C": 50.0}, date(2026, 10, 1)) == 2            # B hat keine Erwartung
    assert track.add(rows, notes, {"A": 100.0, "C": 50.0}, date(2026, 10, 1)) == 0            # selber Tag: nichts doppelt
    assert track.add(rows, notes, {"A": 104.0}, date(2026, 10, 2)) == 1                       # neuer Tag, C ohne Kurs
    assert rows[0]["preis"] == 100.0 and rows[0]["ergebnis"] == {}


def test_update_fills_horizons_within_tolerance_only():
    rows = [{"datum": "2026-10-01", "isin": "A", "preis": 100.0, "erwartung": 5.0, "ergebnis": {}}]
    assert track.update(rows, {"A": 110.0}, date(2026, 10, 10)) == 0                          # erst 9 Tage
    assert track.update(rows, {"A": 110.0}, date(2026, 10, 16)) == 1 and rows[0]["ergebnis"] == {"14": 0.10}
    assert track.update(rows, {"A": 110.0}, date(2026, 10, 16)) == 0                          # nichts doppelt
    assert track.update(rows, {"A": 120.0}, date(2026, 10, 30)) == 1 and rows[0]["ergebnis"]["28"] == 0.20
    assert track.update(rows, {"A": 130.0}, date(2026, 12, 20)) == 0                          # 56-Tage-Zeitpunkt längst verpasst (Toleranz 7 Tage)
    assert track.update(rows, {}, date(2026, 11, 27)) == 0                                    # Kurs fehlt: kein Eintrag


def rows_with(pairs, horizon="28"):
    return [{"datum": "2026-10-01", "isin": f"S{i}", "preis": 1.0, "erwartung": e, "ergebnis": {horizon: r}} for i, (e, r) in enumerate(pairs)]


def test_summary_needs_enough_forecasts():
    assert track.summary([])["n"] == 0
    s = track.summary(rows_with([(5.0, 0.02)] * 10))
    assert s["n"] == 10 and "hinweis" in s and "rangkorrelation" not in s


def test_summary_skilled_forecaster_has_positive_rank_correlation_and_hit_rate():
    pairs = [(e, 0.01 * e + (0.002 if i % 2 else -0.002)) for i, e in enumerate(range(-20, 20))]
    s = track.summary(rows_with(pairs))
    assert s["n"] == 40 and s["rangkorrelation"] > 0.9 and s["trefferquote_richtung"] > 0.9
    assert s["ergebnis_obere_haelfte"] > s["ergebnis_untere_haelfte"]


def test_summary_worthless_forecaster_has_no_skill():
    import random
    rnd = random.Random(3)
    pairs = [(rnd.uniform(-10, 10), rnd.uniform(-0.1, 0.1)) for _ in range(200)]
    s = track.summary(rows_with(pairs))
    assert abs(s["rangkorrelation"]) < 0.2 and 0.35 < s["trefferquote_richtung"] < 0.65


def test_load_save_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", str(tmp_path))
    assert track.load() == []
    rows = [{"datum": "2026-10-01", "isin": "A", "preis": 1.0, "erwartung": 3.0, "ergebnis": {}}]
    track.save(rows)
    assert track.load() == rows
    (tmp_path / "forecasts.json").write_text("kaputt")
    assert track.load() == []
