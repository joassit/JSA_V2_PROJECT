"""
Corre ML1 (Moneyline crudo) + ML1b (Moneyline calibrado via LOSO) contra
el historico REAL compartido y persiste ambos resultados -- pedido
explicito del usuario para someter la proyeccion de ganador de juego
completo al mismo protocolo (LOSO + bootstrap CI 500 resamples + 3
condiciones) que T1/T1b/F1/M1/M2/M3. Ver analysis/moneyline_candidate_audit.py
para la nota de alcance (reusa variables ya existentes, no ingesta nueva).
"""

from __future__ import annotations

import json
import os
import sys
import uuid
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
from analysis.moneyline_candidate_audit import evaluate_ml1, evaluate_ml1b_calibrated
from data_sources.historical_readonly import get_games_with_snapshots_for_season
from db.database import CandidateAuditResult, SessionLocal, init_db


def load_all_seasons() -> list[dict]:
    games: list[dict] = []
    for season in config.HISTORICAL_SEASONS:
        season_games = get_games_with_snapshots_for_season(season)
        print(f"  temporada {season}: {len(season_games)} juegos con snapshot", file=sys.stderr)
        games.extend(season_games)
    return games


def persist_raw(result: dict, run_id: str) -> None:
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


def persist_calibrated(result: dict, run_id: str) -> None:
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
    run_id = f"ml1-moneyline-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}-{uuid.uuid4().hex[:8]}"
    print(f"Cargando juegos historicos (temporadas {config.HISTORICAL_SEASONS})...", file=sys.stderr)
    games = load_all_seasons()
    print(f"Total: {len(games)} juegos con game_pk+snapshot en todas las temporadas.", file=sys.stderr)

    print("\n=== ML1 (crudo, sin calibrar) ===", file=sys.stderr)
    result_raw = evaluate_ml1(games, n_resamples=config.BOOTSTRAP_RESAMPLES)
    print(json.dumps(result_raw, indent=2, default=str))

    print("\n=== ML1b (calibrado via LOSO real por temporada) ===", file=sys.stderr)
    result_calibrated = evaluate_ml1b_calibrated(games, n_resamples=config.BOOTSTRAP_RESAMPLES)
    print(json.dumps(result_calibrated, indent=2, default=str))

    init_db()
    persist_raw(result_raw, run_id)
    persist_calibrated(result_calibrated, run_id)
    print(f"\nAmbos resultados persistidos en candidate_audit_result (run_id={run_id}).", file=sys.stderr)

    for label, result in (("ML1 (crudo)", result_raw), ("ML1b (calibrado)", result_calibrated)):
        if result["meets_all_3_conditions"]:
            print(f"\nVEREDICTO {label}: cumple las 3 condiciones -- mejora real sobre "
                  "el baseline de ventaja de localia fija. No se adopta "
                  "automaticamente, requiere revision explicita del usuario.")
        else:
            print(f"\nVEREDICTO {label}: NO cumple las 3 condiciones.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
