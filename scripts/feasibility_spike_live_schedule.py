"""
Spike de factibilidad para proyecciones EN VIVO (juegos futuros), de
forma independiente -- ver docs/data_source_design.md, "Proyecciones en
vivo". Verifica en vivo, ANTES de comprometerse a ingerir/consumir
nada:

1. `/schedule?hydrate=probablePitcher,team` responde y trae, por cada
   juego del dia, los IDs de los abridores probables + team ids -- el
   insumo minimo para armar un payload compatible con
   predict_totals_over_prob()/f1_first5_win_prob() (analysis/
   totals_candidate_audit.py, analysis/first5_candidate_audit.py).
2. Costo real por llamada (1 sola, cubre todos los juegos del dia).

El clima NO se verifica aqui -- project_runs_pair() (la formula base de
ambas funciones adoptadas) no consume temperatura, solo home_ops/
away_ops/home_starter_xera/away_starter_xera/home_bullpen_era/
away_bullpen_era/park_factor/promedios de liga.
"""

from __future__ import annotations

import sys
import os
import time
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests

MLB_API_BASE = "https://statsapi.mlb.com/api/v1"


def _fetch_schedule(target_date: str) -> dict:
    t0 = time.monotonic()
    resp = requests.get(
        f"{MLB_API_BASE}/schedule",
        params={"sportId": 1, "date": target_date, "hydrate": "probablePitcher,team"},
        timeout=15,
    )
    elapsed = time.monotonic() - t0
    resp.raise_for_status()
    print(f"schedule {target_date}: status={resp.status_code} elapsed={elapsed:.3f}s")
    return resp.json()


def main() -> int:
    today = date.today()
    # Se prueban HOY y MAÑANA -- el spike necesita al menos un dia con
    # juegos futuros reales para confirmar que probablePitcher viene
    # poblado (no solo para juegos ya en curso/terminados de hoy).
    checked_any_with_games = False

    for offset in (0, 1, 2):
        target = (today + timedelta(days=offset)).isoformat()
        payload = _fetch_schedule(target)
        dates = payload.get("dates") or []
        if not dates or not dates[0].get("games"):
            print(f"  sin juegos para {target}")
            continue

        games = dates[0]["games"]
        print(f"  {len(games)} juegos encontrados para {target}")
        checked_any_with_games = True

        sample = games[:3]
        for i, g in enumerate(sample):
            home = g.get("teams", {}).get("home", {})
            away = g.get("teams", {}).get("away", {})
            home_team = (home.get("team") or {})
            away_team = (away.get("team") or {})
            home_pitcher = home.get("probablePitcher") or {}
            away_pitcher = away.get("probablePitcher") or {}
            venue = g.get("venue") or {}
            print(f"\n  Juego {i + 1}: gamePk={g.get('gamePk')} status={g.get('status', {}).get('detailedState')}")
            print(f"    home_team_id={home_team.get('id')} name={home_team.get('name')}")
            print(f"    away_team_id={away_team.get('id')} name={away_team.get('name')}")
            print(f"    home_probable_pitcher_id={home_pitcher.get('id')} name={home_pitcher.get('fullName')}")
            print(f"    away_probable_pitcher_id={away_pitcher.get('id')} name={away_pitcher.get('fullName')}")
            print(f"    venue_id={venue.get('id')} venue_name={venue.get('name')}")

        # Solo se necesita 1 dia con muestra real para confirmar el contrato.
        break

    if not checked_any_with_games:
        print("ADVERTENCIA: no se encontraron juegos en los proximos 3 dias -- "
              "no se pudo confirmar el contrato con datos reales")
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
