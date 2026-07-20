"""
Corre el candidate audit F1 (especializacion de First 5 Innings) contra
el historico real: cruza `historical_snapshot` (solo lectura, schema
public) con `linescore_game` (propio, schema team_strength, ingerido por
scripts/ingest_linescore.py) por game_pk, en Python -- ambas tablas viven
en el mismo Postgres pero se leen por rutas separadas (ver
data_sources/historical_readonly.py vs db/database.py), asi que el join
se hace del lado del cliente, no con SQL cruzado entre schemas.
"""

from __future__ import annotations

import json
import os
import sys
import uuid
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
from analysis.first5_candidate_audit import evaluate_f1
from data_sources.historical_readonly import get_games_with_snapshots_for_season
from db.database import CandidateAuditResult, LinescoreGame, SessionLocal, init_db


def load_games_with_f5_ground_truth() -> list[dict]:
    games: list[dict] = []
    for season in config.HISTORICAL_SEASONS:
        snapshot_games = get_games_with_snapshots_for_season(season)
        with SessionLocal() as session:
            f5_by_pk = {
                row.game_pk: row.home_f5_result
                for row in session.query(LinescoreGame).filter_by(season=season).all()
            }
        merged = 0
        for g in snapshot_games:
            f5_result = f5_by_pk.get(g["game_pk"])
            if f5_result is None:
                continue
            games.append({"season": season, "payload": g["payload"], "home_f5_result": f5_result})
            merged += 1
        print(f"  temporada {season}: {len(snapshot_games)} juegos con snapshot, "
              f"{merged} con linescore tambien", file=sys.stderr)
    return games


def persist_result(result: dict, run_id: str) -> None:
    init_db()
    with SessionLocal() as session:
        session.add(CandidateAuditResult(
            run_id=run_id,
            hypothesis_name=result["hypothesis"],
            target=result["target"],
            n_games=result["n_games_covered"],
            coverage_pct=result["coverage_pct"],
            auc=result["auc_model"],
            delta_brier_mean=result["delta_brier_mean"],
            ci_low=result["ci_low"],
            ci_high=result["ci_high"],
            significant=result["significant"],
            effect_size_ok=result["effect_size_ok"],
            meets_all_3_conditions=result["meets_all_3_conditions"],
        ))
        session.commit()


def main() -> int:
    run_id = f"f1-first5-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}-{uuid.uuid4().hex[:8]}"
    print("Cargando juegos con snapshot + linescore...", file=sys.stderr)
    games = load_games_with_f5_ground_truth()
    print(f"Total: {len(games)} juegos con ambos.", file=sys.stderr)

    print("Evaluando F1 (bootstrap CI 500 resamples)...", file=sys.stderr)
    result = evaluate_f1(games, n_resamples=config.BOOTSTRAP_RESAMPLES)

    print(json.dumps(result, indent=2, default=str))

    persist_result(result, run_id)
    print(f"\nResultado persistido en candidate_audit_result (run_id={run_id}).", file=sys.stderr)

    if result["meets_all_3_conditions"]:
        print("\nVEREDICTO: F1 cumple las 3 condiciones -- mejora real sobre el "
              "proxy de juego completo, no se adopta automaticamente, requiere "
              "revision explicita del usuario.")
    else:
        print("\nVEREDICTO: F1 NO cumple las 3 condiciones.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
