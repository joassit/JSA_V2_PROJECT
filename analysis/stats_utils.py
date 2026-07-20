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
