"""
Calcula y persiste el park factor de cada equipo -- ver
analysis/park_factor.py para la metodologia. Sin red nueva: toda la
entrada viene de `historical_game` (rol de solo lectura). Se recalcula
con las 5 temporadas completas (config.HISTORICAL_SEASONS) cada vez que
se corre -- barato (una sola pasada en memoria), no hace falta lógica
de "ya existe, saltar".
"""

from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
from analysis.park_factor import compute_park_factors_from_games
from data_sources.historical_readonly import get_games_for_season
from db.database import ParkFactor, SessionLocal, init_db


def compute_and_persist() -> dict:
    all_games: list[dict] = []
    for season in config.HISTORICAL_SEASONS:
        all_games.extend(get_games_for_season(season))

    factors = compute_park_factors_from_games(all_games)
    seasons_str = ",".join(str(s) for s in config.HISTORICAL_SEASONS)

    init_db()
    with SessionLocal() as session:
        session.query(ParkFactor).delete()
        for team_id, pf in factors.items():
            games_used = sum(
                1 for g in all_games if g.get("home_team_id") == team_id or g.get("away_team_id") == team_id
            )
            session.add(ParkFactor(
                team_id=team_id, park_factor=pf, seasons_used=seasons_str, games_used=games_used,
            ))
        session.commit()

    return {
        "teams_computed": len(factors),
        "games_total": len(all_games),
        "seasons_used": seasons_str,
        "min_factor": round(min(factors.values()), 4) if factors else None,
        "max_factor": round(max(factors.values()), 4) if factors else None,
        "mean_factor": round(sum(factors.values()) / len(factors), 4) if factors else None,
    }


def main() -> int:
    print("Calculando park factors desde historical_game...", file=sys.stderr)
    result = compute_and_persist()
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
