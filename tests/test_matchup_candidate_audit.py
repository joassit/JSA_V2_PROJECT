import random

from analysis.matchup_candidate_audit import baseline_win_prob, evaluate_m1, m1_matchup_win_prob

_PAYLOAD = {
    "home_ops": 0.750, "away_ops": 0.750,
    "home_starter_xera": 4.30, "away_starter_xera": 4.30,
    "home_bullpen_era": 4.30, "away_bullpen_era": 4.30,
    "league_avg_runs_per_game": 4.5, "league_avg_ops": 0.750, "league_avg_era": 4.30,
    "park_factor": 1.0,
}


def test_baseline_uses_general_ops():
    p = baseline_win_prob(_PAYLOAD)
    assert p is not None
    assert 0.0 <= p <= 1.0


def test_m1_falls_back_to_general_ops_when_split_missing():
    m1_p = m1_matchup_win_prob(_PAYLOAD, None, None)
    baseline_p = baseline_win_prob(_PAYLOAD)
    assert abs(m1_p - baseline_p) < 1e-9


def test_m1_uses_handedness_specific_ops_when_present():
    baseline_p = baseline_win_prob(_PAYLOAD)
    # Home mucho mas fuerte especificamente contra la mano del abridor rival.
    m1_p = m1_matchup_win_prob(_PAYLOAD, home_ops_vs_away_hand=0.950, away_ops_vs_home_hand=0.750)
    assert m1_p > baseline_p


def test_m1_none_for_empty_payload():
    assert m1_matchup_win_prob(None, 0.8, 0.7) is None
    assert baseline_win_prob(None) is None


def _game(season, home_won, home_split=None, away_split=None):
    return {
        "season": season, "payload": dict(_PAYLOAD), "home_won": home_won,
        "home_ops_vs_away_hand": home_split, "away_ops_vs_home_hand": away_split,
    }


def test_evaluate_m1_coverage_excludes_incomplete():
    games = [
        _game(2024, 1, 0.8, 0.7),
        _game(2024, 0, None, None),  # sin split -- SI cuenta (cae al general, no se excluye)
        {"season": 2024, "payload": None, "home_won": 1, "home_ops_vs_away_hand": 0.8, "away_ops_vs_home_hand": 0.7},  # sin payload -- no cuenta
    ]
    result = evaluate_m1(games, n_resamples=10, seed=1)
    assert result["n_games_total"] == 3
    assert result["n_games_covered"] == 2


def test_evaluate_m1_returns_expected_keys():
    rng = random.Random(3)
    games = [_game(2024, rng.randint(0, 1), rng.uniform(0.6, 0.9), rng.uniform(0.6, 0.9)) for _ in range(40)]
    result = evaluate_m1(games, n_resamples=15, seed=2)
    for key in ("delta_brier_mean", "ci_low", "ci_high", "significant", "effect_size_ok", "meets_all_3_conditions"):
        assert key in result
