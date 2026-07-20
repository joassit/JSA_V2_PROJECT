"""
Spike de factibilidad -- Linea 1 (matchup por mano) + Linea 2 (linescore).

NO AUTORIZADO PARA CORRER TODAVIA. Ver docs/data_source_design.md,
seccion "Spike de factibilidad", y docs/scope_handoff.md: cada spike de
este proyecto requiere confirmacion explicita del usuario antes de
dispararse, mismo criterio que ya siguio `jsa/` para Statcast Etapa 1.

Disenado para correr desde un workflow de GitHub Actions (red real) --
este sandbox de desarrollo confirmo (2026-07-19) que NO tiene salida de
red hacia statsapi.mlb.com (CONNECT devuelve 403 del proxy del entorno),
asi que correr esto localmente aqui no sirve para validar nada.

No escribe en ninguna base de datos -- solo lectura de la API pública e
impresión de un resumen a stdout, mismo patrón que
`jsa/historical/statcast_ingestion.py`'s spike original.
"""

from __future__ import annotations

import json
import os
import sys
import time

# Permite `python scripts/feasibility_spike.py` desde cualquier cwd --
# sin esto, `import data_sources...`/`import config` falla porque Python
# solo agrega la carpeta del script (scripts/) a sys.path, no la raiz del
# repo. Mismo patron que conftest.py usa para pytest.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data_sources.mlb_api import (
    get_game_linescore,
    get_pitcher_throws,
    get_team_hitting_split,
    get_team_hitting_split_by_date_range,
    parse_linescore,
    parse_team_hitting_split,
)

# Un juego/equipo/pitcher real de temporada regular 2024 como muestra --
# elegidos arbitrariamente, no requieren estar vivos ni ser relevantes,
# solo existir en el histórico de MLB Stats API.
SAMPLE_GAME_PK = 745444
SAMPLE_TEAM_ID = 136  # Seattle Mariners
SAMPLE_PITCHER_ID = 592789  # Robbie Ray
SAMPLE_SEASON = 2024


def check_linescore() -> dict:
    t0 = time.monotonic()
    raw = get_game_linescore(SAMPLE_GAME_PK)
    elapsed = time.monotonic() - t0
    if raw is None:
        return {"ok": False, "reason": "request_failed", "elapsed_s": elapsed}
    parsed = parse_linescore(raw)
    return {"ok": parsed is not None, "elapsed_s": elapsed, "parsed": parsed}


def check_pitcher_hand() -> dict:
    t0 = time.monotonic()
    hand = get_pitcher_throws(SAMPLE_PITCHER_ID)
    elapsed = time.monotonic() - t0
    return {"ok": hand in ("L", "R"), "elapsed_s": elapsed, "hand": hand}


def check_hitting_split() -> dict:
    t0 = time.monotonic()
    raw = get_team_hitting_split(SAMPLE_TEAM_ID, SAMPLE_SEASON, "L")
    elapsed = time.monotonic() - t0
    if raw is None:
        return {"ok": False, "reason": "request_failed", "elapsed_s": elapsed}
    parsed = parse_team_hitting_split(raw)
    return {"ok": parsed is not None, "elapsed_s": elapsed, "parsed": parsed}


def check_hitting_split_by_date_range() -> dict:
    """
    El check MAS IMPORTANTE de este spike para la Linea 1: si esto
    funciona, el split point-in-time se reconstruye con 1 llamada por
    equipo por ventana (barato). Si falla o el numero no cambia respecto
    a check_hitting_split() (mismo team/season), la API esta ignorando
    startDate/endDate combinado con sitCodes -- hay que ir por
    reconstruccion dia-por-dia (caro, como Trend).
    """
    t0 = time.monotonic()
    raw = get_team_hitting_split_by_date_range(
        SAMPLE_TEAM_ID, f"{SAMPLE_SEASON}-04-01", f"{SAMPLE_SEASON}-05-01", "L", SAMPLE_SEASON,
    )
    elapsed = time.monotonic() - t0
    if raw is None:
        return {"ok": False, "reason": "request_failed", "elapsed_s": elapsed}
    parsed = parse_team_hitting_split(raw)
    return {"ok": parsed is not None, "elapsed_s": elapsed, "parsed": parsed}


def main() -> int:
    results = {
        "linescore": check_linescore(),
        "pitcher_hand": check_pitcher_hand(),
        "hitting_split_vs_lhp": check_hitting_split(),
        "hitting_split_vs_lhp_by_date_range": check_hitting_split_by_date_range(),
    }
    print(json.dumps(results, indent=2, default=str))

    all_ok = all(r.get("ok") for r in results.values())
    if not all_ok:
        print("\nRESULTADO: al menos un check fallo -- ver docs/data_source_design.md "
              "antes de construir ingesta real sobre lo que SI funciono.", file=sys.stderr)
        return 1

    same_pa_as_full_season = (
        results["hitting_split_vs_lhp"]["parsed"]["plate_appearances"]
        == results["hitting_split_vs_lhp_by_date_range"]["parsed"]["plate_appearances"]
    )
    if same_pa_as_full_season:
        print("\nALERTA: byDateRange devolvio las MISMAS plate_appearances que "
              "stats=season completa -- probablemente esta IGNORANDO startDate/"
              "endDate. No confiar en el camino 1 (barato) sin investigar mas.",
              file=sys.stderr)
    else:
        print("\nRESULTADO: byDateRange + sitCodes SI parece filtrar por fecha "
              "(plate_appearances distinto al de la temporada completa) -- "
              "camino 1 (1 llamada por equipo por ventana) parece viable.")

    print("\nRESULTADO: los 4 checks respondieron con la forma esperada. "
          "Siguiente paso: medir costo real a escala (13,101 juegos) antes "
          "de autorizar ingesta completa -- este spike solo prueba 1 caso "
          "de cada uno.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
