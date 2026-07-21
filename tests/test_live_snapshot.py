import pytest

from analysis.live_snapshot import aggregate_bullpen_era, compute_league_averages


def test_aggregate_bullpen_era_weighted_not_simple():
    # Un relevista con mucho mas IP domina el promedio -- si fuera simple
    # (no ponderado) daria (2.0+8.0)/2=5.0, ponderado debe acercarse
    # mucho mas a 2.0.
    era = aggregate_bullpen_era([(2.0, 50.0), (8.0, 2.0)])
    assert era == pytest.approx((2.0 * 50.0 + 8.0 * 2.0) / 52.0)
    assert era < 3.0


def test_aggregate_bullpen_era_none_without_ip():
    assert aggregate_bullpen_era([]) is None
    assert aggregate_bullpen_era([(3.5, 0.0)]) is None


def test_aggregate_bullpen_era_skips_zero_ip_entries():
    # Un pitcher con IP=0 (recien llamado, sin innings todavia) no debe
    # contaminar el promedio.
    era = aggregate_bullpen_era([(4.0, 10.0), (99.0, 0.0)])
    assert era == pytest.approx(4.0)


def test_compute_league_averages_simple_mean():
    result = compute_league_averages([0.700, 0.800], [3.50, 4.50])
    assert result["league_avg_ops"] == pytest.approx(0.750)
    assert result["league_avg_era"] == pytest.approx(4.00)


def test_compute_league_averages_ignores_none_values():
    result = compute_league_averages([0.700, None, 0.900], [None, None])
    assert result["league_avg_ops"] == pytest.approx(0.800)
    assert result["league_avg_era"] is None


def test_compute_league_averages_empty_input_is_none():
    result = compute_league_averages([], [])
    assert result == {"league_avg_ops": None, "league_avg_era": None}
