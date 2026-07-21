"""
Spike de factibilidad para el ERA del cerrador (Linea 3, nueva --
`jsa/historical/point_in_time_provider.py::bullpen_era_as_of()` YA
calcula el ERA especifico de cada pitcher del roster para promediar el
ERA de bullpen, e identifica al cerrador via `most saves`, pero
DESCARTA ambos datos despues de derivar solo `closer_available` (bool)
-- ver jsa/historical/snapshot_reconstruction.py lineas 78-132.
`historical_snapshot.payload` nunca persiste `closer_pitcher_id` ni el
ERA propio del cerrador).

Recalcular roster+stats point-in-time DIA POR DIA (como hace
bullpen_era_as_of()) para los 13,101 juegos x 2 equipos costaria
~366,000 llamadas (roster + ~13 pitchers por equipo-fecha) --
inviable. Este spike verifica una alternativa mucho mas barata:
`stats=gameLog` por pitcher (1 llamada por pitcher, trae saves/ER/IP de
CADA juego que jugo esa temporada) permite reconstruir el ERA y los
saves acumulados del cerrador dia por dia en Python, sin pedirle a la
API un recorte point-in-time (mismo principio que ya aprendimos: nunca
pedirle a la fuente un corte directo, reconstruir nosotros).

Verifica en vivo:
1. Se puede obtener el roster de TEMPORADA COMPLETA de un equipo
   (`rosterType=fullSeason`) -- pool de candidatos a cerrador.
2. `stats=gameLog` responde y trae, por cada juego, date/saves/
   earnedRuns/inningsPitched -- suficiente para reconstruir ERA y saves
   acumulados point-in-time.
3. Costo real por llamada -- 1 roster call + 1 gameLog call por
   pitcher relevista candidato.
"""

from __future__ import annotations

import sys
import os
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests

MLB_API_BASE = "https://statsapi.mlb.com/api/v1"

SAMPLE_TEAM_ID = 136  # Seattle, mismo equipo usado en spikes anteriores
SAMPLE_SEASON = 2024


def main() -> int:
    t0 = time.monotonic()
    resp = requests.get(
        f"{MLB_API_BASE}/teams/{SAMPLE_TEAM_ID}/roster",
        params={"rosterType": "fullSeason", "season": SAMPLE_SEASON},
        timeout=15,
    )
    elapsed_roster = time.monotonic() - t0
    print(f"roster fullSeason: status={resp.status_code} elapsed={elapsed_roster:.3f}s")
    resp.raise_for_status()
    roster = resp.json().get("roster") or []
    pitchers = [p for p in roster if (p.get("position") or {}).get("abbreviation") == "P"]
    print(f"roster completo: {len(roster)} jugadores, {len(pitchers)} pitchers")
    if not pitchers:
        print("ADVERTENCIA: sin pitchers en el roster -- forma inesperada")
        return 1

    sample_pitcher_id = pitchers[0]["person"]["id"]
    sample_pitcher_name = pitchers[0]["person"].get("fullName")
    print(f"\nProbando gameLog de un pitcher de muestra: {sample_pitcher_name} ({sample_pitcher_id})")

    t1 = time.monotonic()
    resp2 = requests.get(
        f"{MLB_API_BASE}/people/{sample_pitcher_id}/stats",
        params={"stats": "gameLog", "group": "pitching", "season": SAMPLE_SEASON},
        timeout=15,
    )
    elapsed_gamelog = time.monotonic() - t1
    print(f"gameLog: status={resp2.status_code} elapsed={elapsed_gamelog:.3f}s")
    resp2.raise_for_status()
    splits = (resp2.json().get("stats") or [{}])[0].get("splits") or []
    print(f"juegos en el gameLog: {len(splits)}")

    if splits:
        print("\n--- Muestra de 3 juegos (estructura real) ---")
        for i, sp in enumerate(splits[:3]):
            stat = sp.get("stat") or {}
            print(f"\nJuego {i + 1}:")
            print(f"  date={sp.get('date')}")
            print(f"  saves={stat.get('saves')} earnedRuns={stat.get('earnedRuns')} "
                  f"inningsPitched={stat.get('inningsPitched')} gamesPitched={stat.get('gamesPitched')}")

    total_pitchers_estimate = len(pitchers)
    n_teams_seasons = 30 * 5
    projected_calls = n_teams_seasons * (1 + total_pitchers_estimate)
    projected_time_seq = projected_calls * ((elapsed_roster + elapsed_gamelog) / (1 + total_pitchers_estimate))
    print(f"\nCosto proyectado: ~{total_pitchers_estimate} pitchers/equipo x 30 equipos x 5 temporadas "
          f"= ~{projected_calls} llamadas totales (roster + gameLog), "
          f"~{projected_time_seq:.0f}s secuencial, ~{projected_time_seq / 8:.0f}s con 8 workers.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
