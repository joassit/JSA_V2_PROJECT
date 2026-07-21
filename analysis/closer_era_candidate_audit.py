"""
M3 -- ERA del cerrador como ajuste al bullpen ERA general (Linea 3,
nueva). Hipotesis: mezclar el ERA especifico del cerrador rival (dato
que `jsa/` YA calcula internamente en `bullpen_era_as_of()` pero
descarta -- ver docs/data_source_design.md) con el bullpen ERA general
del payload mejora la probabilidad de ganar el juego completo,
comparado con usar el bullpen ERA general solo (mismo baseline que
M1/M2 -- lo que ya usa `jsa/`).

Reusa `analysis.totals_candidate_audit._project_team_runs` (misma
formula base de proyeccion de carreras) y
`analysis.first5_candidate_audit.win_prob` (Skellam, sin excluir
empates) -- mismo patron que matchup_candidate_audit.py y
chase_rate_candidate_audit.py. El peso del cerrador se elige via
LEAVE-ONE-SEASON-OUT (mismo patron que evaluate_t1b_calibrated).
"""

from __future__ import annotations

from analysis.first5_candidate_audit import win_prob
from analysis.stats_utils import bootstrap_delta_brier, brier_score, roc_auc
from analysis.totals_candidate_audit import (
    LEAGUE_AVG_ERA, LEAGUE_AVG_RUNS_PER_GAME, LEAGUE_OPS_FALLBACK,
    STARTER_WEIGHT_IN_PITCHING, _project_team_runs,
)

CLOSER_WEIGHT_CANDIDATES: tuple[float, ...] = tuple(round(0.1 * i, 1) for i in range(0, 11))


def _adjusted_bullpen_era(general_bullpen_era: float | None, closer_era: float | None, weight: float) -> float | None:
    """Mezcla el ERA del cerrador con el bullpen ERA general -- weight=0.0
    o closer_era=None colapsa al bullpen ERA general sin ajustar
    (candidato = baseline)."""
    if general_bullpen_era is None:
        return None
    if closer_era is None or weight == 0.0:
        return general_bullpen_era
    return weight * closer_era + (1 - weight) * general_bullpen_era


def _mu_pair(
    payload: dict, home_bullpen_era: float | None, away_bullpen_era: float | None,
) -> tuple[float, float] | None:
    if not payload:
        return None
    league_era = payload.get("league_avg_era") or LEAGUE_AVG_ERA
    league_ops = payload.get("league_avg_ops") or LEAGUE_OPS_FALLBACK
    league_rpg = payload.get("league_avg_runs_per_game") or LEAGUE_AVG_RUNS_PER_GAME
    park_factor = payload.get("park_factor") or 1.0

    home_ops = payload.get("home_ops") if payload.get("home_ops") is not None else league_ops
    away_ops = payload.get("away_ops") if payload.get("away_ops") is not None else league_ops
    away_starter_era = payload.get("away_starter_xera") if payload.get("away_starter_xera") is not None else league_era
    home_starter_era = payload.get("home_starter_xera") if payload.get("home_starter_xera") is not None else league_era
    home_bullpen_era = home_bullpen_era if home_bullpen_era is not None else league_era
    away_bullpen_era = away_bullpen_era if away_bullpen_era is not None else league_era

    # El bullpen del RIVAL castiga la ofensiva propia: mu_home usa el
    # bullpen de AWAY, mu_away usa el bullpen de HOME.
    mu_home = _project_team_runs(
        home_ops, away_starter_era, away_bullpen_era, league_ops=league_ops,
        league_era=league_era, park_factor=park_factor, is_home=True,
        league_avg_runs_per_game=league_rpg, starter_weight=STARTER_WEIGHT_IN_PITCHING,
    )
    mu_away = _project_team_runs(
        away_ops, home_starter_era, home_bullpen_era, league_ops=league_ops,
        league_era=league_era, park_factor=park_factor, is_home=False,
        league_avg_runs_per_game=league_rpg, starter_weight=STARTER_WEIGHT_IN_PITCHING,
    )
    return mu_home, mu_away


def baseline_win_prob(payload: dict) -> float | None:
    """Baseline: bullpen ERA general de ambos equipos, sin ajuste --
    lo mismo que ya usa `jsa/` (engine/pillars/bullpen.py)."""
    pair = _mu_pair(payload, payload.get("home_bullpen_era"), payload.get("away_bullpen_era"))
    if pair is None:
        return None
    return win_prob(*pair)


