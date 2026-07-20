import pytest

from analysis.chase_rate_candidate_audit import (
    LEAGUE_AVG_CHASE_RATE, _adjusted_ops, baseline_win_prob,
    evaluate_m2, m2_chase_adjusted_win_prob,
)

_PAYLOAD = {
    "home_ops": 0.750, "away_ops": 0.750,
    "home_starter_xera": 4.0, "away_starter_xera": 4.0,
    "home_bullpen_era": 4.0, "away_bullpen_era": 4.0,
}


def test_adjusted_ops_weight_zero_returns_general_ops_unchanged():
    assert _adjusted_ops(0.750, chase_rate=0.20, weight=0.0) == 0.750


def test_adjusted_ops_none_chase_rate_returns_general_ops_unchanged():
    assert _adjusted_ops(0.750, chase_rate=None, weight=0.5) == 0.750


def test_adjusted_ops_below_league_average_chase_rate_increases_ops():
    below_league = LEAGUE_AVG_CHASE_RATE - 0.05
    adjusted = _adjusted_ops(0.750, chase_rate=below_league, weight=0.5)
    assert adjusted > 0.750


def test_adjusted_ops_above_league_average_chase_rate_decreases_ops():
    above_league = LEAGUE_AVG_CHASE_RATE + 0.05
    adjusted = _adjusted_ops(0.750, chase_rate=above_league, weight=0.5)
    assert adjusted < 0.750


def test_m2_matches_baseline_when_chase_rates_equal_league_average():
    p_baseline = baseline_win_prob(_PAYLOAD)
    p_m2 = m2_chase_adjusted_win_prob(
        _PAYLOAD, home_chase_rate=LEAGUE_AVG_CHASE_RATE, away_chase_rate=LEAGUE_AVG_CHASE_RATE, weight=0.5,
    )
    assert p_m2 == pytest.approx(p_baseline)


def test_m2_home_advantage_when_home_has_better_discipline():
    p_baseline = baseline_win_prob(_PAYLOAD)
    p_m2 = m2_chase_adjusted_win_prob(
        _PAYLOAD, home_chase_rate=LEAGUE_AVG_CHASE_RATE - 0.10,
        away_chase_rate=LEAGUE_AVG_CHASE_RATE + 0.10, weight=0.5,
    )
    assert p_m2 > p_baseline


def _make_games(n_per_season: int = 30) -> list[dict]:
    games = []
    rng_state = 0
    for season in (2022, 2023, 2024):
        for i in range(n_per_season):
            rng_state = (rng_state * 1103515245 + 12345) % (2**31)
            home_won = 1 if (rng_state % 2 == 0) else 0
            games.append({
                "season": season,
                "payload": dict(_PAYLOAD),
                "home_won": home_won,
                "home_chase_rate": 0.25 if home_won else 0.31,
                "away_chase_rate": 0.31 if home_won else 0.25,
            })
    return games


def test_evaluate_m2_returns_expected_structure():
    games = _make_games()
    result = evaluate_m2(games, n_resamples=50, seed=1)

    assert result["hypothesis"] == "m2_chase_rate_offense_adjustment"
    assert result["n_games_covered"] == len(games)
    assert set(result["fold_weights"].keys()) == {2022, 2023, 2024}
    assert "delta_brier_mean" in result
    assert "meets_all_3_conditions" in result


def test_evaluate_m2_skips_games_without_result():
    games = _make_games(5)
    games[0]["home_won"] = None
    result = evaluate_m2(games, n_resamples=20, seed=1)
    assert result["n_games_covered"] == len(games) - 1
