"""
Ingesta historica de clima real (temp_f/condition/wind) para los 13,101
juegos ya validados -- confirmado en vivo (scripts/feasibility_spike_weather.py):
`/game/{gamePk}/feed/live` (v1.1) trae `gameData.weather` SOLO despues de
que el juego ocurre o esta en curso (nunca para juegos programados
futuros). Point-in-time-safe por construccion: el clima real de un
juego ya jugado no cambia con el tiempo, no hace falta reconstruir nada
dia por dia.

Costo: 1 llamada por juego (13,101 llamadas totales) -- reporta tiempo
real y errores explicitamente, mismo criterio que toda ingesta previa de
este proyecto.
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
from data_sources.mlb_api import get_game_weather_raw, parse_weather
from db.database import SessionLocal, WeatherSnapshot, init_db

MAX_WORKERS = 12


def _fetch_one(game_pk: int) -> tuple[int, dict | None]:
    raw = get_game_weather_raw(game_pk)
    if raw is None:
        return game_pk, None
    return game_pk, parse_weather(raw)


def ingest_season(season: int, force: bool = False) -> dict:
    games = get_games_for_season(season)
    game_pks = [g["game_pk"] for g in games]

    with SessionLocal() as session:
        already_done = set() if force else {
            row.game_pk for row in session.query(WeatherSnapshot).filter_by(season=season).all()
        }
    pending = [pk for pk in game_pks if force or pk not in already_done]

    t0 = time.monotonic()
    no_weather = 0
    fetch_errors = 0
    ok_count = 0

    with SessionLocal() as session:
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
            futures = {pool.submit(_fetch_one, pk): pk for pk in pending}
            for future in as_completed(futures):
                game_pk = futures[future]
                try:
                    _, weather = future.result()
                except Exception as e:  # noqa: BLE001 -- se reporta el error, no se detiene la ingesta
                    print(f"  ERROR game_pk={game_pk}: {e}", file=sys.stderr)
                    fetch_errors += 1
                    continue

                if weather is None:
                    no_weather += 1
                    continue

                session.merge(WeatherSnapshot(
                    game_pk=game_pk, season=season,
                    temp_f=weather["temp_f"], condition=weather["condition"], wind_raw=weather["wind_raw"],
                ))
                ok_count += 1
        session.commit()

    elapsed = time.monotonic() - t0
    return {
        "season": season,
        "n_games_total": len(game_pks),
        "n_pending": len(pending),
        "n_ok": ok_count,
        "n_no_weather": no_weather,
        "n_fetch_errors": fetch_errors,
        "elapsed_seconds": round(elapsed, 1),
    }


def main() -> int:
    init_db()
    results = []
    for season in config.HISTORICAL_SEASONS:
        print(f"Ingiriendo clima de la temporada {season}...", file=sys.stderr)
        result = ingest_season(season)
        print(json.dumps(result, indent=2), file=sys.stderr)
        results.append(result)

    total_ok = sum(r["n_ok"] for r in results)
    total_no_weather = sum(r["n_no_weather"] for r in results)
    total_errors = sum(r["n_fetch_errors"] for r in results)
    total_elapsed = sum(r["elapsed_seconds"] for r in results)
    print(json.dumps({
        "total_ok": total_ok, "total_no_weather": total_no_weather,
        "total_fetch_errors": total_errors, "total_elapsed_seconds": round(total_elapsed, 1),
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
