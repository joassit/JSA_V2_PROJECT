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

from analysis.stats_utils import (
    bootstrap_delta_brier, brier_score, fit_platt_params, platt_calibrate, roc_auc,
)
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
    """
    F1 CRUDO (sin calibrar) -- reponderado hacia el abridor
    (STARTER_WEIGHT_F5=0.90) + escalado a 5/9 entradas. Adoptado
    originalmente asi el 2026-07-21 (delta_brier_mean=-0.00165 vs. el
    proxy de juego completo), pero SUPERADO por F1-Platt (ver
    `predict_first5_home_win_prob()` mas abajo) -- este resultado
    demostro que la version cruda estaba mal calibrada de forma
    sistematica (b estable ~-0.155 en las 5 temporadas LOSO). Se
    mantiene expuesta porque sigue siendo el insumo de la version
    calibrada, y para que quede visible el "antes" de la comparacion.
    """
    pair = project_runs_pair(payload, starter_weight=STARTER_WEIGHT_F5)
    if pair is None:
        return None
    mu_home, mu_away = pair
    return win_prob(mu_home * F5_INNING_FRACTION, mu_away * F5_INNING_FRACTION)


# --- F1-Platt ADOPTADO (autorizado explicitamente por el usuario, 2026-07-21) ---
# Calibracion logistica ajustada sobre las 5 temporadas COMPLETAS
# (13,099 juegos, sin excluir ninguna -- LOSO es solo para validar que
# la mejora generaliza, ver evaluate_f1_platt_calibrated()).
# delta_brier vs. F1 sin calibrar = -0.02477 (CI [-0.02765,-0.02177],
# muy significativo) -- la mejora mas grande de todo el proyecto, mayor
# incluso que T1 crudo -> T1b. Reemplaza a f1_first5_win_prob() como la
# formula recomendada de First 5 para cualquier uso futuro.
F1_PLATT_ADOPTED_A = 0.1032248796519753
F1_PLATT_ADOPTED_B = -0.15656001534780914


def predict_first5_home_win_prob(payload: dict) -> float | None:
    """
    Formula ADOPTADA de First 5 Innings (F1-Platt) -- autorizado
    explicitamente por el usuario, 2026-07-21 (ver
    docs/data_source_design.md, "Resultado real de F1-Platt"):
    f1_first5_win_prob() (reponderado + escalado) ->
    platt_calibrate(a=F1_PLATT_ADOPTED_A, b=F1_PLATT_ADOPTED_B). None si
    el payload no permite proyectar.
    """
    p_raw = f1_first5_win_prob(payload)
    if p_raw is None:
        return None
    return platt_calibrate([p_raw], F1_PLATT_ADOPTED_A, F1_PLATT_ADOPTED_B)[0]


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


def evaluate_f1_platt_calibrated(
    games: list[dict], n_resamples: int = 500, seed: int = 20260721,
) -> dict:
    """
    F1-Platt -- a diferencia de T1/ML1, F1 NUNCA tuvo un paso de
    calibracion de probabilidad (la formula adoptada es reponderacion +
    escalado, sin `calibrate_prob`) -- esta es la PRIMERA vez que se
    prueba calibrar F1. Calibracion logistica de 2 parametros
    (`fit_platt_params()`/`platt_calibrate()`) sobre la probabilidad
    cruda de `f1_first5_win_prob()`, ajustada via LEAVE-ONE-SEASON-OUT
    (mismo procedimiento que T1-Platt/ML1-Platt). Se compara contra el
    mismo baseline de F1 (`baseline_full_game_win_prob`, el proxy de
    juego completo) Y contra la propia F1 SIN calibrar (ya adoptada), que
    aqui hace de "T1b/ML1b" -- el punto de comparacion previo.
    """
    model_raw, baseline_probs, actuals, seasons = [], [], [], []
    for g in games:
        payload = g.get("payload")
        f5_result = g.get("home_f5_result")
        if payload is None or f5_result is None:
            continue
        model_p = f1_first5_win_prob(payload)
        baseline_p = baseline_full_game_win_prob(payload)
        if model_p is None or baseline_p is None:
            continue
        model_raw.append(model_p)
        baseline_probs.append(baseline_p)
        actuals.append(1 if f5_result == "home" else 0)
        seasons.append(g.get("season"))

    n_covered = len(actuals)
    seasons_sorted = sorted(set(seasons))

    fold_platt: dict[int, dict] = {}
    loso_platt_probs: list[float | None] = [None] * n_covered

    for held_out in seasons_sorted:
        train_idx = [i for i, sn in enumerate(seasons) if sn != held_out]
        test_idx = [i for i, sn in enumerate(seasons) if sn == held_out]

        train_probs = [model_raw[i] for i in train_idx]
        train_actuals = [actuals[i] for i in train_idx]
        a, b = fit_platt_params(train_probs, train_actuals)
        train_brier = brier_score(platt_calibrate(train_probs, a, b), train_actuals)

        fold_platt[held_out] = {"a": a, "b": b, "train_brier": train_brier, "n_test": len(test_idx)}
        test_calibrated = platt_calibrate([model_raw[i] for i in test_idx], a, b)
        for i, p_cal in zip(test_idx, test_calibrated):
            loso_platt_probs[i] = p_cal

    bootstrap = bootstrap_delta_brier(loso_platt_probs, baseline_probs, actuals, n_resamples=n_resamples, seed=seed)
    effect_size_ok = bootstrap["delta_brier_mean"] is not None and abs(bootstrap["delta_brier_mean"]) >= 0.001
    meets_all_3 = bool(
        bootstrap["delta_brier_mean"] is not None
        and bootstrap["delta_brier_mean"] < 0
        and bootstrap["significant"]
        and effect_size_ok
    )

    # Comparacion directa contra F1 sin calibrar (ya adoptada) -- misma
    # metodologia, mismos folds/juegos.
    vs_f1_raw = bootstrap_delta_brier(loso_platt_probs, model_raw, actuals, n_resamples=n_resamples, seed=seed)

    # Parametros finales para PRODUCCION: ajustados sobre las 5
    # temporadas COMPLETAS (sin excluir ninguna) -- LOSO es solo para
    # validar que la mejora generaliza, no para elegir la constante que
    # se usa de ahi en adelante (mismo criterio que T1B_ADOPTED_ALPHA,
    # que tambien es un valor unico, no uno distinto por fold).
    full_a, full_b = fit_platt_params(model_raw, actuals)

    return {
        "hypothesis": "f1_platt_calibrated",
        "target": "first5",
        "n_games_covered": n_covered,
        "fold_platt_params": fold_platt,
        "full_data_platt_params": {"a": full_a, "b": full_b},
        "loso_brier_platt": brier_score(loso_platt_probs, actuals),
        "loso_auc_platt": roc_auc(loso_platt_probs, actuals),
        "brier_baseline": brier_score(baseline_probs, actuals),
        "brier_f1_uncalibrated": brier_score(model_raw, actuals),
        "delta_brier_vs_f1_uncalibrated": vs_f1_raw["delta_brier_mean"],
        "vs_f1_ci_low": vs_f1_raw["ci_low"],
        "vs_f1_ci_high": vs_f1_raw["ci_high"],
        "vs_f1_significant": vs_f1_raw["significant"],
        **bootstrap,
        "effect_size_ok": effect_size_ok,
        "meets_all_3_conditions": meets_all_3,
    }
