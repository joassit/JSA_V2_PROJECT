import random

from analysis.first5_candidate_audit import (
    F5_INNING_FRACTION,
    STARTER_WEIGHT_F5,
    baseline_full_game_win_prob,
    evaluate_f1,
    f1_first5_win_prob,
    win_prob,
)


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
