"""
M2 -- Chase Rate como ajuste al OPS general (Linea 1, componente
"Chase Rate" pendiente en el README -- M1 ya cerro la parte de OPS vs.
mano del abridor, ver docs/data_source_design.md). Hipotesis: el chase
rate point-in-time del equipo (% de swings a pitches FUERA de zona --
mas bajo = mejor disciplina de plato) ajusta el OPS general y mejora la
probabilidad de ganar el juego completo, comparado con usar el OPS
general solo (mismo baseline que M1 -- lo que ya usa `jsa/`).

Reusa `analysis.totals_candidate_audit._project_team_runs` (misma
formula base de proyeccion de carreras) y
`analysis.first5_candidate_audit.win_prob` (Skellam, sin excluir
empates) -- mismo patron que analysis/matchup_candidate_audit.py. El
peso de disciplina se elige via LEAVE-ONE-SEASON-OUT (mismo patron que
evaluate_t1b_calibrated en totals_candidate_audit.py): para cada
temporada excluida, el peso optimo se busca SOLO en las otras 4.
"""

from __future__ import annotations

from analysis.first5_candidate_audit import win_prob
from analysis.stats_utils import bootstrap_delta_brier, brier_score, roc_auc
from analysis.totals_candidate_audit import (
    LEAGUE_AVG_ERA, LEAGUE_AVG_RUNS_PER_GAME, LEAGUE_OPS_FALLBACK,
    STARTER_WEIGHT_IN_PITCHING, _project_team_runs,
)

# Chase rate promedio de liga -- valor de referencia PUBLICO (agregados
# historicos de Statcast en la era moderna rondan 28-31%), NO aprendido
# de los propios datos de test -- mismo criterio que LEAGUE_AVG_ERA=4.30
# en totals_candidate_audit.py.
LEAGUE_AVG_CHASE_RATE = 0.28

DISCIPLINE_WEIGHT_CANDIDATES: tuple[float, ...] = tuple(round(0.1 * i, 1) for i in range(0, 11))


def _adjusted_ops(general_ops: float | None, chase_rate: float | None, weight: float) -> float | None:
    """OPS general escalado por disciplina de plato: chase rate por
    debajo del promedio de liga sube el OPS ajustado (bonus), por
    encima lo baja (penalizacion). weight=0.0 o chase_rate=None ->
    OPS sin ajustar (candidato colapsa al baseline)."""
    if general_ops is None:
        return None
    if chase_rate is None or weight == 0.0:
        return general_ops
    return general_ops * (1 + weight * (LEAGUE_AVG_CHASE_RATE - chase_rate))


def _mu_pair(payload: dict, home_ops: float | None, away_ops: float | None) -> tuple[float, float] | None:
    if not payload:
        return None
    league_era = payload.get("league_avg_era") or LEAGUE_AVG_ERA
    league_ops = payload.get("league_avg_ops") or LEAGUE_OPS_FALLBACK
    league_rpg = payload.get("league_avg_runs_per_game") or LEAGUE_AVG_RUNS_PER_GAME
    park_factor = payload.get("park_factor") or 1.0

    home_ops = home_ops if home_ops is not None else league_ops
    away_ops = away_ops if away_ops is not None else league_ops
    away_starter_era = payload.get("away_starter_xera") if payload.get("away_starter_xera") is not None else league_era
    home_starter_era = payload.get("home_starter_xera") if payload.get("home_starter_xera") is not None else league_era
    home_bullpen_era = payload.get("home_bullpen_era") if payload.get("home_bullpen_era") is not None else league_era
    away_bullpen_era = payload.get("away_bullpen_era") if payload.get("away_bullpen_era") is not None else league_era

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
    """Baseline: OPS general de ambos equipos, sin ajuste -- lo mismo
    que ya usa `jsa/` (engine/pillars/offense.py)."""
    pair = _mu_pair(payload, payload.get("home_ops"), payload.get("away_ops"))
    if pair is None:
        return None
    return win_prob(*pair)


def m2_chase_adjusted_win_prob(
    payload: dict, home_chase_rate: float | None, away_chase_rate: float | None, weight: float,
) -> float | None:
    home_ops = _adjusted_ops(payload.get("home_ops"), home_chase_rate, weight)
    away_ops = _adjusted_ops(payload.get("away_ops"), away_chase_rate, weight)
    pair = _mu_pair(payload, home_ops, away_ops)
    if pair is None:
        return None
    return win_prob(*pair)


def _prepare_series(games: list[dict]) -> dict:
    baseline_probs: list[float] = []
    candidates_by_weight: dict[float, list[float]] = {w: [] for w in DISCIPLINE_WEIGHT_CANDIDATES}
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
        for weight in DISCIPLINE_WEIGHT_CANDIDATES:
            p = m2_chase_adjusted_win_prob(payload, g.get("home_chase_rate"), g.get("away_chase_rate"), weight)
            if p is None:
                row_ok = False
                break
            row_candidates[weight] = p
        if not row_ok:
            continue

        baseline_probs.append(p_baseline)
        for weight in DISCIPLINE_WEIGHT_CANDIDATES:
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


def evaluate_m2(games: list[dict], n_resamples: int = 500, seed: int = 20260720) -> dict:
    """
    LOSO real: para cada temporada excluida, el peso de disciplina
    optimo se busca SOLO en las otras 4 (nunca viendo la temporada de
    test) -- mismo patron que evaluate_t1b_calibrated().
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
        for weight in DISCIPLINE_WEIGHT_CANDIDATES:
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
        "hypothesis": "m2_chase_rate_offense_adjustment",
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
