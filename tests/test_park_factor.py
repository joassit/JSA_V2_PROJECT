import pytest

from analysis.park_factor import (
    compute_park_factors_from_games, compute_raw_park_factor, normalize_park_factors,
)


def test_compute_raw_park_factor_equal_home_and_road_is_one():
    pf = compute_raw_park_factor(
        home_runs_for=40, home_runs_against=40, home_games=10,
        road_runs_for=40, road_runs_against=40, road_games=10,
    )
    assert pf == pytest.approx(1.0)


def test_compute_raw_park_factor_hitter_friendly_park_above_one():
    # Mismo equipo anota/permite mas en casa que de visita -- parque
    # favorece la ofensiva.
    pf = compute_raw_park_factor(
        home_runs_for=60, home_runs_against=60, home_games=10,
        road_runs_for=40, road_runs_against=40, road_games=10,
    )
    assert pf > 1.0


def test_compute_raw_park_factor_pitcher_friendly_park_below_one():
    pf = compute_raw_park_factor(
        home_runs_for=30, home_runs_against=30, home_games=10,
        road_runs_for=50, road_runs_against=50, road_games=10,
    )
    assert pf < 1.0


def test_compute_raw_park_factor_none_without_sample():
    assert compute_raw_park_factor(0, 0, 0, 40, 40, 10) is None
    assert compute_raw_park_factor(40, 40, 10, 0, 0, 0) is None


def test_normalize_park_factors_league_average_is_one():
    normalized = normalize_park_factors({1: 1.2, 2: 1.0, 3: 0.8})
    assert sum(normalized.values()) / len(normalized) == pytest.approx(1.0)
    # El orden relativo se preserva.
    assert normalized[1] > normalized[2] > normalized[3]


def test_normalize_park_factors_empty_input():
    assert normalize_park_factors({}) == {}


def _games():
    # 2 equipos, parque de team 100 es mas ofensivo (10 runs/juego en
    # casa) que el de team 200 (4 runs/juego en casa) -- team 100 y 200
    # tienen la MISMA calidad real (anotan/permiten igual de visita).
    return [
        {"home_team_id": 100, "away_team_id": 200, "home_score": 6, "away_score": 4},
        {"home_team_id": 100, "away_team_id": 200, "home_score": 5, "away_score": 5},
        {"home_team_id": 200, "away_team_id": 100, "home_score": 2, "away_score": 2},
        {"home_team_id": 200, "away_team_id": 100, "home_score": 2, "away_score": 2},
    ]


def test_compute_park_factors_from_games_end_to_end():
    factors = compute_park_factors_from_games(_games())
    assert set(factors.keys()) == {100, 200}
    # El parque de 100 (10 runs/juego en casa) es mas ofensivo que el de
    # 200 (4 runs/juego en casa) -- ambos equipos tienen 4 runs/juego de
    # visita (misma calidad real), asi que el factor de 100 debe ser
    # mayor que el de 200.
    assert factors[100] > factors[200]
    assert sum(factors.values()) / len(factors) == pytest.approx(1.0)


def test_compute_park_factors_skips_games_without_score():
    games = _games() + [{"home_team_id": 300, "away_team_id": 100, "home_score": None, "away_score": None}]
    factors = compute_park_factors_from_games(games)
    assert 300 not in factors
