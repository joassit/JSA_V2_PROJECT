"""
Ingesta point-in-time-safe de splits de bateo vs. mano del lanzador
(Linea 1 -- matchup pitcher-vs-lineup).

CAMINO 2 (dia-por-dia), no Camino 1: confirmado en vivo (2026-07-20,
scripts/diagnose_sitcodes_bydaterange.py, corridas 29716014513 y
29716111744) que `sitCodes` NO tiene efecto combinado con
`stats=byDateRange` -- la primera version de este script (Camino 1,
1 llamada por equipo por fecha de corte CON sitCodes) producia splits
"especificos" identicos al OPS general sin separar, lo que causo que
el primer candidate audit de M1 diera delta_brier=0.0 exacto (run
29715848018) -- imposible por azar, no "sin señal real".

Este script reconstruye el split el mismo dia-por-dia que ya usa
`jsa/historical/point_in_time_provider.py` para el OPS general: 1
llamada por equipo por fecha JUGADA (linea de bateo cruda de ESE dia,
sin sitCodes -- se ignoran igual), clasificada por la mano del abridor
RIVAL de ese juego (identica fuente que usa
scripts/run_m1_matchup_audit.py: `/people/{id}`, cacheado por pitcher
unico), y acumulada en Python en dos conjuntos de conteos crudos
corriendo (vs L, vs R) por equipo. El split point-in-time-safe de cada
fecha es el acumulado de TODOS los juegos ANTERIORES a esa fecha
(nunca incluye el propio juego del dia) -- mismo criterio de
`point_in_time_provider.py`. Costo real: 1 llamada por equipo-fecha en
vez de 2 (una por mano) de la version anterior -- mas barato, no mas
caro, que Camino 1.

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
from analysis.stats_utils import ops_from_raw_counts
from data_sources.historical_readonly import get_games_for_season
from data_sources.mlb_api import get_pitcher_throws, get_team_hitting_by_date, parse_team_hitting_raw
from db.database import HandednessSplitSnapshot, SessionLocal, init_db

MAX_WORKERS = 8
_ZERO_COUNTS = {"ab": 0, "h": 0, "bb": 0, "hbp": 0, "sf": 0, "tb": 0, "pa": 0}


def _as_date(value) -> date:
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


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


def _team_schedule(games: list[dict]) -> dict[int, dict[date, int | None]]:
    """team_id -> {fecha: pitcher_id_rival} -- si hay doble cartelera
    (2 juegos, mismo dia), se queda con el ultimo procesado (mismo
    tratamiento que la version anterior, que ya trataba las fechas de
    un equipo como un conjunto sin distinguir dobles carteleras)."""
    schedule: dict[int, dict[date, int | None]] = {}
    for g in games:
        d = _as_date(g["game_date"])
        schedule.setdefault(g["home_team_id"], {})[d] = g["away_pitcher_id"]
        schedule.setdefault(g["away_team_id"], {})[d] = g["home_pitcher_id"]
    return schedule


def _fetch_daily_line(team_id: int, game_date: date, season: int) -> tuple[int, date, dict | None]:
    raw = get_team_hitting_by_date(team_id, game_date.isoformat(), season)
    parsed = parse_team_hitting_raw(raw) if raw is not None else None
    return team_id, game_date, parsed


def _accumulate(running: dict, line: dict) -> None:
    for key in _ZERO_COUNTS:
        running[key] += line[key]


def _upsert(session, team_id: int, cutoff: date, season: int, vs_hand: str, ops: float | None, pa: int) -> None:
    """Upsert real por (team_id, as_of_date, vs_hand) -- session.merge() no
    sirve aqui porque identifica filas por PRIMARY KEY (id autoincrement),
    no por el UniqueConstraint que de verdad define un duplicado."""
    existing = (
        session.query(HandednessSplitSnapshot)
        .filter_by(team_id=team_id, as_of_date=cutoff.isoformat(), vs_hand=vs_hand)
        .one_or_none()
    )
    if existing is None:
        session.add(HandednessSplitSnapshot(
            team_id=team_id, as_of_date=cutoff.isoformat(), season=season, vs_hand=vs_hand,
            ops=ops, obp=None, slg=None, plate_appearances=pa,
        ))
    else:
        existing.ops, existing.plate_appearances = ops, pa


def ingest_season(season: int, force: bool = False) -> dict:
    games = get_games_for_season(season)
    schedule = _team_schedule(games)

    with SessionLocal() as session:
        existing_teams_done = set() if force else {
            row.team_id for row in session.query(HandednessSplitSnapshot).filter_by(season=season).all()
        }

    pitcher_ids = {pid for dates in schedule.values() for pid in dates.values() if pid is not None}
    print(f"  temporada {season}: resolviendo mano de {len(pitcher_ids)} pitchers unicos...", file=sys.stderr)
    pitcher_hands = _fetch_pitcher_hands(pitcher_ids)

    teams_to_process = {t: d for t, d in schedule.items() if force or t not in existing_teams_done}

    t0 = time.monotonic()
    daily_lines: dict[tuple[int, date], dict | None] = {}
    fetch_jobs = [(team_id, d) for team_id, dates in teams_to_process.items() for d in dates]

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = [executor.submit(_fetch_daily_line, team_id, d, season) for team_id, d in fetch_jobs]
        fetch_errors = 0
        for future in as_completed(futures):
            team_id, d, parsed = future.result()
            daily_lines[(team_id, d)] = parsed
            if parsed is None:
                fetch_errors += 1

    ok_count = 0
    with SessionLocal() as session:
        for team_id, dates in teams_to_process.items():
            running = {"L": dict(_ZERO_COUNTS), "R": dict(_ZERO_COUNTS)}
            for d in sorted(dates):
                for hand in ("L", "R"):
                    counts = running[hand]
                    ops = ops_from_raw_counts(counts["ab"], counts["h"], counts["bb"], counts["hbp"], counts["sf"], counts["tb"])
                    _upsert(session, team_id, d, season, hand, ops, counts["pa"])
                    ok_count += 1

                line = daily_lines.get((team_id, d))
                opponent_hand = pitcher_hands.get(dates[d])
                if line is not None and opponent_hand in ("L", "R"):
                    _accumulate(running[opponent_hand], line)
        session.commit()

    elapsed = time.monotonic() - t0
    return {
        "season": season,
        "teams_total": len(schedule),
        "teams_processed": len(teams_to_process),
        "teams_skipped_already_done": len(schedule) - len(teams_to_process),
        "pitchers_resolved": f"{len(pitcher_hands)}/{len(pitcher_ids)}",
        "daily_fetches": len(fetch_jobs),
        "daily_fetch_errors": fetch_errors,
        "snapshots_written": ok_count,
        "elapsed_s": round(elapsed, 1),
    }


def main() -> int:
    init_db()
    force = "--force" in sys.argv
    summary = []
    for season in config.HISTORICAL_SEASONS:
        print(f"Ingiriendo splits vs mano de temporada {season} (Camino 2)...", file=sys.stderr)
        result = ingest_season(season, force=force)
        print(json.dumps(result), file=sys.stderr)
        summary.append(result)

    total_written = sum(r["snapshots_written"] for r in summary)
    total_errors = sum(r["daily_fetch_errors"] for r in summary)
    total_elapsed = sum(r["elapsed_s"] for r in summary)
    print(json.dumps({
        "summary": summary,
        "total_snapshots_written": total_written,
        "total_daily_fetch_errors": total_errors,
        "total_elapsed_s": round(total_elapsed, 1),
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
