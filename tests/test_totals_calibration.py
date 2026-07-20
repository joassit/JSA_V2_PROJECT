import random

from analysis.totals_candidate_audit import (
    ALPHA_CANDIDATES,
    calibrate_prob,
    evaluate_t1b_calibrated,
)


def test_calibrate_prob_alpha_1_is_identity():
    assert calibrate_prob(0.9, 1.0) == 0.9
    assert calibrate_prob(0.2, 1.0) == 0.2


def test_calibrate_prob_alpha_0_collapses_to_half():
    assert calibrate_prob(0.9, 0.0) == 0.5
    assert calibrate_prob(0.1, 0.0) == 0.5


def test_calibrate_prob_midpoint():
    assert abs(calibrate_prob(0.9, 0.5) - 0.7) < 1e-9


def _synthetic_game(rng, season, true_alpha):
    """
    Genera un juego donde la probabilidad REAL de over depende del modelo
    (via project_total_runs) con una contraccion conocida (true_alpha) --
    permite verificar que el LOSO sweep recupera un alpha cercano al real.
    """
    home_ops = rng.uniform(0.65, 0.85)
    away_ops = rng.uniform(0.65, 0.85)
    payload = {
        "league_avg_runs_per_game": 4.5, "league_avg_ops": 0.750, "league_avg_era": 4.30,
        "park_factor": 1.0, "home_ops": home_ops, "away_ops": away_ops,
    }
    from analysis.totals_candidate_audit import poisson_over_prob, project_total_runs
    mu = project_total_runs(payload)
    p_raw = poisson_over_prob(mu)
    p_true = calibrate_prob(p_raw, true_alpha)
    actual_over = 1 if rng.random() < p_true else 0
    total = 9 if actual_over else 8
    return {
        "season": season, "payload": payload,
        "home_score": total // 2, "away_score": total - total // 2,
    }


def test_evaluate_t1b_recovers_known_alpha_and_beats_raw():
    rng = random.Random(2026)
    true_alpha = 0.4
    games = []
    for season in (2023, 2024, 2025):
        for _ in range(400):
            games.append(_synthetic_game(rng, season, true_alpha))

    result = evaluate_t1b_calibrated(games, n_resamples=200, seed=1)

    # El alpha elegido por LOSO en cada fold debe acercarse al real (0.4)
    # -- tolerancia de 2 pasos de la grilla (ALPHA_CANDIDATES esta en
    # pasos de 0.1).
    for fold in result["fold_alphas"].values():
        assert abs(fold["best_alpha"] - true_alpha) <= 0.2

    # Calibrado debe superar (o igualar de cerca) al crudo, ya que el
    # crudo esta sobreconfiado por construccion en este dataset sintetico.
    assert result["loso_brier_calibrated"] <= result["brier_t1_uncalibrated"] + 1e-6


def test_evaluate_t1b_returns_expected_keys():
    rng = random.Random(1)
    games = [_synthetic_game(rng, 2024, 1.0) for _ in range(50)] + [_synthetic_game(rng, 2025, 1.0) for _ in range(50)]
    result = evaluate_t1b_calibrated(games, n_resamples=20, seed=2)
    for key in (
        "fold_alphas", "alpha_stable_across_folds", "loso_brier_calibrated",
        "loso_auc_calibrated", "brier_baseline", "brier_t1_uncalibrated",
        "delta_brier_mean", "significant", "meets_all_3_conditions",
    ):
        assert key in result


def test_alpha_candidates_include_uncalibrated_case():
    assert 1.0 in ALPHA_CANDIDATES
