"""
Corre Weather1 (¿la temperatura real mejora T1b?) contra el historico
REAL compartido -- cruza `historical_snapshot` (solo lectura) con
`weather_snapshot` (propio, ingerido por scripts/ingest_weather.py) por
game_pk, del lado del cliente (mismo patron que run_f1_first5_audit.py
con linescore_game).
"""

from __future__ import annotations

import json
import os
import sys
import uuid
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
from analysis.weather_candidate_audit import evaluate_weather1
from data_sources.historical_readonly import get_games_with_snapshots_for_season
from db.database import CandidateAuditResult, SessionLocal, WeatherSnapshot, init_db


def load_games_with_weather() -> list[dict]:
    games: list[dict] = []
    for season in config.HISTORICAL_SEASONS:
        snapshot_games = get_games_with_snapshots_for_season(season)
        with SessionLocal() as session:
            temp_by_pk = {
                row.game_pk: row.temp_f
                for row in session.query(WeatherSnapshot).filter_by(season=season).all()
            }
        merged = 0
        for g in snapshot_games:
            temp_f = temp_by_pk.get(g["game_pk"])
            if temp_f is None:
                continue
            games.append({
                "season": season, "payload": g["payload"], "temp_f": temp_f,
                "home_score": g["home_score"], "away_score": g["away_score"],
            })
            merged += 1
        print(f"  temporada {season}: {len(snapshot_games)} juegos con snapshot, "
              f"{merged} con clima tambien", file=sys.stderr)
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
            auc=result["loso_auc_adjusted"],
            delta_brier_mean=result["delta_brier_mean"],
            ci_low=result["ci_low"],
            ci_high=result["ci_high"],
            significant=result["significant"],
            effect_size_ok=result["effect_size_ok"],
            meets_all_3_conditions=result["meets_all_3_conditions"],
        ))
        session.commit()


def main() -> int:
    run_id = f"weather1-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}-{uuid.uuid4().hex[:8]}"
    print("Cargando juegos con snapshot + clima...", file=sys.stderr)
    games = load_games_with_weather()
    print(f"Total: {len(games)} juegos con ambos.", file=sys.stderr)

    print("Evaluando Weather1 (LOSO real por temporada + bootstrap CI 500 resamples)...", file=sys.stderr)
    result = evaluate_weather1(games, n_resamples=config.BOOTSTRAP_RESAMPLES)

    print(json.dumps(result, indent=2, default=str))

    persist_result(result, run_id)
    print(f"\nResultado persistido en candidate_audit_result (run_id={run_id}).", file=sys.stderr)

    if result["meets_all_3_conditions"]:
        print("\nVEREDICTO: Weather1 cumple las 3 condiciones -- la temperatura "
              "SI mejora sobre T1b (que ya es la mejor formula de Totales "
              "adoptada). No se adopta automaticamente, requiere revision "
              "explicita del usuario.")
    else:
        print("\nVEREDICTO: Weather1 NO cumple las 3 condiciones -- no hay "
              "evidencia de que la temperatura aporte algo mas alla de lo "
              "que T1b ya predice.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
