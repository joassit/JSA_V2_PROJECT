"""
Corre la calibracion logistica (Platt scaling, 2 parametros) para las 3
formulas ya adoptadas -- T1 (Totales), F1 (First 5) y ML1 (Moneyline) --
contra el historico REAL compartido, y compara cada una contra:
1. El baseline correspondiente (mismo que uso la version original).
2. La version ya adoptada (T1b/ML1b: shrinkage lineal; F1: sin calibrar,
   primera vez que se prueba calibrarla).

Pedido explicito del usuario ("Si, hazlo", en respuesta a la propuesta de
mejorar la calibracion mas alla del shrinkage lineal de 1 parametro).
Cero ingesta nueva -- misma fuente de datos que T1/T1b/F1/ML1/ML1b.
"""

from __future__ import annotations

import json
import os
import sys
import uuid
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
from analysis.first5_candidate_audit import evaluate_f1_platt_calibrated
from analysis.moneyline_candidate_audit import evaluate_ml1_platt_calibrated
from analysis.totals_candidate_audit import evaluate_t1_platt_calibrated
from data_sources.historical_readonly import get_games_with_snapshots_for_season
from db.database import CandidateAuditResult, LinescoreGame, SessionLocal, init_db


def load_totals_moneyline_games() -> list[dict]:
    """Mismo loader que run_t1_totals_audit.py/run_moneyline_candidate_audit.py."""
    games: list[dict] = []
    for season in config.HISTORICAL_SEASONS:
        season_games = get_games_with_snapshots_for_season(season)
        print(f"  temporada {season}: {len(season_games)} juegos con snapshot", file=sys.stderr)
        games.extend(season_games)
    return games


def load_f1_games() -> list[dict]:
    """Mismo loader (join con linescore_game) que run_f1_first5_audit.py."""
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
        print(f"  temporada {season}: {merged} juegos con linescore", file=sys.stderr)
    return games


def persist(result: dict, run_id: str, auc_key: str) -> None:
    with SessionLocal() as session:
        session.add(CandidateAuditResult(
            run_id=run_id,
            hypothesis_name=result["hypothesis"],
            target=result["target"],
            n_games=result["n_games_covered"],
            coverage_pct=100.0,
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
    run_id = f"platt-calibration-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}-{uuid.uuid4().hex[:8]}"
    init_db()

    print("=== Cargando juegos (Totales/Moneyline) ===", file=sys.stderr)
    tm_games = load_totals_moneyline_games()
    print(f"Total: {len(tm_games)} juegos con snapshot.", file=sys.stderr)

    print("\n=== T1-Platt ===", file=sys.stderr)
    t1_platt = evaluate_t1_platt_calibrated(tm_games, n_resamples=config.BOOTSTRAP_RESAMPLES)
    print(json.dumps(t1_platt, indent=2, default=str))
    persist(t1_platt, run_id, "loso_auc_platt")

    print("\n=== ML1-Platt ===", file=sys.stderr)
    ml1_platt = evaluate_ml1_platt_calibrated(tm_games, n_resamples=config.BOOTSTRAP_RESAMPLES)
    print(json.dumps(ml1_platt, indent=2, default=str))
    persist(ml1_platt, run_id, "loso_auc_platt")

    print("\n=== Cargando juegos (First 5, con linescore) ===", file=sys.stderr)
    f1_games = load_f1_games()
    print(f"Total: {len(f1_games)} juegos con linescore.", file=sys.stderr)

    print("\n=== F1-Platt ===", file=sys.stderr)
    f1_platt = evaluate_f1_platt_calibrated(f1_games, n_resamples=config.BOOTSTRAP_RESAMPLES)
    print(json.dumps(f1_platt, indent=2, default=str))
    persist(f1_platt, run_id, "loso_auc_platt")

    print(f"\nLos 3 resultados persistidos en candidate_audit_result (run_id={run_id}).", file=sys.stderr)

    for label, result, vs_key in (
        ("T1-Platt", t1_platt, "delta_brier_vs_t1b_linear"),
        ("F1-Platt", f1_platt, "delta_brier_vs_f1_uncalibrated"),
        ("ML1-Platt", ml1_platt, "delta_brier_vs_ml1b_linear"),
    ):
        veredicto_baseline = "cumple" if result["meets_all_3_conditions"] else "NO cumple"
        print(
            f"\nVEREDICTO {label}: {veredicto_baseline} las 3 condiciones vs. baseline. "
            f"Delta vs. version ya adoptada: {result[vs_key]:+.5f} "
            f"({'mejora' if result[vs_key] < 0 else 'empeora o igual'}).",
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
