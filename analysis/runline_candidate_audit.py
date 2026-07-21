"""
RL1 -- Hipotesis de Run Line (margen de victoria del local: ¿gana por 2 o
mas carreras, "cubre -1.5"?), pedida explicitamente por el usuario como
la extension mas barata posible del trabajo ya hecho: reusa la MISMA
distribucion Skellam(mu_home, mu_away) que ya calcula
`project_runs_pair()` (insumo de T1b/F1-Platt/ML1b), solo cambiando el
umbral de comparacion -- de "P(D>0)" (Moneyline) a "P(D>1.5)" (Run Line).
Cero ingesta nueva.

`RUN_LINE_MARGIN=1.5` es la linea estandar de Run Line en MLB (externa,
no derivada de los datos de este proyecto) -- mismo criterio que
`TOTALS_LINE=8.5` en totals_candidate_audit.py: evita fuga de
informacion que resultaria de elegir el umbral a partir del propio
resultado que se esta evaluando.

Nota de alcance, igual que ML1: reusa las MISMAS variables base que
T1b/F1-Platt/ML1b, no hay dato genuinamente nuevo. `jsa/` tampoco tiene
Run Line implementado en vivo (mismo hueco que Totales/First 5 tenian
antes de este proyecto, segun su reporte tecnico 2026-07-20).

Reusa `project_runs_pair()`/`calibrate_prob()` de
analysis/totals_candidate_audit.py -- no reimplementa la formula base.
"""

from __future__ import annotations

from scipy.stats import skellam

from analysis.stats_utils import (
    bootstrap_delta_brier, brier_score, fit_platt_params, platt_calibrate, roc_auc,
)
from analysis.totals_candidate_audit import (
    HOME_FIELD_RUNS_BONUS, LEAGUE_AVG_RUNS_PER_GAME, STARTER_WEIGHT_IN_PITCHING,
    calibrate_prob, project_runs_pair,
)

# Linea estandar de Run Line en MLB (externa, no derivada de los datos).
RUN_LINE_MARGIN = 1.5


def home_covers_prob(mu_home: float, mu_away: float, margin: float = RUN_LINE_MARGIN) -> float:
    """P(home_runs - away_runs > margin), asumiendo D=home-away ~
    Skellam(mu_home, mu_away). margin=1.5 -> P(D>=2) = 1-P(D<=1)."""
    mu_home, mu_away = max(mu_home, 0.05), max(mu_away, 0.05)
    threshold = int(margin)
    return 1.0 - float(skellam.cdf(threshold, mu_home, mu_away))


def project_home_covers_prob(payload: dict) -> float | None:
    """Formula candidata RL1 (cruda, sin calibrar): `project_runs_pair()`
    con el peso estandar de juego completo -> `home_covers_prob()`."""
    pair = project_runs_pair(payload, starter_weight=STARTER_WEIGHT_IN_PITCHING)
    if pair is None:
        return None
    mu_home, mu_away = pair
    return home_covers_prob(mu_home, mu_away)


def baseline_home_covers_prob(payload: dict) -> float:
    """
    Baseline SIN señal especifica de equipo -- ambos lados proyectados al
    promedio de liga, pero conservando el bono de localia (estructural
    del juego, no de la calidad del equipo) -- mismo criterio que
    `baseline_total_runs()` en totals_candidate_audit.py.
    """
    league_rpg = (payload or {}).get("league_avg_runs_per_game") or LEAGUE_AVG_RUNS_PER_GAME
    mu_avg = league_rpg / 2
    return home_covers_prob(mu_avg + HOME_FIELD_RUNS_BONUS, mu_avg)


def _prepare_series(games: list[dict]) -> dict:
    model_raw_probs, baseline_probs, actuals, seasons = [], [], [], []
    for g in games:
        payload = g.get("payload")
        home_score, away_score = g.get("home_score"), g.get("away_score")
        if payload is None or home_score is None or away_score is None:
            continue
        p_model = project_home_covers_prob(payload)
        if p_model is None:
            continue
        model_raw_probs.append(p_model)
        baseline_probs.append(baseline_home_covers_prob(payload))
        actuals.append(1 if (home_score - away_score) > RUN_LINE_MARGIN else 0)
        seasons.append(g.get("season"))
    return {
        "n_total": len(games),
        "model_raw_probs": model_raw_probs,
        "baseline_probs": baseline_probs,
        "actuals": actuals,
        "seasons": seasons,
    }


def evaluate_rl1(games: list[dict], n_resamples: int = 500, seed: int = 20260721) -> dict:
    """RL1 crudo (sin calibrar) vs baseline sin señal de equipo."""
    s = _prepare_series(games)
    model_probs, baseline_probs, actuals, seasons = (
        s["model_raw_probs"], s["baseline_probs"], s["actuals"], s["seasons"]
    )
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
        "hypothesis": "rl1_runline_raw",
        "target": "runline",
        "run_line_margin": RUN_LINE_MARGIN,
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


