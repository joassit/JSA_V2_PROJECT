"""
Ingesta point-in-time-safe del ERA del cerrador (Linea 3, nueva --
ver docs/data_source_design.md, "Resultado real de M3"). Confirmado en
vivo (scripts/feasibility_spike_closer_era.py): el roster de temporada
completa + `stats=gameLog` por pitcher permiten reconstruir, dia por
dia, quien fue el cerrador (mas saves acumulados) y su propio ERA --
dato que `jsa/historical/point_in_time_provider.py::bullpen_era_as_of()`
YA calcula internamente pero descarta despues de derivar solo
`closer_available` (bool).

Costo: 1 llamada de roster + 1 llamada de gameLog por pitcher del
roster, POR EQUIPO-TEMPORADA (no por equipo-fecha) -- mucho mas barato
que reconstruir roster+stats activos dia por dia (lo que haria
bullpen_era_as_of() si se repitiera aqui, ~366,000 llamadas).

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
from analysis.closer_reconstruction import (
    parse_game_log_events, parse_roster_pitchers, reconstruct_closer_snapshots,
)
from data_sources.historical_readonly import get_games_for_season
from data_sources.mlb_api import get_pitcher_game_log, get_team_roster_full_season
from db.database import CloserEraSnapshot, SessionLocal, init_db

MAX_WORKERS = 8


def _as_date(value) -> date:
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def _team_schedule(games: list[dict]) -> dict[int, set[date]]:
    schedule: dict[int, set[date]] = {}
    for g in games:
        d = _as_date(g["game_date"])
        schedule.setdefault(g["home_team_id"], set()).add(d)
        schedule.setdefault(g["away_team_id"], set()).add(d)
    return schedule


def _fetch_pitcher_log(pitcher_id: int, season: int) -> tuple[int, list[dict] | None]:
    raw = get_pitcher_game_log(pitcher_id, season)
    if raw is None:
        return pitcher_id, None
    return pitcher_id, parse_game_log_events(raw)


def _upsert(session, team_id: int, cutoff: date, season: int, snap: dict) -> None:
    """Upsert real por (team_id, as_of_date) -- session.merge() no sirve
    aqui porque identifica filas por PRIMARY KEY (id autoincrement), no
    por el UniqueConstraint que de verdad define un duplicado."""
    existing = (
        session.query(CloserEraSnapshot)
        .filter_by(team_id=team_id, as_of_date=cutoff.isoformat())
        .one_or_none()
    )
    if existing is None:
        session.add(CloserEraSnapshot(
            team_id=team_id, as_of_date=cutoff.isoformat(), season=season,
            closer_pitcher_id=snap["closer_pitcher_id"], closer_era=snap["closer_era"],
            closer_ip=snap["closer_ip"], closer_saves=snap["closer_saves"],
        ))
    else:
        existing.closer_pitcher_id = snap["closer_pitcher_id"]
        existing.closer_era = snap["closer_era"]
        existing.closer_ip = snap["closer_ip"]
        existing.closer_saves = snap["closer_saves"]


def ingest_season(season: int, force: bool = False) -> dict:
    games = get_games_for_season(season)
    schedule = _team_schedule(games)

    with SessionLocal() as session:
        existing_teams_done = set() if force else {
            row.team_id for row in session.query(CloserEraSnapshot).filter_by(season=season).all()
        }
    teams_to_process = {t: d for t, d in schedule.items() if force or t not in existing_teams_done}

    t0 = time.monotonic()
    roster_errors = 0
    pitcher_fetch_errors = 0
    ok_count = 0

    with SessionLocal() as session:
        for team_id, team_dates in teams_to_process.items():
            roster_raw = get_team_roster_full_season(team_id, season)
            if roster_raw is None:
                roster_errors += 1
                continue
            pitcher_ids = parse_roster_pitchers(roster_raw)

            pitcher_logs: dict[int, list[dict]] = {}
            with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
                futures = [executor.submit(_fetch_pitcher_log, pid, season) for pid in pitcher_ids]
                for future in as_completed(futures):
                    pid, events = future.result()
                    if events is None:
                        pitcher_fetch_errors += 1
                        continue
                    pitcher_logs[pid] = events

            snapshots = reconstruct_closer_snapshots(sorted(team_dates), pitcher_logs)
            for cutoff, snap in snapshots.items():
                _upsert(session, team_id, cutoff, season, snap)
                ok_count += 1
        session.commit()

    elapsed = time.monotonic() - t0
    return {
        "season": season,
        "teams_total": len(schedule),
        "teams_processed": len(teams_to_process),
        "teams_skipped_already_done": len(schedule) - len(teams_to_process),
        "roster_fetch_errors": roster_errors,
        "pitcher_fetch_errors": pitcher_fetch_errors,
        "snapshots_written": ok_count,
        "elapsed_s": round(elapsed, 1),
    }


def main() -> int:
    init_db()
    force = "--force" in sys.argv
    summary = []
    for season in config.HISTORICAL_SEASONS:
        print(f"Ingiriendo ERA del cerrador de temporada {season}...", file=sys.stderr)
        result = ingest_season(season, force=force)
        print(json.dumps(result), file=sys.stderr)
        summary.append(result)

    total_written = sum(r["snapshots_written"] for r in summary)
    total_roster_errors = sum(r["roster_fetch_errors"] for r in summary)
    total_pitcher_errors = sum(r["pitcher_fetch_errors"] for r in summary)
    total_elapsed = sum(r["elapsed_s"] for r in summary)
    print(json.dumps({
        "summary": summary,
        "total_snapshots_written": total_written,
        "total_roster_fetch_errors": total_roster_errors,
        "total_pitcher_fetch_errors": total_pitcher_errors,
        "total_elapsed_s": round(total_elapsed, 1),
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
