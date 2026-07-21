"""
Wind1 -- Hipotesis de viento sobre Totales, encima de Weather1 (Linea 2,
segunda extension de clima). Pedido explicito del usuario ("Con todo,
haz todo lo que...", 2026-07-21) -- el viento (`wind_raw`) ya esta
ingerido en `weather_snapshot` (mismo `/feed/live` que temp/condition),
cero ingesta nueva.

Pregunta que se prueba: ¿el viento aporta señal NUEVA mas alla de lo que
Weather1 (T1b + temperatura) ya predice? El baseline aqui es Weather1
mismo, no uno mas debil -- mismo criterio metodologico que Weather1 uso
contra T1b.

`wind_raw` viene en formato libre de MLB Stats API, ej. "10 mph, Out To
CF", "5 mph, In From LF", "8 mph, L To R", "0 mph, Calm" -- se reduce a
un efecto firmado en mph: positivo si sopla "Out" (empuja la pelota, mas
carreras), negativo si sopla "In" (la frena), 0 en cualquier otro caso
(cruzado L/R, calmo, o formato no reconocido).
"""

from __future__ import annotations

import math
import re

from analysis.stats_utils import bootstrap_delta_brier, brier_score, roc_auc
from analysis.totals_candidate_audit import TOTALS_LINE
from analysis.weather_candidate_audit import predict_totals_over_prob_weather_adjusted

COEF_CANDIDATES: tuple[float, ...] = (
    -0.04, -0.03, -0.02, -0.01, -0.005, 0.0, 0.005, 0.01, 0.02, 0.03, 0.04, 0.05,
)

_WIND_SPEED_RE = re.compile(r"(\d+(?:\.\d+)?)\s*mph", re.IGNORECASE)


def parse_wind_effect(wind_raw: str | None) -> float:
    """
    Efecto firmado de viento en mph -- positivo si sopla "Out" (empuja
    la pelota, mas carreras), negativo si sopla "In" (la frena), 0 si es
    cruzado (L To R / R To L), calmo, o el formato no se reconoce
    (ej. "Varies", string vacio, None).
    """
    if not wind_raw:
        return 0.0
    match = _WIND_SPEED_RE.search(wind_raw)
    if match is None:
        return 0.0
    speed = float(match.group(1))
    lowered = wind_raw.lower()
    if "out" in lowered:
        return speed
    if "in" in lowered:
        return -speed
    return 0.0


def _safe_logit(p: float) -> float:
    p = min(max(p, 1e-6), 1 - 1e-6)
    return math.log(p / (1 - p))


def _sigmoid(z: float) -> float:
    z = min(max(z, -35.0), 35.0)
    return 1.0 / (1.0 + math.exp(-z))


def wind_adjust_prob(p_baseline: float, wind_effect_mph: float, coef: float) -> float:
    """p_ajustada = sigmoid(logit(p_baseline) + coef*wind_effect_mph).
    wind_effect_mph=0 (calmo/cruzado/desconocido) -> sin ajuste, sin
    importar el coef."""
    return _sigmoid(_safe_logit(p_baseline) + coef * wind_effect_mph)


def _prepare_series(games: list[dict]) -> dict:
    """
    games: lista de dicts con 'season', 'payload', 'temp_f', 'wind_raw',
    'home_score', 'away_score'.
    """
    baseline_probs, wind_effects, actuals, seasons = [], [], [], []
    for g in games:
        payload = g.get("payload")
        temp_f = g.get("temp_f")
        home_score, away_score = g.get("home_score"), g.get("away_score")
        if payload is None or temp_f is None or home_score is None or away_score is None:
            continue
        p_baseline = predict_totals_over_prob_weather_adjusted(payload, temp_f)
        if p_baseline is None:
            continue
        baseline_probs.append(p_baseline)
        wind_effects.append(parse_wind_effect(g.get("wind_raw")))
        actuals.append(1 if (home_score + away_score) > TOTALS_LINE else 0)
        seasons.append(g.get("season"))
    return {
        "n_total": len(games),
        "baseline_probs": baseline_probs,
        "wind_effects": wind_effects,
        "actuals": actuals,
        "seasons": seasons,
    }


def evaluate_wind1(
    games: list[dict], coef_candidates: tuple[float, ...] = COEF_CANDIDATES,
    n_resamples: int = 500, seed: int = 20260721,
) -> dict:
    """Wind1 -- ¿el ajuste por viento mejora sobre Weather1 (el baseline
    aqui, no uno debil)? LEAVE-ONE-SEASON-OUT: el coeficiente optimo de
    cada fold se busca SOLO en las otras 4 temporadas."""
    s = _prepare_series(games)
    baseline_probs, wind_effects, actuals, seasons = (
        s["baseline_probs"], s["wind_effects"], s["actuals"], s["seasons"]
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
            train_probs = [wind_adjust_prob(baseline_probs[i], wind_effects[i], coef) for i in train_idx]
            train_actuals = [actuals[i] for i in train_idx]
            b = brier_score(train_probs, train_actuals)
            if b is not None and b < best_train_brier:
                best_train_brier, best_coef = b, coef

        fold_coefs[held_out] = {"best_coef": best_coef, "train_brier": best_train_brier, "n_test": len(test_idx)}
        for i in test_idx:
            loso_adjusted_probs[i] = wind_adjust_prob(baseline_probs[i], wind_effects[i], best_coef)

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

    # Coeficiente final para PRODUCCION: elegido sobre las 5 temporadas
    # COMPLETAS (LOSO es solo para validar que la mejora generaliza).
    full_best_coef, full_best_brier = None, float("inf")
    for coef in coef_candidates:
        full_probs = [wind_adjust_prob(baseline_probs[i], wind_effects[i], coef) for i in range(n_covered)]
        b = brier_score(full_probs, actuals)
        if b is not None and b < full_best_brier:
            full_best_brier, full_best_coef = b, coef

    return {
        "hypothesis": "wind1_wind_adjustment",
        "target": "totals",
        "n_games_total": n_total,
        "n_games_covered": n_covered,
        "coverage_pct": coverage_pct,
        "fold_coefs": fold_coefs,
        "coef_stable_across_folds": coef_stable,
        "full_data_best_coef": full_best_coef,
        "loso_brier_adjusted": brier_score(loso_adjusted_probs, actuals),
        "loso_auc_adjusted": roc_auc(loso_adjusted_probs, actuals),
        "brier_weather1_baseline": brier_score(baseline_probs, actuals),
        "auc_weather1_baseline": roc_auc(baseline_probs, actuals),
        **bootstrap,
        "effect_size_ok": effect_size_ok,
        "meets_all_3_conditions": meets_all_3,
    }
