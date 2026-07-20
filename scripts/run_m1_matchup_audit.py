"""
Corre el candidate audit M1 (matchup pitcher-vs-lineup por mano) contra
el historico real. Cruza en Python (mismo patron que run_f1_first5_audit.py):
- historical_game/historical_snapshot (solo lectura, incluye
  home_pitcher_id/away_pitcher_id).
- handedness_split_snapshot (propio, ingerido por
  scripts/ingest_handedness_splits.py).
- Mano de cada abridor (`/people/{id}`, MLB Stats API) -- atributo casi
  siempre inmutable en la carrera de un pitcher, se obtiene en vivo aqui
  (cacheado dentro de la corrida, ~1 llamada por pitcher UNICO, no por
  juego) en vez de persistirse en una tabla nueva -- costo trivial
  (cientos de pitchers, no miles de juegos).
"""

from __future__ import annotations

import json
import os
import sys
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
from analysis.matchup_candidate_audit import evaluate_m1
from data_sources.historical_readonly import get_games_with_snapshots_for_season
from data_sources.mlb_api import get_pitcher_throws
from db.database import CandidateAuditResult, HandednessSplitSnapshot, SessionLocal, init_db

MAX_WORKERS = 8


def _fetch_pitcher_hands(pitcher_ids: set[int]) -> dict[int, str]:
    hands: dict[int, str] = {}
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {executor.submit(get_pitcher_throws, pid): pid for pid in pitcher_ids if pid is not None}
        for future in as_completed(futures):
            pid = futures[future]
            hand = future.result()
            if hand in ("L", "R"):
                hands[pid] = hand
    return hands


def load_games_with_matchup_inputs() -> list[dict]:
    games: list[dict] = []
    for season in config.HISTORICAL_SEASONS:
        raw_games = get_games_with_snapshots_for_season(season)  # 1 query, evita N+1
        pitcher_ids = {g["home_pitcher_id"] for g in raw_games} | {g["away_pitcher_id"] for g in raw_games}
        pitcher_hands = _fetch_pitcher_hands(pitcher_ids)

        with SessionLocal() as session:
            splits = {
                (row.team_id, row.as_of_date, row.vs_hand): row.ops
                for row in session.query(HandednessSplitSnapshot).filter_by(season=season).all()
            }

        merged = 0
        for g in raw_games:
            if g["winner"] not in ("home", "away"):
                continue
            game_date = str(g["game_date"])
            home_hand = pitcher_hands.get(g["home_pitcher_id"])
            away_hand = pitcher_hands.get(g["away_pitcher_id"])
            home_ops_vs_away_hand = splits.get((g["home_team_id"], game_date, away_hand)) if away_hand else None
            away_ops_vs_home_hand = splits.get((g["away_team_id"], game_date, home_hand)) if home_hand else None

            games.append({
                "season": season, "payload": g["payload"], "home_won": 1 if g["winner"] == "home" else 0,
                "home_ops_vs_away_hand": home_ops_vs_away_hand, "away_ops_vs_home_hand": away_ops_vs_home_hand,
            })
            merged += 1
        print(f"  temporada {season}: {len(raw_games)} juegos, {len(pitcher_hands)}/{len(pitcher_ids)} "
              f"manos de pitcher resueltas, {merged} juegos usables", file=sys.stderr)
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
    run_id = f"m1-matchup-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}-{uuid.uuid4().hex[:8]}"
    print("Cargando juegos + manos de pitcher + splits...", file=sys.stderr)
    games = load_games_with_matchup_inputs()
    print(f"Total: {len(games)} juegos.", file=sys.stderr)

    with_split = sum(1 for g in games if g["home_ops_vs_away_hand"] is not None or g["away_ops_vs_home_hand"] is not None)
    print(f"Juegos con al menos 1 split especifico resuelto: {with_split}/{len(games)}", file=sys.stderr)

    # DIAGNOSTICO: comparar el split especifico contra el OPS general para
    # una muestra -- si son identicos en la muestra, la sustitucion no esta
    # aportando nada (bug de datos), no "sin señal real".
    sample = [g for g in games if g["home_ops_vs_away_hand"] is not None][:10]
    for g in sample:
        general = g["payload"].get("home_ops")
        specific = g["home_ops_vs_away_hand"]
        print(f"  DEBUG home_ops general={general} vs especifico={specific} "
              f"(iguales={general == specific})", file=sys.stderr)

    print("Evaluando M1 (bootstrap CI 500 resamples)...", file=sys.stderr)
    result = evaluate_m1(games, n_resamples=config.BOOTSTRAP_RESAMPLES)

    print(json.dumps(result, indent=2, default=str))

    persist_result(result, run_id)
    print(f"\nResultado persistido en candidate_audit_result (run_id={run_id}).", file=sys.stderr)

    if result["meets_all_3_conditions"]:
        print("\nVEREDICTO: M1 cumple las 3 condiciones -- mejora real sobre el "
              "OPS general, no se adopta automaticamente, requiere revision "
              "explicita del usuario.")
    else:
        print("\nVEREDICTO: M1 NO cumple las 3 condiciones.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
