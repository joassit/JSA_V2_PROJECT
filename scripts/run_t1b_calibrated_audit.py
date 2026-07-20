"""
Corre T1b (version calibrada de T1, contraccion hacia 0.5 elegida via
LOSO real por temporada -- ver analysis/totals_candidate_audit.py) contra
el historico REAL compartido y persiste el resultado. Cero ingesta nueva.
"""

from __future__ import annotations

import json
import os
import sys
import uuid
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
from analysis.totals_candidate_audit import evaluate_t1b_calibrated
from data_sources.historical_readonly import get_games_with_snapshots_for_season
from db.database import CandidateAuditResult, SessionLocal, init_db


def load_all_seasons() -> list[dict]:
    """Duplicado deliberado de run_t1_totals_audit.py::load_all_seasons()
    -- cada script en scripts/ es un entrypoint standalone, sin depender
    de que scripts/ sea un paquete importable."""
    games: list[dict] = []
    for season in config.HISTORICAL_SEASONS:
        season_games = get_games_with_snapshots_for_season(season)
        print(f"  temporada {season}: {len(season_games)} juegos con snapshot", file=sys.stderr)
        games.extend(season_games)
    return games


def persist_result(result: dict, run_id: str) -> None:
    init_db()
    with SessionLocal() as session:
        session.add(CandidateAuditResult(
            run_id=run_id,
            hypothesis_name=result["hypothesis"],
            target=result["target"],
            n_games=result["n_games_covered"],
            coverage_pct=100.0,
            auc=result["loso_auc_calibrated"],
            delta_brier_mean=result["delta_brier_mean"],
            ci_low=result["ci_low"],
            ci_high=result["ci_high"],
            significant=result["significant"],
            effect_size_ok=result["effect_size_ok"],
            meets_all_3_conditions=result["meets_all_3_conditions"],
        ))
        session.commit()


def main() -> int:
    run_id = f"t1b-calibrated-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}-{uuid.uuid4().hex[:8]}"
    print(f"Cargando juegos historicos (temporadas {config.HISTORICAL_SEASONS})...", file=sys.stderr)
    games = load_all_seasons()
    print(f"Total: {len(games)} juegos con game_pk+snapshot en todas las temporadas.", file=sys.stderr)

    print("Evaluando T1b (LOSO real por temporada + bootstrap CI 500 resamples)...", file=sys.stderr)
    result = evaluate_t1b_calibrated(games, n_resamples=config.BOOTSTRAP_RESAMPLES)

    print(json.dumps(result, indent=2, default=str))

    persist_result(result, run_id)
    print(f"\nResultado persistido en candidate_audit_result (run_id={run_id}).", file=sys.stderr)

    if result["meets_all_3_conditions"]:
        print("\nVEREDICTO: T1b cumple las 3 condiciones -- mejora real sobre el "
              "baseline de liga, no se adopta automaticamente, requiere "
              "revision explicita del usuario antes de cualquier siguiente paso.")
    else:
        print("\nVEREDICTO: T1b NO cumple las 3 condiciones.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
