"""
Ingesta point-in-time-safe de splits de bateo vs. mano del lanzador
(Linea 1 -- matchup pitcher-vs-lineup). Confirmado por el spike real
(2026-07-20, docs/data_source_design.md): `stats=byDateRange` combinado
con `sitCodes` SI filtra por fecha -- 1 llamada por equipo por fecha de
corte, no reconstruccion dia-por-dia desde game logs.

Point-in-time real: para cada fecha en la que un equipo jugo, se congela
su OPS/OBP/SLG vs. cada mano (L y R) acumulado ÚNICAMENTE hasta el dia
ANTERIOR a esa fecha (`endDate = game_date - 1`) -- nunca incluye el
propio dia del juego, para evitar cualquier fuga de informacion futura
hacia atras (mismo criterio de `point_in_time_provider.py` en `jsa/`).

Reporta EXPLICITAMENTE el costo real (tiempo, llamadas, errores).
"""

from __future__ import annotations

import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
from data_sources.historical_readonly import get_games_for_season
from data_sources.mlb_api import get_team_hitting_split_by_date_range, parse_team_hitting_split
from db.database import HandednessSplitSnapshot, SessionLocal, init_db

MAX_WORKERS = 8


def _as_date(value) -> date:
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def _season_start(season: int) -> str:
    return f"{season}-01-01"


def _team_cutoff_dates(games: list[dict]) -> dict[int, set[date]]:
    """team_id -> conjunto de fechas en las que jugo (home o away)."""
    by_team: dict[int, set[date]] = {}
    for g in games:
        game_date = _as_date(g["game_date"])
        for team_id in (g["home_team_id"], g["away_team_id"]):
            by_team.setdefault(team_id, set()).add(game_date)
    return by_team


def _fetch_one(team_id: int, season: int, cutoff: date, vs_hand: str) -> tuple[int, date, str, dict | None]:
    end_date = (cutoff - timedelta(days=1)).isoformat()
    raw = get_team_hitting_split_by_date_range(team_id, _season_start(season), end_date, vs_hand, season)
    parsed = parse_team_hitting_split(raw) if raw is not None else None
    return team_id, cutoff, vs_hand, parsed


def _upsert(session, team_id: int, cutoff: date, season: int, vs_hand: str, parsed: dict) -> None:
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
            ops=parsed.get("ops"), obp=parsed.get("obp"), slg=parsed.get("slg"),
            plate_appearances=parsed.get("plate_appearances"),
        ))
    else:
        existing.ops, existing.obp, existing.slg = parsed.get("ops"), parsed.get("obp"), parsed.get("slg")
        existing.plate_appearances = parsed.get("plate_appearances")


def ingest_season(season: int, force: bool = False) -> dict:
    games = get_games_for_season(season)
    by_team = _team_cutoff_dates(games)

    with SessionLocal() as session:
        existing_keys = set() if force else {
            (row.team_id, row.as_of_date, row.vs_hand)
            for row in session.query(HandednessSplitSnapshot).filter_by(season=season).all()
        }

    jobs: list[tuple[int, date, str]] = []
    for team_id, dates in by_team.items():
        for d in dates:
            for hand in ("L", "R"):
                if (team_id, d.isoformat(), hand) not in existing_keys:
                    jobs.append((team_id, d, hand))

    t0 = time.monotonic()
    ok_count, error_count = 0, 0

    with SessionLocal() as session:
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            futures = [executor.submit(_fetch_one, team_id, season, cutoff, hand) for team_id, cutoff, hand in jobs]
            for future in as_completed(futures):
                team_id, cutoff, vs_hand, parsed = future.result()
                if parsed is None:
                    error_count += 1
                    continue
                _upsert(session, team_id, cutoff, season, vs_hand, parsed)
                ok_count += 1
        session.commit()

    elapsed = time.monotonic() - t0
    return {
        "season": season,
        "teams": len(by_team),
        "already_had": len(existing_keys),
        "attempted": len(jobs),
        "ok": ok_count,
        "errors": error_count,
        "elapsed_s": round(elapsed, 1),
    }


def main() -> int:
    init_db()
    force = "--force" in sys.argv
    summary = []
    for season in config.HISTORICAL_SEASONS:
        print(f"Ingiriendo splits vs mano de temporada {season}...", file=sys.stderr)
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
