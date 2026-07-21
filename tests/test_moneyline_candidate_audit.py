import random

import pytest

from analysis.moneyline_candidate_audit import (
    ALPHA_CANDIDATES,
    BASELINE_HOME_WIN_RATE,
    evaluate_ml1,
    evaluate_ml1b_calibrated,
    moneyline_win_prob,
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
