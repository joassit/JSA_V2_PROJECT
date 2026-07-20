"""
F1 -- Especializacion por mercado First 5 Innings (docs/data_source_design.md,
Linea 2). Hipotesis: una reponderacion especifica de F5 (abridor domina,
bullpen casi no participa en las primeras 5 entradas) predice el ganador
real de F5 (ground truth de `linescore_game`, ingerido 2026-07-20) mejor
que usar la probabilidad de ganar el JUEGO COMPLETO (formula estandar,
`STARTER_WEIGHT_IN_PITCHING=0.65`) como proxy ingenuo -- exactamente la
pregunta que planteaba el diseno original antes de que existiera el
ground truth.

Reusa `project_runs_pair()` de analysis/totals_candidate_audit.py con un
`starter_weight` distinto -- no reimplementa la formula base.
"""

from __future__ import annotations

from scipy.stats import skellam

from analysis.stats_utils import bootstrap_delta_brier, brier_score, roc_auc
from analysis.totals_candidate_audit import STARTER_WEIGHT_IN_PITCHING, project_runs_pair

# El abridor lanza practicamente todas las primeras 5 entradas -- el
# bullpen casi no participa todavia (a diferencia del juego completo,
# donde el promedio historico de MLB es ~5.1-5.5 IP por abridor). 0.90
# es un valor conceptual, no calibrado -- el LOSO+bootstrap evalua si
# esta reponderacion concreta mejora sobre el proxy de juego completo.
STARTER_WEIGHT_F5 = 0.90

# Las primeras 5 de 9 entradas -- fraccion de las carreras proyectadas de
# 9 entradas que corresponderia a F5 si el ritmo de anotacion fuera
# uniforme por entrada (simplificacion; no modela que las entradas
# finales suelen anotar mas por decisiones de manager en juegos cerrados).
F5_INNING_FRACTION = 5 / 9


def win_prob(mu_a: float, mu_b: float) -> float:
    """P(A > B) para A~Poisson(mu_a), B~Poisson(mu_b) independientes."""
    mu_a, mu_b = max(mu_a, 0.05), max(mu_b, 0.05)
    return 1.0 - float(skellam.cdf(0, mu_a, mu_b))


def baseline_full_game_win_prob(payload: dict) -> float | None:
    """Proxy ingenuo: probabilidad de ganar el JUEGO COMPLETO (formula
    estandar de 9 entradas) usada tal cual para "quien gana F5"."""
    pair = project_runs_pair(payload, starter_weight=STARTER_WEIGHT_IN_PITCHING)
    if pair is None:
        return None
    mu_home, mu_away = pair
    return win_prob(mu_home, mu_away)


def f1_first5_win_prob(payload: dict) -> float | None:
    """Candidato F1: reponderado hacia el abridor + escalado a 5/9 entradas."""
    pair = project_runs_pair(payload, starter_weight=STARTER_WEIGHT_F5)
    if pair is None:
        return None
    mu_home, mu_away = pair
    return win_prob(mu_home * F5_INNING_FRACTION, mu_away * F5_INNING_FRACTION)


def evaluate_f1(games: list[dict], n_resamples: int = 500, seed: int = 20260720) -> dict:
    """
    games: lista de dicts con 'season', 'payload', 'home_f5_result'
    ('home'/'away'/'tie'). Objetivo binario: actual=1 si home gano F5,
    0 en cualquier otro caso (away o empate) -- un empate en F5 NO es lo
    mismo que ganar, asi que cuenta como "no home win", nunca se excluye.
    """
    model_probs, baseline_probs, actuals, seasons = [], [], [], []

    for g in games:
        payload = g.get("payload")
        f5_result = g.get("home_f5_result")
        if payload is None or f5_result is None:
            continue
        model_p = f1_first5_win_prob(payload)
        baseline_p = baseline_full_game_win_prob(payload)
        if model_p is None or baseline_p is None:
            continue

        model_probs.append(model_p)
        baseline_probs.append(baseline_p)
        actuals.append(1 if f5_result == "home" else 0)
        seasons.append(g.get("season"))

    n_total = len(games)
    n_covered = len(actuals)
    coverage_pct = (100.0 * n_covered / n_total) if n_total else 0.0

    by_season: dict[int, dict] = {}
    for season in sorted(set(seasons)):
        idx = [i for i, sn in enumerate(seasons) if sn == season]
        s_model = [model_probs[i] for i in idx]
        s_actuals = [actuals[i] for i in idx]
        by_season[season] = {
            "n": len(idx),
            "brier_model": brier_score(s_model, s_actuals),
            "auc_model": roc_auc(s_model, s_actuals),
        }

    bootstrap = bootstrap_delta_brier(model_probs, baseline_probs, actuals, n_resamples=n_resamples, seed=seed)
    effect_size_ok = bootstrap["delta_brier_mean"] is not None and abs(bootstrap["delta_brier_mean"]) >= 0.001
    meets_all_3 = bool(
        bootstrap["delta_brier_mean"] is not None
        and bootstrap["delta_brier_mean"] < 0
        and bootstrap["significant"]
        and effect_size_ok
    )

    return {
        "hypothesis": "f1_first5_specialization",
        "target": "first5",
        "n_games_total": n_total,
        "n_games_covered": n_covered,
        "coverage_pct": coverage_pct,
        "auc_model": roc_auc(model_probs, actuals),
        "auc_baseline": roc_auc(baseline_probs, actuals),
        "brier_model": brier_score(model_probs, actuals),
        "brier_baseline": brier_score(baseline_probs, actuals),
        "by_season": by_season,
        **bootstrap,
        "effect_size_ok": effect_size_ok,
        "meets_all_3_conditions": meets_all_3,
    }
