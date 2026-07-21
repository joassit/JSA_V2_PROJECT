"""
Corre el candidate audit M3 (ERA del cerrador como ajuste al bullpen ERA
general) contra el historico real. Cruza en Python (mismo patron que
run_m2_chase_rate_audit.py):
- historical_game/historical_snapshot (solo lectura).
- closer_era_snapshot (propio, ingerido por scripts/ingest_closer_era.py).
"""

from __future__ import annotations

import json
import os
import sys
import uuid
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
from analysis.closer_era_candidate_audit import evaluate_m3
from data_sources.historical_readonly import get_games_with_snapshots_for_season
from db.database import CandidateAuditResult, CloserEraSnapshot, SessionLocal, init_db


def load_games_with_closer_era() -> list[dict]:
    games: list[dict] = []
    for season in config.HISTORICAL_SEASONS:
        raw_games = get_games_with_snapshots_for_season(season)

        with SessionLocal() as session:
            snapshots = {
                (row.team_id, row.as_of_date): row.closer_era
                for row in session.query(CloserEraSnapshot).filter_by(season=season).all()
            }

        merged = 0
        for g in raw_games:
            if g["winner"] not in ("home", "away"):
                continue
            game_date = str(g["game_date"])
            home_closer_era = snapshots.get((g["home_team_id"], game_date))
            away_closer_era = snapshots.get((g["away_team_id"], game_date))

            games.append({
                "season": season, "payload": g["payload"], "home_won": 1 if g["winner"] == "home" else 0,
                "home_closer_era": home_closer_era, "away_closer_era": away_closer_era,
            })
            merged += 1
        with_closer = sum(1 for g in games[-merged:] if g["home_closer_era"] is not None or g["away_closer_era"] is not None)
        print(f"  temporada {season}: {len(raw_games)} juegos, {merged} usables, "
              f"{with_closer} con al menos 1 ERA de cerrador resuelto", file=sys.stderr)
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
    run_id = f"m3-closer-era-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}-{uuid.uuid4().hex[:8]}"
    print("Cargando juegos + ERA del cerrador...", file=sys.stderr)
    games = load_games_with_closer_era()
    print(f"Total: {len(games)} juegos.", file=sys.stderr)

    with_closer = sum(1 for g in games if g["home_closer_era"] is not None or g["away_closer_era"] is not None)
    print(f"Juegos con al menos 1 ERA de cerrador resuelto: {with_closer}/{len(games)}", file=sys.stderr)

    print("Evaluando M3 (LOSO + bootstrap CI 500 resamples)...", file=sys.stderr)
    result = evaluate_m3(games, n_resamples=config.BOOTSTRAP_RESAMPLES)

    print(json.dumps(result, indent=2, default=str))

    persist_result(result, run_id)
    print(f"\nResultado persistido en candidate_audit_result (run_id={run_id}).", file=sys.stderr)

    if result["meets_all_3_conditions"]:
        print("\nVEREDICTO: M3 cumple las 3 condiciones -- mejora real sobre el "
              "bullpen ERA general, no se adopta automaticamente, requiere "
              "revision explicita del usuario.")
    else:
        print("\nVEREDICTO: M3 NO cumple las 3 condiciones.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
