"""
Ingesta point-in-time-safe de Chase Rate (Linea 1, componente pendiente
-- ver docs/data_source_design.md). Confirmado en vivo
(scripts/feasibility_spike_chase_rate.py): `/game/{gamePk}/playByPlay`
trae pitch a pitch de AMBOS equipos en una sola llamada -- mas barato
que los splits vs mano (1 llamada por juego, no por equipo-fecha).

Point-in-time real: para cada fecha en la que un equipo jugo, se congela
su chase rate acumulado UNICAMENTE con juegos ANTERIORES a esa fecha
(nunca incluye el propio juego del dia) -- mismo criterio que
ingest_handedness_splits.py (Camino 2) y point_in_time_provider.py en
jsa/.

Reporta EXPLICITAMENTE el costo real (tiempo, llamadas, errores).
"""

from __future__ import annotations

import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
from analysis.pitch_classification import chase_rate_from_counts, extract_game_pitches
from data_sources.historical_readonly import get_games_for_season
from data_sources.mlb_api import get_game_play_by_play
from db.database import ChaseRateSnapshot, SessionLocal, init_db

MAX_WORKERS = 8


def _as_date(value) -> date:
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def _fetch_game_pitches(game_pk: int) -> tuple[int, list[dict] | None]:
    raw = get_game_play_by_play(game_pk)
    if raw is None:
        return game_pk, None
    return game_pk, extract_game_pitches(raw)


def _upsert(session, team_id: int, cutoff: date, season: int, chase_rate: float | None, pitches: int, swings: int) -> None:
    """Upsert real por (team_id, as_of_date) -- session.merge() no sirve
    aqui porque identifica filas por PRIMARY KEY (id autoincrement), no
    por el UniqueConstraint que de verdad define un duplicado."""
    existing = (
        session.query(ChaseRateSnapshot)
        .filter_by(team_id=team_id, as_of_date=cutoff.isoformat())
        .one_or_none()
    )
    if existing is None:
        session.add(ChaseRateSnapshot(
            team_id=team_id, as_of_date=cutoff.isoformat(), season=season,
            chase_rate=chase_rate, pitches_out_zone_seen=pitches, swings_out_zone=swings,
        ))
    else:
        existing.chase_rate = chase_rate
        existing.pitches_out_zone_seen = pitches
        existing.swings_out_zone = swings


def ingest_season(season: int, force: bool = False) -> dict:
    games = get_games_for_season(season)

    # team_id -> {fecha: game_pk} -- cada equipo juega como mucho 1 vez
    # por fecha en el uso normal (dobles carteleras se tratan como la
    # version anterior: la ultima gana).
    schedule: dict[int, dict[date, int]] = {}
    for g in games:
        d = _as_date(g["game_date"])
        schedule.setdefault(g["home_team_id"], {})[d] = g["game_pk"]
        schedule.setdefault(g["away_team_id"], {})[d] = g["game_pk"]

    with SessionLocal() as session:
        existing_teams_done = set() if force else {
            row.team_id for row in session.query(ChaseRateSnapshot).filter_by(season=season).all()
        }
    teams_to_process = {t: d for t, d in schedule.items() if force or t not in existing_teams_done}

    unique_game_pks = {gp for dates in teams_to_process.values() for gp in dates.values()}

    t0 = time.monotonic()
    game_pitches: dict[int, list[dict] | None] = {}
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = [executor.submit(_fetch_game_pitches, gp) for gp in unique_game_pks]
        fetch_errors = 0
        for future in as_completed(futures):
            game_pk, pitches = future.result()
            game_pitches[game_pk] = pitches
            if pitches is None:
                fetch_errors += 1

    ok_count = 0
    with SessionLocal() as session:
        for team_id, dates in teams_to_process.items():
            running_pitches_out = 0
            running_swings_out = 0
            for d in sorted(dates):
                chase_rate = chase_rate_from_counts(running_swings_out, running_pitches_out)
                _upsert(session, team_id, d, season, chase_rate, running_pitches_out, running_swings_out)
                ok_count += 1

                pitches = game_pitches.get(dates[d])
                game_info = next((g for g in games if g["game_pk"] == dates[d]), None)
                if pitches and game_info:
                    is_home = game_info["home_team_id"] == team_id
                    for p in pitches:
                        batting_is_this_team = (not p["is_top_inning"]) if is_home else p["is_top_inning"]
                        if not batting_is_this_team or not p["out_of_zone"]:
                            continue
                        running_pitches_out += 1
                        if p["is_swing"]:
                            running_swings_out += 1
        session.commit()

    elapsed = time.monotonic() - t0
    return {
        "season": season,
        "teams_total": len(schedule),
        "teams_processed": len(teams_to_process),
        "teams_skipped_already_done": len(schedule) - len(teams_to_process),
        "unique_games_fetched": len(unique_game_pks),
        "game_fetch_errors": fetch_errors,
        "snapshots_written": ok_count,
        "elapsed_s": round(elapsed, 1),
    }


def main() -> int:
    init_db()
    force = "--force" in sys.argv
    summary = []
    for season in config.HISTORICAL_SEASONS:
        print(f"Ingiriendo chase rate de temporada {season}...", file=sys.stderr)
        result = ingest_season(season, force=force)
        print(json.dumps(result), file=sys.stderr)
        summary.append(result)

    total_written = sum(r["snapshots_written"] for r in summary)
    total_errors = sum(r["game_fetch_errors"] for r in summary)
    total_elapsed = sum(r["elapsed_s"] for r in summary)
    print(json.dumps({
        "summary": summary,
        "total_snapshots_written": total_written,
        "total_game_fetch_errors": total_errors,
        "total_elapsed_s": round(total_elapsed, 1),
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
