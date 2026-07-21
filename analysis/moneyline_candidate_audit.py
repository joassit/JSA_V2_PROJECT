"""
ML1 -- Hipotesis de Moneyline (ganador del juego completo), pedida
explicitamente por el usuario ("Usa el protocolo de validacion") para
someter la proyeccion de ganador a 9 entradas al MISMO protocolo (LOSO +
bootstrap CI de 500 resamples + 3 condiciones) que ya se aplico a
T1/T1b/F1/M1/M2/M3.

Nota de alcance, importante: a diferencia de M1/M2/M3 (variables NUEVAS
point-in-time que `jsa/` no calcula), esta hipotesis reutiliza las MISMAS
variables base que ya usa `project_runs_pair()` (OPS, ERA de abridor/
bullpen, park factor) -- las mismas que el modelo Skellam de produccion de
`jsa/` ya usa para Moneyline, y que ese mismo reporte tecnico (2026-07-20)
documenta rindiendo peor que el mercado real. No hay dato genuinamente
nuevo aqui -- se corre porque el usuario lo pidio de forma explicita, no
porque cumpla el criterio de alcance original de este proyecto (ver
docs/scope_handoff.md). El resultado (pase o no las 3 condiciones) es
igualmente informativo.

Reusa `project_runs_pair()` y `calibrate_prob()` de
analysis/totals_candidate_audit.py -- no reimplementa la formula base.
"""

from __future__ import annotations

from scipy.stats import skellam

from analysis.stats_utils import bootstrap_delta_brier, brier_score, roc_auc
from analysis.totals_candidate_audit import (
    STARTER_WEIGHT_IN_PITCHING, calibrate_prob, project_runs_pair,
)

# Ventaja de localia historica de MLB -- cifra externa ampliamente citada
# en sabermetria (~54%), NO ajustada a partir de los datos de este
# proyecto (evita fuga de informacion) -- mismo criterio que el baseline
# de T1 (LEAGUE_AVG_RUNS_PER_GAME es tambien una constante externa, no
# derivada de este dataset). Baseline "sin señal especifica de equipo":
# predecir siempre la ventaja de localia promedio de la liga.
BASELINE_HOME_WIN_RATE = 0.54


def moneyline_win_prob(mu_home: float, mu_away: float) -> float:
    """
    P(home gana el juego completo) -- Skellam(mu_home, mu_away)
    RENORMALIZADO excluyendo la probabilidad de empate: un juego de 9
    entradas de MLB nunca puede terminar empatado (hay entradas extra
    hasta que haya ganador), a diferencia de First 5 (`win_prob()` en
    analysis/first5_candidate_audit.py, que SI deja el empate como
    resultado valido porque el juego sigue después de la 5ta).
    """
    mu_home, mu_away = max(mu_home, 0.05), max(mu_away, 0.05)
    p_home = 1.0 - float(skellam.cdf(0, mu_home, mu_away))
    p_away = float(skellam.cdf(-1, mu_home, mu_away))
    denom = p_home + p_away
    if denom <= 0:
        return 0.5
    return p_home / denom


def project_home_win_prob(payload: dict) -> float | None:
    """Formula candidata ML1 (cruda, sin calibrar): `project_runs_pair()`
    con el peso estandar de juego completo (`STARTER_WEIGHT_IN_PITCHING`,
    no el 0.90 especifico de F5) -> `moneyline_win_prob()`."""
    pair = project_runs_pair(payload, starter_weight=STARTER_WEIGHT_IN_PITCHING)
    if pair is None:
        return None
    mu_home, mu_away = pair
    return moneyline_win_prob(mu_home, mu_away)


def _prepare_series(games: list[dict]) -> dict:
    model_raw_probs, actuals, seasons = [], [], []
    for g in games:
        payload = g.get("payload")
        home_score, away_score = g.get("home_score"), g.get("away_score")
        if payload is None or home_score is None or away_score is None or home_score == away_score:
            continue
        p_model = project_home_win_prob(payload)
        if p_model is None:
            continue
        model_raw_probs.append(p_model)
        actuals.append(1 if home_score > away_score else 0)
        seasons.append(g.get("season"))
    return {
        "n_total": len(games),
        "model_raw_probs": model_raw_probs,
        "actuals": actuals,
        "seasons": seasons,
    }