def evaluate_rl1b_calibrated(
    games: list[dict], alpha_candidates: tuple[float, ...] = ALPHA_CANDIDATES,
    n_resamples: int = 500, seed: int = 20260721,
) -> dict:
    """RL1b -- misma proyeccion cruda de RL1, con contraccion hacia 0.5
    (`calibrate_prob`) elegida via LEAVE-ONE-SEASON-OUT, mismo
    procedimiento que T1b/ML1b."""
    s = _prepare_series(games)
    model_raw, baseline_probs, actuals, seasons = (
        s["model_raw_probs"], s["baseline_probs"], s["actuals"], s["seasons"]
    )
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
        "hypothesis": "rl1b_runline_calibrated",
        "target": "runline",
        "run_line_margin": RUN_LINE_MARGIN,
        "n_games_covered": n_covered,
        "fold_alphas": fold_alphas,
        "alpha_stable_across_folds": alpha_stable,
        "loso_brier_calibrated": brier_score(loso_calibrated_probs, actuals),
        "loso_auc_calibrated": roc_auc(loso_calibrated_probs, actuals),
        "brier_baseline": brier_score(baseline_probs, actuals),
        "brier_rl1_uncalibrated": brier_score(model_raw, actuals),
        **bootstrap,
        "effect_size_ok": effect_size_ok,
        "meets_all_3_conditions": meets_all_3,
    }


# --- RL1-Platt ADOPTADO (autorizado explicitamente por el usuario, 2026-07-21) ---
# Calibracion logistica ajustada sobre las 5 temporadas COMPLETAS
# (13,101 juegos, sin excluir ninguna). A diferencia de T1/ML1 (donde el
# shrinkage lineal de 1 parametro ya bastaba), aca Platt es la MEJOR de
# las 3 variantes: delta_brier=-0.01260 vs. baseline (CI
# [-0.01436,-0.01072], significativo) Y delta_brier=-0.00465 vs. RL1b
# lineal (significativo) -- Platt le gana tambien a la version lineal, no
# solo al baseline. Ver docs/data_source_design.md, "Resultado real de
# RL1/RL1b/RL1-Platt".
RL1_PLATT_ADOPTED_A = 0.15210344440371978
RL1_PLATT_ADOPTED_B = -0.4420859447827888


def predict_runline_home_covers_prob(payload: dict) -> float | None:
    """
    Formula ADOPTADA de Run Line (RL1-Platt): project_runs_pair() (peso
    estandar) -> home_covers_prob() (P(home cubre -1.5)) ->
    platt_calibrate(a=RL1_PLATT_ADOPTED_A, b=RL1_PLATT_ADOPTED_B). P(el
    LOCAL cubre -1.5, gana por 2+ carreras). None si el payload no
    permite proyectar.
    """
    p_raw = project_home_covers_prob(payload)
    if p_raw is None:
        return None
    return platt_calibrate([p_raw], RL1_PLATT_ADOPTED_A, RL1_PLATT_ADOPTED_B)[0]


def evaluate_rl1_platt_calibrated(
    games: list[dict], n_resamples: int = 500, seed: int = 20260721,
) -> dict:
    """RL1-Platt -- misma proyeccion cruda de RL1, calibrada con
    regresion logistica de 2 parametros en vez del shrinkage lineal de
    RL1b. Se compara contra el baseline Y contra RL1b (lineal) para saber
    si Platt aporta algo mas."""
    s = _prepare_series(games)
    model_raw, baseline_probs, actuals, seasons = (
        s["model_raw_probs"], s["baseline_probs"], s["actuals"], s["seasons"]
    )
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

    # Fit final sobre TODOS los datos (no LOSO) -- constante de produccion
    # si Platt termina siendo la version adoptada.
    full_a, full_b = fit_platt_params(model_raw, actuals)

    # Comparacion directa contra RL1b (lineal) -- mismos juegos/folds.
    rl1b_result = evaluate_rl1b_calibrated(games, n_resamples=n_resamples, seed=seed)
    rl1b_alphas = [v["best_alpha"] for v in rl1b_result["fold_alphas"].values()]
    rl1b_stable_alpha = rl1b_alphas[0] if rl1b_result["alpha_stable_across_folds"] else None
    rl1b_calibrated_probs = (
        [calibrate_prob(model_raw[i], rl1b_stable_alpha) for i in range(n_covered)]
        if rl1b_stable_alpha is not None else None
    )
    vs_rl1b = (
        bootstrap_delta_brier(loso_platt_probs, rl1b_calibrated_probs, actuals, n_resamples=n_resamples, seed=seed)
        if rl1b_calibrated_probs is not None else None
    )

    return {
        "hypothesis": "rl1_platt_calibrated",
        "target": "runline",
        "run_line_margin": RUN_LINE_MARGIN,
        "n_games_covered": n_covered,
        "fold_platt_params": fold_platt,
        "full_data_platt_params": {"a": full_a, "b": full_b},
        "loso_brier_platt": brier_score(loso_platt_probs, actuals),
        "loso_auc_platt": roc_auc(loso_platt_probs, actuals),
        "brier_baseline": brier_score(baseline_probs, actuals),
        "brier_rl1_uncalibrated": brier_score(model_raw, actuals),
        "brier_rl1b_linear_calibrated": rl1b_result["loso_brier_calibrated"],
        "delta_brier_vs_rl1b_linear": vs_rl1b["delta_brier_mean"] if vs_rl1b else None,
        "vs_rl1b_significant": vs_rl1b["significant"] if vs_rl1b else None,
        **bootstrap,
        "effect_size_ok": effect_size_ok,
        "meets_all_3_conditions": meets_all_3,
    }