def m3_closer_era_win_prob(
    payload: dict, home_closer_era: float | None, away_closer_era: float | None, weight: float,
) -> float | None:
    home_bullpen = _adjusted_bullpen_era(payload.get("home_bullpen_era"), home_closer_era, weight)
    away_bullpen = _adjusted_bullpen_era(payload.get("away_bullpen_era"), away_closer_era, weight)
    pair = _mu_pair(payload, home_bullpen, away_bullpen)
    if pair is None:
        return None
    return win_prob(*pair)


def _prepare_series(games: list[dict]) -> dict:
    baseline_probs: list[float] = []
    candidates_by_weight: dict[float, list[float]] = {w: [] for w in CLOSER_WEIGHT_CANDIDATES}
    actuals: list[int] = []
    seasons: list[int] = []

    for g in games:
        payload = g.get("payload")
        if payload is None or g.get("home_won") not in (0, 1):
            continue
        p_baseline = baseline_win_prob(payload)
        if p_baseline is None:
            continue

        row_candidates = {}
        row_ok = True
        for weight in CLOSER_WEIGHT_CANDIDATES:
            p = m3_closer_era_win_prob(payload, g.get("home_closer_era"), g.get("away_closer_era"), weight)
            if p is None:
                row_ok = False
                break
            row_candidates[weight] = p
        if not row_ok:
            continue

        baseline_probs.append(p_baseline)
        for weight in CLOSER_WEIGHT_CANDIDATES:
            candidates_by_weight[weight].append(row_candidates[weight])
        actuals.append(g["home_won"])
        seasons.append(g["season"])

    return {
        "n_covered": len(actuals),
        "baseline_probs": baseline_probs,
        "candidates_by_weight": candidates_by_weight,
        "actuals": actuals,
        "seasons": seasons,
    }


def evaluate_m3(games: list[dict], n_resamples: int = 500, seed: int = 20260720) -> dict:
    """
    LOSO real: para cada temporada excluida, el peso del cerrador optimo
    se busca SOLO en las otras 4 (nunca viendo la temporada de test) --
    mismo patron que evaluate_t1b_calibrated().
    """
    s = _prepare_series(games)
    baseline_probs, candidates_by_weight, actuals, seasons = (
        s["baseline_probs"], s["candidates_by_weight"], s["actuals"], s["seasons"]
    )
    n_covered = s["n_covered"]
    seasons_sorted = sorted(set(seasons))

    fold_weights: dict[int, dict] = {}
    loso_probs: list[float | None] = [None] * n_covered

    for held_out in seasons_sorted:
        train_idx = [i for i, sn in enumerate(seasons) if sn != held_out]
        test_idx = [i for i, sn in enumerate(seasons) if sn == held_out]

        best_weight, best_train_brier = None, float("inf")
        for weight in CLOSER_WEIGHT_CANDIDATES:
            train_probs = [candidates_by_weight[weight][i] for i in train_idx]
            train_actuals = [actuals[i] for i in train_idx]
            b = brier_score(train_probs, train_actuals)
            if b is not None and b < best_train_brier:
                best_train_brier, best_weight = b, weight

        fold_weights[held_out] = {
            "best_weight": best_weight, "train_brier": best_train_brier, "n_test": len(test_idx),
        }
        for i in test_idx:
            loso_probs[i] = candidates_by_weight[best_weight][i]

    bootstrap = bootstrap_delta_brier(loso_probs, baseline_probs, actuals, n_resamples=n_resamples, seed=seed)
    effect_size_ok = bootstrap["delta_brier_mean"] is not None and abs(bootstrap["delta_brier_mean"]) >= 0.001
    meets_all_3 = bool(
        bootstrap["delta_brier_mean"] is not None
        and bootstrap["delta_brier_mean"] < 0
        and bootstrap["significant"]
        and effect_size_ok
    )

    weights_chosen = [v["best_weight"] for v in fold_weights.values()]
    weight_stable = len(set(weights_chosen)) == 1 if weights_chosen else False

    return {
        "hypothesis": "m3_closer_era_bullpen_adjustment",
        "target": "moneyline",
        "n_games_covered": n_covered,
        "coverage_pct": (100.0 * n_covered / len(games)) if games else 0.0,
        "fold_weights": fold_weights,
        "weight_stable_across_folds": weight_stable,
        "auc_model": roc_auc(loso_probs, actuals),
        "auc_baseline": roc_auc(baseline_probs, actuals),
        "brier_model": brier_score(loso_probs, actuals),
        "brier_baseline": brier_score(baseline_probs, actuals),
        **bootstrap,
        "effect_size_ok": effect_size_ok,
        "meets_all_3_conditions": meets_all_3,
    }
