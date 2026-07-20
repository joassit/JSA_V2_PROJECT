import random

from analysis.stats_utils import bootstrap_delta_brier, brier_score, roc_auc


def test_brier_score_perfect():
    assert brier_score([1.0, 0.0], [1, 0]) == 0.0


def test_brier_score_worst():
    assert brier_score([0.0, 1.0], [1, 0]) == 1.0


def test_brier_score_coinflip():
    assert brier_score([0.5, 0.5, 0.5, 0.5], [1, 0, 1, 0]) == 0.25


def test_brier_score_empty_returns_none():
    assert brier_score([], []) is None


def test_roc_auc_perfect_separation():
    probs = [0.9, 0.8, 0.2, 0.1]
    actuals = [1, 1, 0, 0]
    assert roc_auc(probs, actuals) == 1.0


def test_roc_auc_inverted_separation():
    probs = [0.1, 0.2, 0.8, 0.9]
    actuals = [1, 1, 0, 0]
    assert roc_auc(probs, actuals) == 0.0


def test_roc_auc_degenerate_single_class_is_none():
    assert roc_auc([0.5, 0.6, 0.7], [1, 1, 1]) is None


def test_roc_auc_ties_average_to_half():
    # 2 positivos, 2 negativos, mismo prob para todos -> AUC = 0.5 exacto
    assert roc_auc([0.5, 0.5, 0.5, 0.5], [1, 0, 1, 0]) == 0.5


def test_bootstrap_sanity_no_signal_when_identical():
    """Anti-fuga: candidato == baseline exactamente -> delta 0, nunca significativo."""
    rng = random.Random(1)
    probs = [rng.random() for _ in range(200)]
    actuals = [rng.randint(0, 1) for _ in range(200)]
    result = bootstrap_delta_brier(probs, probs, actuals, n_resamples=200, seed=42)
    assert result["delta_brier_mean"] == 0.0
    assert result["significant"] is False


def test_bootstrap_sanity_pure_noise_vs_pure_noise_not_significant():
    """Anti-fuga: 2 candidatos igual de no-informativos (coinflip) contra
    resultado real aleatorio -- no deberia haber señal detectada con
    confianza."""
    rng = random.Random(7)
    n = 500
    actuals = [rng.randint(0, 1) for _ in range(n)]
    probs_a = [0.5] * n
    probs_b = [0.5] * n
    result = bootstrap_delta_brier(probs_a, probs_b, actuals, n_resamples=300, seed=7)
    assert result["significant"] is False


def test_bootstrap_recovers_injected_real_signal():
    """El candidato usa la probabilidad REAL (perfectamente calibrada, con
    ruido minimo) mientras el baseline es un coinflip puro -- el candidato
    DEBE salir significativamente mejor (delta negativo, CI que no cruza
    cero). Mismo tipo de sanity check anti-fuga que usa jsa/ (recuperacion
    de señal inyectada)."""
    rng = random.Random(99)
    n = 800
    actuals = [rng.randint(0, 1) for _ in range(n)]
    # Candidato: predice el resultado real con alta confianza (0.9/0.1).
    probs_a = [0.9 if a == 1 else 0.1 for a in actuals]
    # Baseline: coinflip puro, sin informacion.
    probs_b = [0.5] * n

    result = bootstrap_delta_brier(probs_a, probs_b, actuals, n_resamples=300, seed=99)
    assert result["delta_brier_mean"] < 0
    assert result["significant"] is True