def evaluate_ml1(games: list[dict], n_resamples: int = 500, seed: int = 20260721) -> dict:
    """ML1 crudo (sin calibrar) vs baseline de ventaja de localia fija."""
    s = _prepare_series(games)
    model_probs, actuals, seasons = s["model_raw_probs"], s["actuals"], s["seasons"]
    baseline_probs = [BASELINE_HOME_WIN_RATE] * len(actuals)

    n_total, n_covered = s["n_total"], len(actuals)
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
        "hypothesis": "ml1_moneyline_raw",
        "target": "moneyline",
        "baseline_home_win_rate": BASELINE_HOME_WIN_RATE,
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


ALPHA_CANDIDATES: tuple[float, ...] = (0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0)


def evaluate_ml1b_calibrated(
    games: list[dict], alpha_candidates: tuple[float, ...] = ALPHA_CANDIDATES,
    n_resamples: int = 500, seed: int = 20260721,
) -> dict:
    """
    ML1b -- misma proyeccion cruda de ML1, con contraccion hacia 0.5
    (`calibrate_prob`) elegida via LEAVE-ONE-SEASON-OUT: para cada
    temporada excluida, el alpha optimo se busca SOLO en las otras 4
    (nunca viendo la temporada evaluada), mismo procedimiento exacto que
    `evaluate_t1b_calibrated()` en analysis/totals_candidate_audit.py.
    """
    s = _prepare_series(games)
    model_raw, actuals, seasons = s["model_raw_probs"], s["actuals"], s["seasons"]
    baseline_probs = [BASELINE_HOME_WIN_RATE] * len(actuals)
    n_covered = len(actuals)
    seasons_sorted = sorted(set(seasons))

    fold_alphas: dict[int, dict] = {}
    loso_calibrated_probs: list[float | None] = [None] * n_covered

    for held_out in seasons_sorted:
        train_idx = [i for i, sn in enumerate(seasons) if sn != held_out]
        test_idx = [i for i, sn in enumerate(seasons) if sn == held_out]

        best_alpha, best_train_brier = None, float("inf")
        for alpha in alpha_candidates:
            train_probs = [calibrate_prob(model_raw[i], alpha) for i in train_idx]
            train_actuals = [actuals[i] for i in train_idx]
            b = brier_score(train_probs, train_actuals)
            if b is not None and b < best_train_brier:
                best_train_brier, best_alpha = b, alpha

        fold_alphas[held_out] = {"best_alpha": best_alpha, "train_brier": best_train_brier, "n_test": len(test_idx)}
        for i in test_idx:
            loso_calibrated_probs[i] = calibrate_prob(model_raw[i], best_alpha)

    bootstrap = bootstrap_delta_brier(loso_calibrated_probs, baseline_probs, actuals, n_resamples=n_resamples, seed=seed)
    effect_size_ok = bootstrap["delta_brier_mean"] is not None and abs(bootstrap["delta_brier_mean"]) >= 0.001
    meets_all_3 = bool(
        bootstrap["delta_brier_mean"] is not None
        and bootstrap["delta_brier_mean"] < 0
        and bootstrap["significant"]
        and effect_size_ok
    )

    alphas_chosen = [v["best_alpha"] for v in fold_alphas.values()]
    alpha_stable = len(set(alphas_chosen)) == 1 if alphas_chosen else False

    return {
        "hypothesis": "ml1b_moneyline_calibrated",
        "target": "moneyline",
        "baseline_home_win_rate": BASELINE_HOME_WIN_RATE,
        "n_games_covered": n_covered,
        "fold_alphas": fold_alphas,
        "alpha_stable_across_folds": alpha_stable,
        "loso_brier_calibrated": brier_score(loso_calibrated_probs, actuals),
        "loso_auc_calibrated": roc_auc(loso_calibrated_probs, actuals),
        "brier_baseline": brier_score(baseline_probs, actuals),
        "brier_ml1_uncalibrated": brier_score(model_raw, actuals),
        **bootstrap,
        "effect_size_ok": effect_size_ok,
        "meets_all_3_conditions": meets_all_3,
    }
