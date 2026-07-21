import random

import pytest

from analysis.runline_candidate_audit import (
    ALPHA_CANDIDATES,
    RL1_PLATT_ADOPTED_A,
    RL1_PLATT_ADOPTED_B,
    RUN_LINE_MARGIN,
    baseline_home_covers_prob,
    evaluate_rl1,
    evaluate_rl1_platt_calibrated,
    evaluate_rl1b_calibrated,
    home_covers_prob,
    predict_runline_home_covers_prob,
    project_home_covers_prob,
)
from analysis.stats_utils import platt_calibrate


def test_run_line_margin_is_standard_mlb_value():
    assert RUN_LINE_MARGIN == 1.5


def test_home_covers_prob_favors_higher_mu_home():
    assert home_covers_prob(6.0, 3.0) > home_covers_prob(4.5, 4.5)


def test_home_covers_prob_bounded():
    assert 0.0 <= home_covers_prob(6.0, 1.0) <= 1.0
    assert 0.0 <= home_covers_prob(1.0, 6.0) <= 1.0


def test_home_covers_prob_lower_than_moneyline_win_prob():
    # Cubrir -1.5 (ganar por 2+) es un evento mas exigente que ganar por
    # cualquier margen -- P(cubre) <= P(gana).
    from analysis.moneyline_candidate_audit import moneyline_win_prob

    mu_home, mu_away = 5.0, 4.0
    assert home_covers_prob(mu_home, mu_away) <= moneyline_win_prob(mu_home, mu_away)


def test_project_home_covers_prob_none_when_payload_empty():
    assert project_home_covers_prob({}) is None


def test_baseline_home_covers_prob_uses_home_field_bonus():
    # Con bono de localia > 0, el baseline (equipos promedio) debe seguir
    # favoreciendo levemente al local -- P(cubre local) < P(cubre local
    # sin bono), pero > la mitad de lo que seria sin ninguna ventaja.
    baseline = baseline_home_covers_prob({})
    assert 0.0 < baseline < 0.5  # cubrir -1.5 es dificil incluso siendo levemente mejor


def _synthetic_game(rng, season, true_alpha):
    home_ops = rng.uniform(0.65, 0.85)
    away_ops = rng.uniform(0.65, 0.85)
    payload = {
        "league_avg_runs_per_game": 4.5, "league_avg_ops": 0.750, "league_avg_era": 4.30,
        "park_factor": 1.0, "home_ops": home_ops, "away_ops": away_ops,
    }
    from analysis.totals_candidate_audit import calibrate_prob, project_runs_pair

    pair = project_runs_pair(payload)
    p_raw = home_covers_prob(*pair)
    p_true = calibrate_prob(p_raw, true_alpha)
    home_covers = rng.random() < p_true
    return {
        "season": season, "payload": payload,
        "home_score": 6 if home_covers else 3,
        "away_score": 3 if home_covers else 4,
    }


def test_evaluate_rl1_returns_expected_keys():
    rng = random.Random(40)
    games = [_synthetic_game(rng, 2024, 1.0) for _ in range(60)] + [_synthetic_game(rng, 2025, 1.0) for _ in range(60)]
    result = evaluate_rl1(games, n_resamples=20, seed=41)
    for key in (
        "hypothesis", "target", "run_line_margin", "n_games_covered",
        "auc_model", "brier_model", "brier_baseline", "delta_brier_mean",
        "significant", "meets_all_3_conditions",
    ):
        assert key in result
    assert result["run_line_margin"] == RUN_LINE_MARGIN


def test_evaluate_rl1b_recovers_known_alpha():
    rng = random.Random(2029)
    true_alpha = 0.3
    games = []
    for season in (2023, 2024, 2025):
        for _ in range(400):
            games.append(_synthetic_game(rng, season, true_alpha))

    result = evaluate_rl1b_calibrated(games, n_resamples=200, seed=42)
    for fold in result["fold_alphas"].values():
        assert abs(fold["best_alpha"] - true_alpha) <= 0.2
    assert result["loso_brier_calibrated"] <= result["brier_rl1_uncalibrated"] + 1e-6


def test_evaluate_rl1_platt_returns_expected_keys():
    rng = random.Random(43)
    games = [_synthetic_game(rng, 2024, 1.0) for _ in range(60)] + [_synthetic_game(rng, 2025, 1.0) for _ in range(60)]
    result = evaluate_rl1_platt_calibrated(games, n_resamples=20, seed=44)
    for key in (
        "fold_platt_params", "full_data_platt_params", "loso_brier_platt",
        "brier_baseline", "brier_rl1_uncalibrated", "brier_rl1b_linear_calibrated",
        "delta_brier_mean", "meets_all_3_conditions",
    ):
        assert key in result


def test_alpha_candidates_include_uncalibrated_case():
    assert 1.0 in ALPHA_CANDIDATES


def test_predict_runline_home_covers_prob_matches_manual_pipeline():
    payload = {
        "league_avg_runs_per_game": 4.5, "league_avg_ops": 0.750, "league_avg_era": 4.30,
        "park_factor": 1.0, "home_ops": 0.780, "away_ops": 0.720,
    }
    expected = platt_calibrate(
        [project_home_covers_prob(payload)], RL1_PLATT_ADOPTED_A, RL1_PLATT_ADOPTED_B,
    )[0]
    assert predict_runline_home_covers_prob(payload) == pytest.approx(expected)


def test_predict_runline_home_covers_prob_none_when_payload_empty():
    assert predict_runline_home_covers_prob({}) is None
