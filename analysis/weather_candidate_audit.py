"""
Weather1 -- Hipotesis de clima/temperatura sobre Totales (Linea 2,
extension). Pedido explicito del usuario ("agregamos un API") tras
confirmar en vivo (scripts/feasibility_spike_weather.py) que MLB Stats
API SI expone clima real para juegos ya jugados.

Pregunta que se prueba: ¿la temperatura real del juego mejora la
prediccion de T1b (Totales, YA adoptada) mas alla de lo que T1b ya
predice? El baseline de esta hipotesis es literalmente T1b -- no un
baseline mas debil -- porque la pregunta cientificamente honesta es "el
clima aporta algo NUEVO", no "el clima es mejor que no saber nada de los
equipos" (eso ya lo resolvio T1b).

Metodo: reponderar la probabilidad YA calibrada de T1b en espacio logit,
con un coeficiente sobre la desviacion de temperatura respecto a una
referencia externa (70°F, temperatura ambiente estandar, NO derivada de
este dataset): `p_ajustada = sigmoid(logit(p_T1b) + coef*(temp_f-70))`.
El coeficiente se elige via LEAVE-ONE-SEASON-OUT (mismo procedimiento
que alpha/Platt en T1b/F1-Platt/ML1b/RL1b).

Reusa `predict_totals_over_prob()` de analysis/totals_candidate_audit.py
-- no reimplementa la formula base.
"""

from __future__ import annotations

import math

from analysis.stats_utils import bootstrap_delta_brier, brier_score, roc_auc
from analysis.totals_candidate_audit import TOTALS_LINE, predict_totals_over_prob

# Referencia externa (temperatura ambiente estandar para beisbol en
# sabermetria), NO derivada de los datos de este proyecto -- mismo
# criterio que TOTALS_LINE=8.5 o BASELINE_HOME_WIN_RATE=0.54: evita fuga
# de informacion.
TEMP_REFERENCE_F = 70.0

COEF_CANDIDATES: tuple[float, ...] = (
    -0.03, -0.02, -0.015, -0.01, -0.005, 0.0, 0.005, 0.01, 0.015, 0.02, 0.03, 0.04,
)


def _safe_logit(p: float) -> float:
    p = min(max(p, 1e-6), 1 - 1e-6)
    return math.log(p / (1 - p))


def _sigmoid(z: float) -> float:
    z = min(max(z, -35.0), 35.0)
    return 1.0 / (1.0 + math.exp(-z))


def temp_adjust_prob(p_baseline: float, temp_f: float, coef: float) -> float:
    """p_ajustada = sigmoid(logit(p_baseline) + coef*(temp_f - TEMP_REFERENCE_F)).
    coef=0.0 -> identico a p_baseline (sin ajuste)."""
    return _sigmoid(_safe_logit(p_baseline) + coef * (temp_f - TEMP_REFERENCE_F))


def _prepare_series(games: list[dict]) -> dict:
    """
    games: lista de dicts con 'season', 'payload', 'temp_f', 'home_score',
    'away_score'. `payload` es el mismo GameSnapshot que ya usa T1b --
    `temp_f` viene de la ingesta nueva (weather_snapshot, cruzada por
    game_pk del lado del cliente, ver scripts/run_weather_candidate_audit.py).
    """
    baseline_probs, temps, actuals, seasons = [], [], [], []
    for g in games:
        payload = g.get("payload")
        temp_f = g.get("temp_f")
        home_score, away_score = g.get("home_score"), g.get("away_score")
        if payload is None or temp_f is None or home_score is None or away_score is None:
            continue
        p_baseline = predict_totals_over_prob(payload)
        if p_baseline is None:
            continue
        baseline_probs.append(p_baseline)
        temps.append(temp_f)
        actuals.append(1 if (home_score + away_score) > TOTALS_LINE else 0)
        seasons.append(g.get("season"))
    return {
        "n_total": len(games),
        "baseline_probs": baseline_probs,
        "temps": temps,
        "actuals": actuals,
        "seasons": seasons,
    }


def evaluate_weather1(
    games: list[dict], coef_candidates: tuple[float, ...] = COEF_CANDIDATES,
    n_resamples: int = 500, seed: int = 20260721,
) -> dict:
    """
    Weather1 -- ¿el ajuste por temperatura mejora sobre T1b (el baseline
    aqui, NO un baseline debil)? LEAVE-ONE-SEASON-OUT: el coeficiente
    optimo de cada fold se busca SOLO en las otras 4 temporadas.
    """
    s = _prepare_series(games)
    baseline_probs, temps, actuals, seasons = (
        s["baseline_probs"], s["temps"], s["actuals"], s["seasons"]
    )
    n_total, n_covered = s["n_total"], len(actuals)
    coverage_pct = (100.0 * n_covered / n_total) if n_total else 0.0
    seasons_sorted = sorted(set(seasons))

    fold_coefs: dict[int, dict] = {}
    loso_adjusted_probs: list[float | None] = [None] * n_covered

    for held_out in seasons_sorted:
        train_idx = [i for i, sn in enumerate(seasons) if sn != held_out]
        test_idx = [i for i, sn in enumerate(seasons) if sn == held_out]

        best_coef, best_train_brier = None, float("inf")
        for coef in coef_candidates:
            train_probs = [temp_adjust_prob(baseline_probs[i], temps[i], coef) for i in train_idx]
            train_actuals = [actuals[i] for i in train_idx]
            b = brier_score(train_probs, train_actuals)
            if b is not None and b < best_train_brier:
                best_train_brier, best_coef = b, coef

        fold_coefs[held_out] = {"best_coef": best_coef, "train_brier": best_train_brier, "n_test": len(test_idx)}
        for i in test_idx:
            loso_adjusted_probs[i] = temp_adjust_prob(baseline_probs[i], temps[i], best_coef)

    bootstrap = bootstrap_delta_brier(loso_adjusted_probs, baseline_probs, actuals, n_resamples=n_resamples, seed=seed)
    effect_size_ok = bootstrap["delta_brier_mean"] is not None and abs(bootstrap["delta_brier_mean"]) >= 0.001
    meets_all_3 = bool(
        bootstrap["delta_brier_mean"] is not None
        and bootstrap["delta_brier_mean"] < 0
        and bootstrap["significant"]
        and effect_size_ok
    )

    coefs_chosen = [v["best_coef"] for v in fold_coefs.values()]
    coef_stable = len(set(coefs_chosen)) == 1 if coefs_chosen else False

    return {
        "hypothesis": "weather1_temperature_adjustment",
        "target": "totals",
        "temp_reference_f": TEMP_REFERENCE_F,
        "n_games_total": n_total,
        "n_games_covered": n_covered,
        "coverage_pct": coverage_pct,
        "fold_coefs": fold_coefs,
        "coef_stable_across_folds": coef_stable,
        "loso_brier_adjusted": brier_score(loso_adjusted_probs, actuals),
        "loso_auc_adjusted": roc_auc(loso_adjusted_probs, actuals),
        "brier_t1b_baseline": brier_score(baseline_probs, actuals),
        "auc_t1b_baseline": roc_auc(baseline_probs, actuals),
        **bootstrap,
        "effect_size_ok": effect_size_ok,
        "meets_all_3_conditions": meets_all_3,
    }
