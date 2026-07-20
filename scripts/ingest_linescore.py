"""
Ingesta de linescore (carreras por entrada) de los 13,101 juegos
historicos -- ground truth que no existe en ningun lado del proyecto
hermano (`historical_game` solo persiste el marcador final). Necesario
para First 5 Innings / Inning Dominance (Linea 2).

Cada juego es un hecho historico FIJO (no cambia con el tiempo) -- a
diferencia de splits/ERA de temporada, esto NO tiene problema de
point-in-time: el linescore de un juego jugado en 2022 es el mismo hoy
que sera en 2030. Se guarda una sola vez, sin necesidad de recalcular.

Reporta EXPLICITAMENTE el costo real (tiempo, juegos, errores) -- mismo
criterio que `jsa/historical/statcast_ingestion.py`.
"""

from __future__ import annotations

import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
from data_sources.historical_readonly import get_games_for_season
from data_sources.mlb_api import get_game_linescore, parse_linescore
from db.database import LinescoreGame, SessionLocal, init_db

MAX_WORKERS = 8


def _fetch_and_parse(game: dict) -> tuple[dict, dict | None]:
    raw = get_game_linescore(game["game_pk"])
    if raw is None:
        return game, None
    parsed = parse_linescore(raw)
    return game, parsed


def ingest_season(season: int, force: bool = False) -> dict:
    games = get_games_for_season(season)

    with SessionLocal() as session:
        existing_pks = set() if force else {
            row[0] for row in session.query(LinescoreGame.game_pk).filter(LinescoreGame.season == season).all()
        }
    pending = [g for g in games if g["game_pk"] not in existing_pks]

    t0 = time.monotonic()
    ok_count, error_count = 0, 0
    errors: list[int] = []

    with SessionLocal() as session:
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            futures = [executor.submit(_fetch_and_parse, g) for g in pending]
            for future in as_completed(futures):
                game, parsed = future.result()
                if parsed is None:
                    error_count += 1
                    errors.append(game["game_pk"])
                    continue
                session.merge(LinescoreGame(
                    game_pk=game["game_pk"],
                    game_date=str(game["game_date"]),
                    season=season,
                    home_f5_runs=parsed["home_f5_runs"],
                    away_f5_runs=parsed["away_f5_runs"],
                    home_f5_result=parsed["home_f5_result"],
                    home_total_runs=parsed["home_total_runs"],
                    away_total_runs=parsed["away_total_runs"],
                    innings_raw=parsed["innings_raw"],
                ))
                ok_count += 1
        session.commit()

    elapsed = time.monotonic() - t0
    return {
        "season": season,
        "games_total": len(games),
        "already_had": len(existing_pks),
        "attempted": len(pending),
        "ok": ok_count,
        "errors": error_count,
        "error_game_pks": errors[:20],  # muestra, no la lista completa si son muchos
        "elapsed_s": round(elapsed, 1),
    }


def main() -> int:
    init_db()
    force = "--force" in sys.argv
    summary = []
    for season in config.HISTORICAL_SEASONS:
        print(f"Ingiriendo linescore de temporada {season}...", file=sys.stderr)
        result = ingest_season(season, force=force)
        print(json.dumps(result), file=sys.stderr)
        summary.append(result)

    total_ok = sum(r["ok"] for r in summary)
    total_errors = sum(r["errors"] for r in summary)
    total_elapsed = sum(r["elapsed_s"] for r in summary)
    print(json.dumps({
        "summary": summary,
        "total_ok": total_ok,
        "total_errors": total_errors,
        "total_elapsed_s": round(total_elapsed, 1),
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
