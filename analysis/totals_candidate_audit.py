"""
T1 -- Especializacion por mercado de Totales (docs/data_source_design.md,
Linea 2). Hipotesis: la proyeccion de carreras totales calculada a partir
de las variables point-in-time YA validadas de `jsa/` (ERA/OPS con
shrinkage, park factor, promedios de liga -- via `historical_snapshot`,
solo lectura) predice el resultado real de Totales (over/under 8.5
carreras) mejor que un baseline sin señal especifica de equipo (siempre
proyectar el promedio de liga).

Cero ingesta nueva: el ground truth (carreras totales del juego) ya
existe en `historical_game.home_score`/`away_score`; las variables de
entrada ya existen en `historical_snapshot.payload`.

`project_total_runs()` es una RE-DERIVACION independiente (no un import)
de `jsa/engine/projected_runs.py::compute_projected_runs()` +
`jsa/config.py` + `jsa/engine/pillars/base.py::offense_factor()` --
aislamiento de codigo entre repos (ver README.md), documentado explicito
aqui para que cualquier drift entre las 2 formulas sea detectable por
inspeccion, no oculto. Constantes copiadas de `jsa/config.py` (valores
verificados contra el codigo fuente real, 2026-07-20): LEAGUE_AVG_ERA=4.30,
LEAGUE_AVG_RUNS_PER_GAME=4.50, OFFENSE_FACTOR_EXPONENT=1.8,
STARTER_WEIGHT_IN_PITCHING=0.65, HOME_FIELD_RUNS_BONUS=0.15.
"""

from __future__ import annotations

from scipy.stats import poisson

from analysis.stats_utils import bootstrap_delta_brier, brier_score, roc_auc

LEAGUE_AVG_ERA = 4.30
LEAGUE_AVG_RUNS_PER_GAME = 4.50
LEAGUE_OPS_FALLBACK = 0.750
OFFENSE_FACTOR_EXPONENT = 1.8
STARTER_WEIGHT_IN_PITCHING = 0.65
HOME_FIELD_RUNS_BONUS = 0.15

# Linea de Totales fija y externa (estandar de mercado MLB), NO derivada
# de los datos -- evita fuga de informacion que resultaria de elegir el
# umbral a partir del propio resultado real que se esta evaluando.
TOTALS_LINE = 8.5


def _offense_factor(team_ops: float, league_ops: float) -> float:
    if league_ops <= 0:
        return 1.0
    return (team_ops / league_ops) ** OFFENSE_FACTOR_EXPONENT


def _project_team_runs(
    team_ops: float, opp_starter_era: float, opp_bullpen_era: float, *,
    league_ops: float, league_era: float, park_factor: float, is_home: bool,
    league_avg_runs_per_game: float,
) -> float:
    off_factor = _offense_factor(team_ops, league_ops)
    opp_pitching_era = (
        STARTER_WEIGHT_IN_PITCHING * opp_starter_era
        + (1 - STARTER_WEIGHT_IN_PITCHING) * opp_bullpen_era
    )
    pitching_factor = opp_pitching_era / league_era if league_era > 0 else 1.0
    runs = league_avg_runs_per_game * off_factor * pitching_factor * park_factor
    if is_home:
        runs += HOME_FIELD_RUNS_BONUS
    return max(runs, 0.3)


def project_total_runs(payload: dict) -> float | None:
    """
    mu_home + mu_away, recalculado desde un `historical_snapshot.payload`
    real (GameSnapshot serializado) -- candidato T1. None si el payload
    esta vacio.
    """
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
    home_bullpen_era = payload.get("home_bullpen_era") if payload.get("home_bullpen_era") is not None else league_era
    away_bullpen_era = payload.get("away_bullpen_era") if payload.get("away_bullpen_era") is not None else league_era

    mu_home = _project_team_runs(
        home_ops, away_starter_era, away_bullpen_era, league_ops=league_ops,
        league_era=league_era, park_factor=park_factor, is_home=True,
        league_avg_runs_per_game=league_rpg,
    )
    mu_away = _project_team_runs(
        away_ops, home_starter_era, home_bullpen_era, league_ops=league_ops,
        league_era=league_era, park_factor=park_factor, is_home=False,
        league_avg_runs_per_game=league_rpg,
    )
    return mu_home + mu_away


def baseline_total_runs(payload: dict) -> float:
    """
    Baseline SIN señal especifica de equipo/park/pitcheo -- siempre el
    promedio de liga combinado (2x carreras/juego de liga). Aisla si la
    señal especifica del juego aporta algo mas alla de "un juego promedio
    de MLB", exactamente el mismo criterio de "sustituye vs. aporta algo
    nuevo" que ya aplico jsa/ (ver docs/scope_handoff.md).
    """
    league_rpg = (payload or {}).get("league_avg_runs_per_game") or LEAGUE_AVG_RUNS_PER_GAME
    return 2 * league_rpg


def poisson_over_prob(mu_total: float, line: float = TOTALS_LINE) -> float:
    """P(total > line), asumiendo que la suma de 2 Poisson es Poisson(mu_total)."""
    mu_total = max(mu_total, 0.1)
    threshold = int(line)  # ej. line=8.5 -> P(total >= 9) = 1 - P(total <= 8)
    return 1.0 - float(poisson.cdf(threshold, mu_total))


def evaluate_t1(games: list[dict], n_resamples: int = 500, seed: int = 20260720) -> dict:
    """
    games: lista de dicts con 'season', 'home_score', 'away_score', 'payload'.
    Evalua T1 (candidato) vs baseline (promedio de liga), por temporada y
    agregado (bootstrap CI sobre el pool completo).
    """
    model_probs, baseline_probs, actuals, seasons = [], [], [], []

    for g in games:
        payload = g.get("payload")
        home_score, away_score = g.get("home_score"), g.get("away_score")
        if payload is None or home_score is None or away_score is None:
            continue
        mu_model = project_total_runs(payload)
        if mu_model is None:
            continue
        mu_baseline = baseline_total_runs(payload)

        actual_total = home_score + away_score
        actual_over = 1 if actual_total > TOTALS_LINE else 0

        model_probs.append(poisson_over_prob(mu_model))
        baseline_probs.append(poisson_over_prob(mu_baseline))
        actuals.append(actual_over)
        seasons.append(g.get("season"))

    n_total = len(games)
    n_covered = len(actuals)
    coverage_pct = (100.0 * n_covered / n_total) if n_total else 0.0

    by_season: dict[int, dict] = {}
    for season in sorted(set(seasons)):
        idx = [i for i, s in enumerate(seasons) if s == season]
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
        "hypothesis": "t1_totals_specialization",
        "target": "totals",
        "totals_line": TOTALS_LINE,
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
