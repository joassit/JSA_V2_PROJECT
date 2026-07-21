import random

import pytest

from analysis.wind_candidate_audit import (
    COEF_CANDIDATES,
    evaluate_wind1,
    parse_wind_effect,
    wind_adjust_prob,
)


def test_parse_wind_effect_out_is_positive():
    assert parse_wind_effect("10 mph, Out To CF") == 10.0


def test_parse_wind_effect_in_is_negative():
    assert parse_wind_effect("5 mph, In From LF") == -5.0


def test_parse_wind_effect_cross_is_zero():
    assert parse_wind_effect("8 mph, L To R") == 0.0
    assert parse_wind_effect("8 mph, R To L") == 0.0


def test_parse_wind_effect_calm_is_zero():
    assert parse_wind_effect("0 mph, Calm") == 0.0


def test_parse_wind_effect_unrecognized_format_is_zero():
    assert parse_wind_effect("Varies") == 0.0
    assert parse_wind_effect(None) == 0.0
    assert parse_wind_effect("") == 0.0


def test_wind_adjust_prob_zero_effect_is_noop():
    assert wind_adjust_prob(0.6, 0.0, 0.05) == pytest.approx(0.6, abs=1e-9)


def test_wind_adjust_prob_positive_effect_increases_with_positive_coef():
    p_out = wind_adjust_prob(0.5, 10.0, 0.02)
    p_in = wind_adjust_prob(0.5, -10.0, 0.02)
    assert p_out > 0.5 > p_in


def _synthetic_game(rng, season, true_coef):
    from analysis.totals_candidate_audit import calibrate_prob, project_runs_pair
    from analysis.weather_candidate_audit import (
        WEATHER1_ADOPTED_COEF, predict_totals_over_prob_weather_adjusted, temp_adjust_prob,
    )

    payload = {
        "league_avg_runs_per_game": 4.5, "league_avg_ops": 0.750, "league_avg_era": 4.30,
        "park_factor": 1.0, "home_ops": rng.uniform(0.65, 0.85), "away_ops": rng.uniform(0.65, 0.85),
    }
    temp_f = rng.uniform(50.0, 90.0)
    wind_choices = ["10 mph, Out To CF", "10 mph, In From CF", "5 mph, L To R", "0 mph, Calm"]
    wind_raw = rng.choice(wind_choices)
    wind_effect = parse_wind_effect(wind_raw)

    p_baseline = predict_totals_over_prob_weather_adjusted(payload, temp_f)
    p_true = wind_adjust_prob(p_baseline, wind_effect, true_coef)
    actual_over = 1 if rng.random() < p_true else 0
    total = 9 if actual_over else 8
    return {
        "season": season, "payload": payload, "temp_f": temp_f, "wind_raw": wind_raw,
        "home_score": total // 2, "away_score": total - total // 2,
    }


def test_evaluate_wind1_returns_expected_keys():
    rng = random.Random(60)
    games = [_synthetic_game(rng, 2024, 0.0) for _ in range(60)] + [_synthetic_game(rng, 2025, 0.0) for _ in range(60)]
    result = evaluate_wind1(games, n_resamples=20, seed=61)
    for key in (
        "hypothesis", "target", "n_games_covered", "fold_coefs",
        "coef_stable_across_folds", "full_data_best_coef", "loso_brier_adjusted",
        "brier_weather1_baseline", "delta_brier_mean", "meets_all_3_conditions",
    ):
        assert key in result


def test_evaluate_wind1_recovers_known_coef_and_beats_baseline():
    rng = random.Random(2031)
    true_coef = 0.03
    games = []
    for season in (2023, 2024, 2025):
        for _ in range(1500):
            games.append(_synthetic_game(rng, season, true_coef))

    result = evaluate_wind1(games, n_resamples=200, seed=62)
    for fold in result["fold_coefs"].values():
        assert abs(fold["best_coef"] - true_coef) <= 0.02
    assert result["loso_brier_adjusted"] <= result["brier_weather1_baseline"] + 1e-6


def test_coef_candidates_include_zero():
    assert 0.0 in COEF_CANDIDATES
