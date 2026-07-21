"""
Corre RL1 (crudo) + RL1b (lineal) + RL1-Platt (logistico) contra el
historico REAL compartido y persiste los 3 resultados -- extension mas
barata posible del trabajo ya hecho (reusa Skellam(mu_home,mu_away) de
project_runs_pair(), solo cambia el umbral de comparacion respecto a
ML1). Cero ingesta nueva.
"""

from __future__ import annotations

import json
import os
import sys
import uuid
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
from analysis.runline_candidate_audit import (
    evaluate_rl1, evaluate_rl1_platt_calibrated, evaluate_rl1b_calibrated,
)
from data_sources.historical_readonly import get_games_with_snapshots_for_season
from db.database import CandidateAuditResult, SessionLocal, init_db


def load_all_seasons() -> list[dict]:
    games: list[dict] = []
    for season in config.HISTORICAL_SEASONS:
        season_games = get_games_with_snapshots_for_season(season)
        print(f"  temporada {season}: {len(season_games)} juegos con snapshot", file=sys.stderr)
        games.extend(season_games)
    return games


def persist(result: dict, run_id: str, auc_key: str, coverage_pct: float) -> None:
    with SessionLocal() as session:
        session.add(CandidateAuditResult(
            run_id=run_id,
            hypothesis_name=result["hypothesis"],
            target=result["target"],
            n_games=result["n_games_covered"],
            coverage_pct=coverage_pct,
            auc=result[auc_key],
            delta_brier_mean=result["delta_brier_mean"],
            ci_low=result["ci_low"],
            ci_high=result["ci_high"],
            significant=result["significant"],
            effect_size_ok=result["effect_size_ok"],
            meets_all_3_conditions=result["meets_all_3_conditions"],
        ))
        session.commit()


def main() -> int:
    run_id = f"rl1-runline-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}-{uuid.uuid4().hex[:8]}"
    init_db()

    print("Cargando juegos historicos...", file=sys.stderr)
    games = load_all_seasons()
    print(f"Total: {len(games)} juegos con snapshot.", file=sys.stderr)

    print("\n=== RL1 (crudo) ===", file=sys.stderr)
    rl1 = evaluate_rl1(games, n_resamples=config.BOOTSTRAP_RESAMPLES)
    print(json.dumps(rl1, indent=2, default=str))
    persist(rl1, run_id, "auc_model", rl1["coverage_pct"])

    print("\n=== RL1b (lineal, LOSO) ===", file=sys.stderr)
    rl1b = evaluate_rl1b_calibrated(games, n_resamples=config.BOOTSTRAP_RESAMPLES)
    print(json.dumps(rl1b, indent=2, default=str))
    persist(rl1b, run_id, "loso_auc_calibrated", 100.0)

    print("\n=== RL1-Platt (logistico, LOSO) ===", file=sys.stderr)
    rl1_platt = evaluate_rl1_platt_calibrated(games, n_resamples=config.BOOTSTRAP_RESAMPLES)
    print(json.dumps(rl1_platt, indent=2, default=str))
    persist(rl1_platt, run_id, "loso_auc_platt", 100.0)

    print(f"\nLos 3 resultados persistidos en candidate_audit_result (run_id={run_id}).", file=sys.stderr)

    for label, result in (("RL1 crudo", rl1), ("RL1b lineal", rl1b), ("RL1-Platt", rl1_platt)):
        veredicto = "cumple" if result["meets_all_3_conditions"] else "NO cumple"
        print(f"\nVEREDICTO {label}: {veredicto} las 3 condiciones.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
