"""
Orquestador de proyecciones EN VIVO (juegos futuros) -- arma el payload de
cada juego del dia (o de una fecha dada) con datos "a hoy" (OPS de
temporada, ERA del abridor probable, ERA de bullpen ponderado por IP del
roster activo, park factor ya calculado por scripts/compute_park_factors.py)
y aplica las 3 formulas ADOPTADAS (T1b, F1, ML1b) -- ver
docs/data_source_design.md, "Proyecciones en vivo". ML1b tiene una
advertencia de alcance propia (no vence al mercado real, ver
analysis/moneyline_candidate_audit.py) -- se incluye igual, adoptada por
pedido explicito del usuario.

Distinto de todo lo point-in-time historico de este proyecto: "hoy" ya ES
el corte, no hace falta reconstruir nada dia por dia -- stats=season de la
API ya trae el acumulado correcto.

Nunca escribe en la base de datos (solo lee ParkFactor); no persiste
proyecciones -- imprime JSON a stdout para que el consumidor (o una futura
tabla) decida que hacer con el resultado.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from analysis.first5_candidate_audit import predict_first5_home_win_prob
from analysis.live_snapshot import aggregate_bullpen_era, compute_league_averages
from analysis.moneyline_candidate_audit import predict_moneyline_home_win_prob
from analysis.runline_candidate_audit import RUN_LINE_MARGIN, predict_runline_home_covers_prob
from analysis.totals_candidate_audit import TOTALS_LINE, predict_totals_over_prob
from data_sources.mlb_api import (
    get_pitcher_era_season, get_schedule_with_probables, get_team_active_roster,
    get_team_ops_season, parse_era_ip_from_season_stats, parse_ops_from_season_stats,
    parse_schedule_games,
)
from db.database import ParkFactor, SessionLocal

MAX_WORKERS = 8

# Codigo de posicion oficial de la API para "pitcher" -- mismo campo que
# usa el resto del ecosistema para filtrar el roster.
PITCHER_POSITION_CODE = "1"


def _pitcher_ids_from_roster(roster_payload: dict | None, exclude_id: int | None) -> list[int]:
    """IDs de pitchers del roster ACTIVO, sin el abridor probable de hoy
    (ya se cuenta por separado como `*_starter_xera`, no como bullpen)."""
    if not roster_payload:
        return []
    ids = []
    for entry in roster_payload.get("roster") or []:
        position = entry.get("position") or {}
        if position.get("code") != PITCHER_POSITION_CODE:
            continue
        person_id = (entry.get("person") or {}).get("id")
        if person_id is None or person_id == exclude_id:
            continue
        ids.append(person_id)
    return ids


def _fetch_team_ops(team_id: int, season: int) -> tuple[int, float | None]:
    payload = get_team_ops_season(team_id, season)
    return team_id, (parse_ops_from_season_stats(payload) if payload else None)


def _fetch_pitcher_era_ip(pitcher_id: int, season: int) -> tuple[int, tuple[float, float] | None]:
    payload = get_pitcher_era_season(pitcher_id, season)
    return pitcher_id, (parse_era_ip_from_season_stats(payload) if payload else None)


def _fetch_roster(team_id: int) -> tuple[int, dict | None]:
    return team_id, get_team_active_roster(team_id)


def build_live_projections(target_date: str, season: int) -> list[dict]:
    schedule_payload = get_schedule_with_probables(target_date)
    if not schedule_payload:
        return []
    games = parse_schedule_games(schedule_payload)
    if not games:
        return []

    team_ids = sorted({g["home_team_id"] for g in games} | {g["away_team_id"] for g in games})
    starter_by_team: dict[int, int | None] = {}
    for g in games:
        starter_by_team[g["home_team_id"]] = g["home_pitcher_id"]
        starter_by_team[g["away_team_id"]] = g["away_pitcher_id"]
    starter_ids = sorted({pid for pid in starter_by_team.values() if pid is not None})

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        ops_by_team = dict(pool.map(lambda t: _fetch_team_ops(t, season), team_ids))
        rosters_by_team = dict(pool.map(_fetch_roster, team_ids))
        starter_era_ip = dict(pool.map(lambda p: _fetch_pitcher_era_ip(p, season), starter_ids))

    bullpen_pitchers_by_team: dict[int, list[int]] = {}
    bullpen_pitcher_ids: set[int] = set()
    for team_id in team_ids:
        ids = _pitcher_ids_from_roster(rosters_by_team.get(team_id), starter_by_team.get(team_id))
        bullpen_pitchers_by_team[team_id] = ids
        bullpen_pitcher_ids.update(ids)

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        bullpen_era_ip = dict(
            pool.map(lambda p: _fetch_pitcher_era_ip(p, season), sorted(bullpen_pitcher_ids))
        )

    bullpen_era_by_team: dict[int, float | None] = {}
    for team_id, pitcher_ids in bullpen_pitchers_by_team.items():
        pairs = [bullpen_era_ip[p] for p in pitcher_ids if bullpen_era_ip.get(p) is not None]
        bullpen_era_by_team[team_id] = aggregate_bullpen_era(pairs)

    with SessionLocal() as session:
        park_factors = {row.team_id: row.park_factor for row in session.query(ParkFactor).all()}

    starter_eras = [v[0] for v in starter_era_ip.values() if v is not None]
    league_avgs = compute_league_averages(list(ops_by_team.values()), starter_eras)

    results = []
    for g in games:
        home_id, away_id = g["home_team_id"], g["away_team_id"]
        home_pitcher_id, away_pitcher_id = g["home_pitcher_id"], g["away_pitcher_id"]
        home_starter = starter_era_ip.get(home_pitcher_id)
        away_starter = starter_era_ip.get(away_pitcher_id)

        payload = {
            "home_ops": ops_by_team.get(home_id),
            "away_ops": ops_by_team.get(away_id),
            "home_starter_xera": home_starter[0] if home_starter else None,
            "away_starter_xera": away_starter[0] if away_starter else None,
            "home_bullpen_era": bullpen_era_by_team.get(home_id),
            "away_bullpen_era": bullpen_era_by_team.get(away_id),
            "league_avg_era": league_avgs["league_avg_era"],
            "league_avg_ops": league_avgs["league_avg_ops"],
            "park_factor": park_factors.get(home_id),
        }

        results.append({
            "game_pk": g["game_pk"],
            "home_team_id": home_id,
            "away_team_id": away_id,
            "home_pitcher_id": home_pitcher_id,
            "away_pitcher_id": away_pitcher_id,
            "totals_line": TOTALS_LINE,
            "totals_over_prob": predict_totals_over_prob(payload),
            "first5_home_win_prob": predict_first5_home_win_prob(payload),
            "moneyline_home_win_prob": predict_moneyline_home_win_prob(payload),
            "run_line_margin": RUN_LINE_MARGIN,
            "runline_home_covers_prob": predict_runline_home_covers_prob(payload),
            "payload": payload,
        })

    return results


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", default=None, help="YYYY-MM-DD (default: hoy)")
    parser.add_argument("--season", type=int, default=None, help="default: año de --date")
    args = parser.parse_args()

    target_date = args.date or date.today().isoformat()
    season = args.season or int(target_date[:4])

    print(f"Buscando calendario de {target_date} (temporada {season})...", file=sys.stderr)
    results = build_live_projections(target_date, season)
    print(json.dumps(results, indent=2, ensure_ascii=False))
    print(f"{len(results)} juegos proyectados.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
