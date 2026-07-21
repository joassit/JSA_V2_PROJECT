import random

from analysis.first5_candidate_audit import (
    F5_INNING_FRACTION,
    STARTER_WEIGHT_F5,
    baseline_full_game_win_prob,
    evaluate_f1,
    evaluate_f1_platt_calibrated,
    f1_first5_win_prob,
    predict_first5_home_win_prob,
    win_prob,
)


def test_predict_first5_home_win_prob_is_f1_alias():
    # predict_first5_home_win_prob es la formula F1 ADOPTADA -- mismo
    # objeto que f1_first5_win_prob, expuesta con nombre consistente a
    # predict_totals_over_prob() (T1b).
    assert predict_first5_home_win_prob is f1_first5_win_prob


def test_win_prob_equal_strength_is_symmetric_below_half():
    # P(A>B) para A,B ~ Poisson(mu) iid NO es 0.5 exacto -- hay
    # probabilidad real de empate (P(A=B)>0), asi que P(A>B)=P(A<B) <
    # 0.5 por construccion. Deliberado (no se excluye el empate, a
    # diferencia del skellam_win_prob de jsa/ para el juego completo,
    # que SI renormaliza excluyendo empate porque un juego de 9 entradas
    # no puede terminar empatado -- F5 si puede).
    p = win_prob(4.5, 4.5)
    assert p < 0.5
    assert abs(p - win_prob(4.5, 4.5)) < 1e-9  # determinista


def test_win_prob_favors_higher_mu():
    assert win_prob(6.0, 3.0) > 0.5
    assert win_prob(3.0, 6.0) < 0.5


def test_win_prob_bounded():
    assert 0.0 <= win_prob(10, 0.1) <= 1.0
    assert 0.0 <= win_prob(0.1, 10) <= 1.0


def test_f1_prob_none_for_empty_payload():
    assert f1_first5_win_prob(None) is None
    assert f1_first5_win_prob({}) is None
    assert baseline_full_game_win_prob(None) is None


def test_f1_and_baseline_agree_on_direction_when_home_much_stronger():
    payload = {
        "home_ops": 0.950, "away_ops": 0.600,
        "home_starter_xera": 2.50, "away_starter_xera": 6.00,
        "home_bullpen_era": 3.00, "away_bullpen_era": 5.50,
        "league_avg_runs_per_game": 4.5, "league_avg_ops": 0.750, "league_avg_era": 4.30,
        "park_factor": 1.0,
    }
    model_p = f1_first5_win_prob(payload)
    baseline_p = baseline_full_game_win_prob(payload)
    assert model_p > 0.5
    assert baseline_p > 0.5


def test_constants_reasonable():
    assert 0.5 < STARTER_WEIGHT_F5 <= 1.0
    assert abs(F5_INNING_FRACTION - 5 / 9) < 1e-9


def _synthetic_game(rng, season):
    payload = {
        "home_ops": rng.uniform(0.65, 0.85), "away_ops": rng.uniform(0.65, 0.85),
        "home_starter_xera": rng.uniform(3.0, 5.5), "away_starter_xera": rng.uniform(3.0, 5.5),
        "home_bullpen_era": rng.uniform(3.5, 5.0), "away_bullpen_era": rng.uniform(3.5, 5.0),
        "league_avg_runs_per_game": 4.5, "league_avg_ops": 0.750, "league_avg_era": 4.30,
        "park_factor": 1.0,
    }
    result = rng.choice(["home", "away", "tie"])
    return {"season": season, "payload": payload, "home_f5_result": result}


def test_evaluate_f1_coverage_and_keys():
    rng = random.Random(11)
    games = [_synthetic_game(rng, 2024) for _ in range(60)] + [_synthetic_game(rng, 2025) for _ in range(60)]
    # Un juego sin payload y otro sin resultado -- no deben contar para coverage.
    games.append({"season": 2024, "payload": None, "home_f5_result": "home"})
    games.append({"season": 2024, "payload": {"home_ops": 0.7}, "home_f5_result": None})

    result = evaluate_f1(games, n_resamples=20, seed=1)

    assert result["n_games_total"] == 122
    assert result["n_games_covered"] == 120
    assert set(result["by_season"].keys()) == {2024, 2025}
    for key in ("delta_brier_mean", "ci_low", "ci_high", "significant", "effect_size_ok", "meets_all_3_conditions"):
        assert key in result


def test_evaluate_f1_ties_count_as_not_home_win():
    games = [{"season": 2024, "payload": {"home_ops": 0.7, "away_ops": 0.7}, "home_f5_result": "tie"} for _ in range(10)]
    result = evaluate_f1(games, n_resamples=10, seed=2)
    assert result["n_games_covered"] == 10


def _synthetic_game_with_known_logistic_signal(rng, season, true_a, true_b):
    import numpy as np

    payload = {
        "home_ops": rng.uniform(0.65, 0.85), "away_ops": rng.uniform(0.65, 0.85),
        "home_starter_xera": rng.uniform(3.0, 5.5), "away_starter_xera": rng.uniform(3.0, 5.5),
        "home_bullpen_era": rng.uniform(3.5, 5.0), "away_bullpen_era": rng.uniform(3.5, 5.0),
        "league_avg_runs_per_game": 4.5, "league_avg_ops": 0.750, "league_avg_era": 4.30,
        "park_factor": 1.0,
    }
    p_raw = f1_first5_win_prob(payload)
    logit_raw = np.log(p_raw / (1 - p_raw))
    p_true = 1 / (1 + np.exp(-(true_a * logit_raw + true_b)))
    home_wins = rng.random() < p_true
    return {"season": season, "payload": payload, "home_f5_result": "home" if home_wins else "away"}


def test_evaluate_f1_platt_returns_expected_keys():
    rng = random.Random(21)
    games = (
        [_synthetic_game_with_known_logistic_signal(rng, 2024, 0.5, 0.0) for _ in range(60)]
        + [_synthetic_game_with_known_logistic_signal(rng, 2025, 0.5, 0.0) for _ in range(60)]
    )
    result = evaluate_f1_platt_calibrated(games, n_resamples=20, seed=22)
    for key in (
        "fold_platt_params", "loso_brier_platt", "brier_baseline",
        "brier_f1_uncalibrated", "delta_brier_vs_f1_uncalibrated",
        "delta_brier_mean", "significant", "meets_all_3_conditions",
    ):
        assert key in result


def test_evaluate_f1_platt_beats_baseline_with_injected_signal():
    rng = random.Random(2027)
    games = []
    for season in (2023, 2024, 2025):
        for _ in range(400):
            games.append(_synthetic_game_with_known_logistic_signal(rng, season, 0.6, 0.0))

    result = evaluate_f1_platt_calibrated(games, n_resamples=100, seed=23)
    assert result["loso_brier_platt"] < result["brier_baseline"]
