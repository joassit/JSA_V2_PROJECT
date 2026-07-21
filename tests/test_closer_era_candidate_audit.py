import pytest

from analysis.closer_era_candidate_audit import (
    _adjusted_bullpen_era, baseline_win_prob, evaluate_m3, m3_closer_era_win_prob,
)

_PAYLOAD = {
    "home_ops": 0.750, "away_ops": 0.750,
    "home_starter_xera": 4.0, "away_starter_xera": 4.0,
    "home_bullpen_era": 4.0, "away_bullpen_era": 4.0,
}


def test_adjusted_bullpen_era_weight_zero_returns_general_unchanged():
    assert _adjusted_bullpen_era(4.0, closer_era=2.0, weight=0.0) == 4.0


def test_adjusted_bullpen_era_none_closer_era_returns_general_unchanged():
    assert _adjusted_bullpen_era(4.0, closer_era=None, weight=0.5) == 4.0


def test_adjusted_bullpen_era_blends_toward_closer_era():
    adjusted = _adjusted_bullpen_era(4.0, closer_era=2.0, weight=0.5)
    assert adjusted == pytest.approx(3.0)


def test_m3_matches_baseline_when_closer_era_equals_general():
    p_baseline = baseline_win_prob(_PAYLOAD)
    p_m3 = m3_closer_era_win_prob(_PAYLOAD, home_closer_era=4.0, away_closer_era=4.0, weight=0.5)
    assert p_m3 == pytest.approx(p_baseline)


def test_m3_home_advantage_when_away_closer_era_is_worse():
    # El cerrador rival (away) con ERA peor que el bullpen general
    # deberia subir la probabilidad de ganar del HOME (menos runs en
    # contra esperados para el away... espera: el bullpen de AWAY
    # afecta la ofensiva de HOME -- un peor cerrador away = mas runs
    # esperados para HOME = mayor prob. de ganar para HOME).
    p_baseline = baseline_win_prob(_PAYLOAD)
    p_m3 = m3_closer_era_win_prob(_PAYLOAD, home_closer_era=4.0, away_closer_era=8.0, weight=0.5)
    assert p_m3 > p_baseline


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
                "home_closer_era": 2.5 if home_won else 6.0,
                "away_closer_era": 6.0 if home_won else 2.5,
            })
    return games


def test_evaluate_m3_returns_expected_structure():
    games = _make_games()
    result = evaluate_m3(games, n_resamples=50, seed=1)

    assert result["hypothesis"] == "m3_closer_era_bullpen_adjustment"
    assert result["n_games_covered"] == len(games)
    assert set(result["fold_weights"].keys()) == {2022, 2023, 2024}
    assert "delta_brier_mean" in result
    assert "meets_all_3_conditions" in result


def test_evaluate_m3_skips_games_without_result():
    games = _make_games(5)
    games[0]["home_won"] = None
    result = evaluate_m3(games, n_resamples=20, seed=1)
    assert result["n_games_covered"] == len(games) - 1
