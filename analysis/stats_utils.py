"""
Utilidades estadisticas puras (sin red, sin DB) para candidate audits --
mismo protocolo que exige docs/scope_handoff.md: LOSO + bootstrap CI de
500 resamples + umbral de tamaño de efecto minimo, replicado aqui de
forma independiente (aislamiento de codigo, ver README.md) en vez de
importar jsa/historical/stats_utils.py del repo hermano.
"""

from __future__ import annotations

import random

import numpy as np
from scipy.optimize import minimize


def _safe_logit(p: np.ndarray) -> np.ndarray:
    p = np.clip(p, 1e-6, 1 - 1e-6)
    return np.log(p / (1 - p))


def _sigmoid(z: np.ndarray) -> np.ndarray:
    z = np.clip(z, -35, 35)
    return 1.0 / (1.0 + np.exp(-z))


def fit_platt_params(probs: list[float], actuals: list[int]) -> tuple[float, float]:
    """
    Calibracion logistica (Platt scaling): ajusta (a, b) de
    `p_cal = sigmoid(a*logit(p) + b)` minimizando el BRIER SCORE sobre
    (probs, actuals) -- deliberadamente el mismo objetivo de ajuste que el
    grid search de `calibrate_prob()` (shrinkage lineal de 1 parametro en
    totals_candidate_audit.py), no log-loss, para que comparar ambos
    metodos de calibracion sea una comparacion justa (mismo criterio de
    bondad de ajuste, distinta familia de funciones). 2 parametros en vez
    de 1: puede corregir sub/sobreconfianza de forma distinta en los
    extremos que en el centro, a diferencia del shrinkage lineal hacia
    0.5 (que aplica la misma correccion proporcional en todo el rango).
    `a=1, b=0` = identidad (sin cambio), es el punto de partida de la
    optimizacion.
    """
    logits = _safe_logit(np.asarray(probs, dtype=float))
    actuals_arr = np.asarray(actuals, dtype=float)

    def loss(params: np.ndarray) -> float:
        a, b = params
        preds = _sigmoid(a * logits + b)
        return float(np.mean((preds - actuals_arr) ** 2))

    result = minimize(
        loss, x0=np.array([1.0, 0.0]), method="Nelder-Mead",
        options={"xatol": 1e-7, "fatol": 1e-10, "maxiter": 4000},
    )
    return float(result.x[0]), float(result.x[1])


def platt_calibrate(probs: list[float], a: float, b: float) -> list[float]:
    """Aplica la calibracion logistica ya ajustada (`fit_platt_params()`)
    a una lista de probabilidades crudas."""
    logits = _safe_logit(np.asarray(probs, dtype=float))
    return _sigmoid(a * logits + b).tolist()


def ops_from_raw_counts(ab: int, h: int, bb: int, hbp: int, sf: int, tb: int) -> float | None:
    """
    OPS = OBP + SLG a partir de conteos crudos acumulados -- necesario
    porque `sitCodes` no tiene efecto combinado con `stats=byDateRange`
    (confirmado en vivo, ver scripts/diagnose_sitcodes_bydaterange.py),
    asi que la clasificacion por mano del lanzador rival y la acumulacion
    dia-por-dia se hacen en este codigo, no en la API (Camino 2 de
    docs/data_source_design.md). None si no hay muestra suficiente (AB=0).
    """
    denom_obp = ab + bb + hbp + sf
    if ab <= 0 or denom_obp <= 0:
        return None
    obp = (h + bb + hbp) / denom_obp
    slg = tb / ab
    return obp + slg


def brier_score(probs: list[float], actuals: list[int]) -> float | None:
    """Promedio de (prob - resultado_real)^2. None si no hay datos.
    0.0 = perfecto, 0.25 = tan bueno como decir 50% siempre."""
    if not probs:
        return None
    return sum((p - a) ** 2 for p, a in zip(probs, actuals)) / len(probs)


def roc_auc(probs: list[float], actuals: list[int]) -> float | None:
    """
    AUC via el metodo de rangos (equivalente a Mann-Whitney U / Wilcoxon
    rank-sum), O(n log n) -- evita el O(n_pos * n_neg) de comparar cada
    par explicitamente, relevante con miles de juegos. None si todos los
    resultados son la misma clase (AUC indefinida).
    """
    n = len(probs)
    if n == 0:
        return None
    paired = sorted(zip(probs, actuals))
    ranks = [0.0] * n
    i = 0
    while i < n:
        j = i
        while j < n and paired[j][0] == paired[i][0]:
            j += 1
        avg_rank = (i + j + 1) / 2.0  # rango promedio 1-indexado para el grupo empatado [i, j)
        for k in range(i, j):
            ranks[k] = avg_rank
        i = j

    n_pos = sum(1 for _, a in paired if a == 1)
    n_neg = n - n_pos
    if n_pos == 0 or n_neg == 0:
        return None

    sum_ranks_pos = sum(r for r, (_, a) in zip(ranks, paired) if a == 1)
    return (sum_ranks_pos - n_pos * (n_pos + 1) / 2) / (n_pos * n_neg)


def bootstrap_delta_brier(
    probs_a: list[float], probs_b: list[float], actuals: list[int],
    n_resamples: int = 500, seed: int | None = None,
) -> dict:
    """
    Compara probs_a (candidato) contra probs_b (baseline) sobre los MISMOS
    actuals, re-muestreando juegos con reemplazo. delta_brier_mean < 0
    significa que el candidato mejora sobre el baseline. `significant`
    = el intervalo de confianza del 95% (percentil 2.5-97.5) no cruza
    cero -- mismo criterio que jsa/historical/*_candidate_audit.py.
    """
    n = len(actuals)
    if n == 0:
        return {"delta_brier_mean": None, "ci_low": None, "ci_high": None, "significant": False, "n": 0}

    point_delta = brier_score(probs_a, actuals) - brier_score(probs_b, actuals)

    rng = random.Random(seed)
    probs_a_arr = np.asarray(probs_a)
    probs_b_arr = np.asarray(probs_b)
    actuals_arr = np.asarray(actuals)

    deltas = np.empty(n_resamples)
    for r in range(n_resamples):
        idx = [rng.randrange(n) for _ in range(n)]
        pa, pb, ac = probs_a_arr[idx], probs_b_arr[idx], actuals_arr[idx]
        deltas[r] = float(np.mean((pa - ac) ** 2) - np.mean((pb - ac) ** 2))

    ci_low, ci_high = (float(x) for x in np.percentile(deltas, [2.5, 97.5]))
    significant = (ci_low > 0) or (ci_high < 0)

    return {
        "delta_brier_mean": point_delta,
        "ci_low": ci_low,
        "ci_high": ci_high,
        "significant": significant,
        "n": n,
    }
