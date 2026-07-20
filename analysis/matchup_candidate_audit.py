"""
M1 -- Matchup Pitcher vs Lineup por mano (docs/data_source_design.md,
Linea 1). Hipotesis: sustituir el OPS general de temporada (`home_ops`/
`away_ops`, ya usado por `offense` en `jsa/`) por el OPS del lineup
ESPECIFICAMENTE contra la mano del abridor rival (point-in-time, via
`handedness_split_snapshot`, ingerido 2026-07-20) predice el resultado
del juego completo mejor -- distinto de Statcast H1 (que uso xwOBA de
equipo sin separar por mano).

Reusa win_prob() de analysis/first5_candidate_audit.py (misma formula
Skellam P(A>B), sin renormalizar excluyendo empate -- aqui no aplica de
todas formas porque un juego completo no puede empatar).
"""

from __future__ import annotations

from analysis.first5_candidate_audit import win_prob
from analysis.stats_utils import bootstrap_delta_brier, brier_score, roc_auc
from analysis.totals_candidate_audit import (
    LEAGUE_AVG_ERA,
    LEAGUE_AVG_RUNS_PER_GAME,
    LEAGUE_OPS_FALLBACK,
    STARTER_WEIGHT_IN_PITCHING,
    _project_team_runs,
)


def _mu_pair(payload: dict, home_ops: float, away_ops: float) -> tuple[float, float] | None:
    """Mismo `_project_team_runs` de T1/F1, pero con el OPS que decida el
    llamador (general o especifico-por-mano) en vez de leerlo del payload."""
    if not payload:
        return None
    league_era = payload.get("league_avg_era") or LEAGUE_AVG_ERA
    league_ops = payload.get("league_avg_ops") or LEAGUE_OPS_FALLBACK
    league_rpg = payload.get("league_avg_runs_per_game") or LEAGUE_AVG_RUNS_PER_GAME
    park_factor = payload.get("park_factor") or 1.0
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
    """OPS general de temporada (lo que ya usa `offense` en jsa/)."""
    if not payload:
        return None
    league_ops = payload.get("league_avg_ops") or LEAGUE_OPS_FALLBACK
    home_ops = payload.get("home_ops") if payload.get("home_ops") is not None else league_ops
    away_ops = payload.get("away_ops") if payload.get("away_ops") is not None else league_ops
    pair = _mu_pair(payload, home_ops, away_ops)
    return None if pair is None else win_prob(*pair)


def m1_matchup_win_prob(
    payload: dict, home_ops_vs_away_hand: float | None, away_ops_vs_home_hand: float | None,
) -> float | None:
    """
    Candidato M1: OPS especifico contra la mano del abridor rival.
    Cae al OPS general de ESE equipo (no al de liga) si falta el split
    especifico -- mismo criterio de fallback in-place que usa
    project_total_runs()/project_runs_pair() para otros campos faltantes.
    """
    if not payload:
        return None
    league_ops = payload.get("league_avg_ops") or LEAGUE_OPS_FALLBACK
    home_ops_general = payload.get("home_ops") if payload.get("home_ops") is not None else league_ops
    away_ops_general = payload.get("away_ops") if payload.get("away_ops") is not None else league_ops

    home_ops = home_ops_vs_away_hand if home_ops_vs_away_hand is not None else home_ops_general
    away_ops = away_ops_vs_home_hand if away_ops_vs_home_hand is not None else away_ops_general

    pair = _mu_pair(payload, home_ops, away_ops)
    return None if pair is None else win_prob(*pair)


def evaluate_m1(games: list[dict], n_resamples: int = 500, seed: int = 20260720) -> dict:
    """
    games: lista de dicts con 'season', 'payload', 'home_won' (0/1),
    'home_ops_vs_away_hand', 'away_ops_vs_home_hand' (estos 2 pueden ser
    None -- cobertura parcial esperada, ver coverage_pct).
    """
    model_probs, baseline_probs, actuals, seasons = [], [], [], []

    for g in games:
        payload = g.get("payload")
        home_won = g.get("home_won")
        if payload is None or home_won is None:
            continue
        model_p = m1_matchup_win_prob(payload, g.get("home_ops_vs_away_hand"), g.get("away_ops_vs_home_hand"))
        baseline_p = baseline_win_prob(payload)
        if model_p is None or baseline_p is None:
            continue

        model_probs.append(model_p)
        baseline_probs.append(baseline_p)
        actuals.append(home_won)
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
        "hypothesis": "m1_matchup_handedness",
        "target": "offense",
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
