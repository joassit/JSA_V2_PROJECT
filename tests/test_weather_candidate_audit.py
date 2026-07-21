import random

import pytest

from analysis.weather_candidate_audit import (
    COEF_CANDIDATES,
    TEMP_REFERENCE_F,
    evaluate_weather1,
    temp_adjust_prob,
)


def test_temp_adjust_prob_zero_coef_is_noop():
    assert temp_adjust_prob(0.65, 90.0, 0.0) == pytest.approx(0.65, abs=1e-9)
    assert temp_adjust_prob(0.65, 40.0, 0.0) == pytest.approx(0.65, abs=1e-9)


def test_temp_adjust_prob_positive_coef_increases_with_heat():
    p_hot = temp_adjust_prob(0.5, 95.0, 0.01)
    p_cold = temp_adjust_prob(0.5, 40.0, 0.01)
    assert p_hot > 0.5 > p_cold


def test_temp_adjust_prob_at_reference_is_noop_regardless_of_coef():
    assert temp_adjust_prob(0.6, TEMP_REFERENCE_F, 0.05) == pytest.approx(0.6, abs=1e-9)


def _synthetic_game(rng, season, true_coef):
    from analysis.totals_candidate_audit import T1B_ADOPTED_ALPHA, calibrate_prob, predict_totals_over_prob, project_total_runs, poisson_over_prob

    home_ops = rng.uniform(0.65, 0.85)
    away_ops = rng.uniform(0.65, 0.85)
    payload = {
        "league_avg_runs_per_game": 4.5, "league_avg_ops": 0.750, "league_avg_era": 4.30,
        "park_factor": 1.0, "home_ops": home_ops, "away_ops": away_ops,
    }
    temp_f = rng.uniform(40.0, 100.0)
    p_baseline = predict_totals_over_prob(payload)
    p_true = temp_adjust_prob(p_baseline, temp_f, true_coef)
    actual_over = 1 if rng.random() < p_true else 0
    total = 9 if actual_over else 8
    return {
        "season": season, "payload": payload, "temp_f": temp_f,
        "home_score": total // 2, "away_score": total - total // 2,
    }


def test_evaluate_weather1_returns_expected_keys():
    rng = random.Random(50)
    games = [_synthetic_game(rng, 2024, 0.0) for _ in range(60)] + [_synthetic_game(rng, 2025, 0.0) for _ in range(60)]
    result = evaluate_weather1(games, n_resamples=20, seed=51)
    for key in (
        "hypothesis", "target", "temp_reference_f", "n_games_covered",
        "fold_coefs", "coef_stable_across_folds", "loso_brier_adjusted",
        "brier_t1b_baseline", "delta_brier_mean", "meets_all_3_conditions",
    ):
        assert key in result
    assert result["temp_reference_f"] == TEMP_REFERENCE_F


def test_evaluate_weather1_recovers_known_coef_and_beats_baseline():
    rng = random.Random(2030)
    true_coef = 0.015
    games = []
    for season in (2023, 2024, 2025):
        for _ in range(400):
            games.append(_synthetic_game(rng, season, true_coef))

    result = evaluate_weather1(games, n_resamples=200, seed=52)
    for fold in result["fold_coefs"].values():
        assert abs(fold["best_coef"] - true_coef) <= 0.02
    assert result["loso_brier_adjusted"] <= result["brier_t1b_baseline"] + 1e-6


def test_evaluate_weather1_no_signal_does_not_beat_baseline_falsely():
    # Temperatura pura ruido (sin relacion real con el resultado) -- no
    # deberia detectarse señal falsa con confianza.
    rng = random.Random(53)
    games = []
    for season in (2023, 2024, 2025):
        for _ in range(300):
            payload = {
                "league_avg_runs_per_game": 4.5, "league_avg_ops": 0.750, "league_avg_era": 4.30,
                "park_factor": 1.0, "home_ops": rng.uniform(0.65, 0.85), "away_ops": rng.uniform(0.65, 0.85),
            }
            from analysis.totals_candidate_audit import predict_totals_over_prob

            p = predict_totals_over_prob(payload)
            actual_over = 1 if rng.random() < p else 0
            total = 9 if actual_over else 8
            games.append({
                "season": season, "payload": payload, "temp_f": rng.uniform(40.0, 100.0),
                "home_score": total // 2, "away_score": total - total // 2,
            })

    result = evaluate_weather1(games, n_resamples=200, seed=54)
    assert not (result["significant"] and result["delta_brier_mean"] < 0)


def test_coef_candidates_include_zero():
    assert 0.0 in COEF_CANDIDATES
