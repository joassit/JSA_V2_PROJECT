import random

import pytest

from analysis.moneyline_candidate_audit import (
    ALPHA_CANDIDATES,
    BASELINE_HOME_WIN_RATE,
    ML1B_ADOPTED_ALPHA,
    evaluate_ml1,
    evaluate_ml1_platt_calibrated,
    evaluate_ml1b_calibrated,
    moneyline_win_prob,
    predict_moneyline_home_win_prob,
    project_home_win_prob,
)


def test_moneyline_win_prob_equal_strength_is_half():
    # Sin ventaja de ninguno de los 2 lados, la probabilidad renormalizada
    # (excluyendo empate) debe ser exactamente 0.5 por simetria.
    assert moneyline_win_prob(4.5, 4.5) == pytest.approx(0.5)


def test_moneyline_win_prob_favors_higher_mu():
    assert moneyline_win_prob(6.0, 3.0) > 0.5
    assert moneyline_win_prob(3.0, 6.0) < 0.5


def test_moneyline_win_prob_never_returns_tie_mass():
    # A diferencia de win_prob() de F5, aqui la suma con el complemento
    # (calculado como el mismo par invertido) debe dar exactamente 1 --
    # prueba indirecta de que se renormalizo excluyendo el empate.
    p_home = moneyline_win_prob(5.0, 4.0)
    p_away = moneyline_win_prob(4.0, 5.0)
    assert p_home + p_away == pytest.approx(1.0)


def test_project_home_win_prob_none_when_payload_empty():
    assert project_home_win_prob({}) is None


def _synthetic_game(rng, season, true_alpha):
    home_ops = rng.uniform(0.65, 0.85)
    away_ops = rng.uniform(0.65, 0.85)
    payload = {
        "league_avg_runs_per_game": 4.5, "league_avg_ops": 0.750, "league_avg_era": 4.30,
        "park_factor": 1.0, "home_ops": home_ops, "away_ops": away_ops,
    }
    from analysis.moneyline_candidate_audit import moneyline_win_prob
    from analysis.totals_candidate_audit import calibrate_prob, project_runs_pair

    pair = project_runs_pair(payload)
    p_raw = moneyline_win_prob(*pair)
    p_true = calibrate_prob(p_raw, true_alpha)
    home_wins = rng.random() < p_true
    return {
        "season": season, "payload": payload,
        "home_score": 5 if home_wins else 3,
        "away_score": 3 if home_wins else 5,
    }


def test_evaluate_ml1_returns_expected_keys():
    rng = random.Random(3)
    games = [_synthetic_game(rng, 2024, 1.0) for _ in range(60)] + [_synthetic_game(rng, 2025, 1.0) for _ in range(60)]
    result = evaluate_ml1(games, n_resamples=20, seed=4)
    for key in (
        "hypothesis", "target", "baseline_home_win_rate", "n_games_covered",
        "auc_model", "brier_model", "brier_baseline", "delta_brier_mean",
        "significant", "meets_all_3_conditions",
    ):
        assert key in result
    assert result["baseline_home_win_rate"] == BASELINE_HOME_WIN_RATE


def test_evaluate_ml1b_recovers_known_alpha():
    rng = random.Random(2026)
    true_alpha = 0.3
    games = []
    for season in (2023, 2024, 2025):
        for _ in range(400):
            games.append(_synthetic_game(rng, season, true_alpha))

    result = evaluate_ml1b_calibrated(games, n_resamples=200, seed=5)
    for fold in result["fold_alphas"].values():
        assert abs(fold["best_alpha"] - true_alpha) <= 0.2
    assert result["loso_brier_calibrated"] <= result["brier_ml1_uncalibrated"] + 1e-6


def test_alpha_candidates_include_uncalibrated_case():
    assert 1.0 in ALPHA_CANDIDATES


def test_ml1b_adopted_alpha_matches_documented_result():
    # alpha=0.2 fue optimo en las 5 temporadas sin excepcion (LOSO real,
    # identico al de T1b) -- la formula adoptada debe usar exactamente
    # ese valor.
    assert ML1B_ADOPTED_ALPHA == 0.2


def test_predict_moneyline_home_win_prob_matches_manual_pipeline():
    payload = {
        "league_avg_runs_per_game": 4.5, "league_avg_ops": 0.750, "league_avg_era": 4.30,
        "park_factor": 1.0, "home_ops": 0.780, "away_ops": 0.720,
    }
    from analysis.totals_candidate_audit import calibrate_prob

    expected = calibrate_prob(project_home_win_prob(payload), ML1B_ADOPTED_ALPHA)
    assert predict_moneyline_home_win_prob(payload) == pytest.approx(expected)


def test_predict_moneyline_home_win_prob_none_when_payload_empty():
    assert predict_moneyline_home_win_prob({}) is None


def _synthetic_game_with_logistic_signal(rng, season, true_a, true_b):
    import numpy as np

    from analysis.totals_candidate_audit import project_runs_pair

    home_ops = rng.uniform(0.65, 0.85)
    away_ops = rng.uniform(0.65, 0.85)
    payload = {
        "league_avg_runs_per_game": 4.5, "league_avg_ops": 0.750, "league_avg_era": 4.30,
        "park_factor": 1.0, "home_ops": home_ops, "away_ops": away_ops,
    }
    pair = project_runs_pair(payload)
    p_raw = moneyline_win_prob(*pair)
    logit_raw = np.log(p_raw / (1 - p_raw))
    p_true = 1 / (1 + np.exp(-(true_a * logit_raw + true_b)))
    home_wins = rng.random() < p_true
    return {
        "season": season, "payload": payload,
        "home_score": 5 if home_wins else 3,
        "away_score": 3 if home_wins else 5,
    }


def test_evaluate_ml1_platt_returns_expected_keys():
    rng = random.Random(30)
    games = (
        [_synthetic_game_with_logistic_signal(rng, 2024, 0.5, 0.0) for _ in range(60)]
        + [_synthetic_game_with_logistic_signal(rng, 2025, 0.5, 0.0) for _ in range(60)]
    )
    result = evaluate_ml1_platt_calibrated(games, n_resamples=20, seed=31)
    for key in (
        "fold_platt_params", "loso_brier_platt", "brier_baseline",
        "brier_ml1_uncalibrated", "brier_ml1b_linear_calibrated",
        "delta_brier_vs_ml1b_linear", "delta_brier_mean", "meets_all_3_conditions",
    ):
        assert key in result


def test_evaluate_ml1_platt_beats_baseline_with_injected_signal():
    rng = random.Random(2028)
    games = []
    for season in (2023, 2024, 2025):
        for _ in range(400):
            games.append(_synthetic_game_with_logistic_signal(rng, season, 0.6, 0.0))

    result = evaluate_ml1_platt_calibrated(games, n_resamples=100, seed=32)
    assert result["loso_brier_platt"] < result["brier_baseline"]
