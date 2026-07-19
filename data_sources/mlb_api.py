"""
MLB Stats API -- misma API oficial gratuita que ya usa el resto del
ecosistema (mlb_edge_analyzer.v2/jsa), sin API key.

IMPORTANTE (ver docs/data_source_design.md): los parametros `sitCodes` y
`stats=byDateRange` NO estan verificados en vivo desde este entorno (sin
salida de red hacia statsapi.mlb.com en este sandbox). Las funciones de
parseo estan separadas de las de red precisamente para poder testear la
logica con fixtures sin necesitar esa verificacion -- pero el CONTRATO
exacto de la API (nombres de campo, forma del JSON) debe confirmarse con
`scripts/feasibility_spike.py` desde un entorno con red real antes de
confiar en esto para ingesta de produccion.
"""

from __future__ import annotations

import logging

import requests

import config

logger = logging.getLogger("jsa_v2_project")

_session = requests.Session()


def get_game_linescore(game_pk: int, timeout: int = 15) -> dict | None:
    """JSON crudo de /game/{game_pk}/linescore, o None si falla. Nunca lanza."""
    try:
        resp = _session.get(f"{config.MLB_API_BASE}/game/{game_pk}/linescore", timeout=timeout)
        resp.raise_for_status()
        return resp.json()
    except (requests.RequestException, ValueError) as e:
        logger.warning(f"No se pudo obtener linescore del juego {game_pk}: {e}")
        return None


def parse_linescore(payload: dict) -> dict | None:
    """
    Reduce el linescore crudo a los campos que necesita `linescore_game`:
    carreras acumuladas de las primeras 5 entradas y del juego completo.

    Forma esperada (no verificada en vivo): payload["innings"] es una
    lista de {"num": int, "home": {"runs": int}, "away": {"runs": int}}.
    Una entrada puede no tener "away" si el home gano sin batear en la
    baja de la 9 (o de una entrada extra) -- se trata como 0, no como
    dato faltante, porque significa "no le tocaba batear", no "no se
    pudo medir".
    """
    innings = payload.get("innings")
    if not innings:
        return None

    home_f5 = away_f5 = home_total = away_total = 0
    for inning in innings:
        num = inning.get("num")
        home_runs = (inning.get("home") or {}).get("runs") or 0
        away_runs = (inning.get("away") or {}).get("runs") or 0
        home_total += home_runs
        away_total += away_runs
        if num is not None and num <= 5:
            home_f5 += home_runs
            away_f5 += away_runs

    if home_f5 > away_f5:
        f5_result = "home"
    elif away_f5 > home_f5:
        f5_result = "away"
    else:
        f5_result = "tie"

    return {
        "home_f5_runs": home_f5,
        "away_f5_runs": away_f5,
        "home_f5_result": f5_result,
        "home_total_runs": home_total,
        "away_total_runs": away_total,
        "innings_raw": innings,
    }


def get_pitcher_throws(pitcher_id: int, timeout: int = 15) -> str | None:
    """'L' o 'R', o None si falla. Nunca lanza."""
    try:
        resp = _session.get(f"{config.MLB_API_BASE}/people/{pitcher_id}", timeout=timeout)
        resp.raise_for_status()
        people = resp.json().get("people") or []
        if not people:
            return None
        return people[0].get("pitchHand", {}).get("code")
    except (requests.RequestException, ValueError, KeyError) as e:
        logger.warning(f"No se pudo obtener la mano del pitcher {pitcher_id}: {e}")
        return None


def get_team_hitting_split(
    team_id: int, season: int, vs_hand: str, timeout: int = 15
) -> dict | None:
    """
    OPS/OBP/SLG de un equipo vs. una mano de lanzador ('L' o 'R'),
    acumulado de TEMPORADA A HOY (no point-in-time -- ver limitacion en
    docs/data_source_design.md, seccion "El problema point-in-time").
    Util solo para el spike de factibilidad, no para ingesta point-in-time
    real todavia.
    """
    if vs_hand not in ("L", "R"):
        raise ValueError(f"vs_hand debe ser 'L' o 'R', recibido: {vs_hand!r}")
    sit_code = "vl" if vs_hand == "L" else "vr"
    try:
        resp = _session.get(
            f"{config.MLB_API_BASE}/teams/{team_id}/stats",
            params={"stats": "season", "group": "hitting", "season": season, "sitCodes": sit_code},
            timeout=timeout,
        )
        resp.raise_for_status()
        return resp.json()
    except (requests.RequestException, ValueError) as e:
        logger.warning(
            f"No se pudo obtener split vs {vs_hand} del equipo {team_id}: {e}"
        )
        return None


def parse_team_hitting_split(payload: dict) -> dict | None:
    """Extrae ops/obp/slg/plateAppearances del JSON crudo de get_team_hitting_split()."""
    try:
        splits = payload["stats"][0]["splits"]
        if not splits:
            return None
        stat = splits[0]["stat"]
        return {
            "ops": float(stat["ops"]) if stat.get("ops") is not None else None,
            "obp": float(stat["obp"]) if stat.get("obp") is not None else None,
            "slg": float(stat["slg"]) if stat.get("slg") is not None else None,
            "plate_appearances": int(stat["plateAppearances"]) if stat.get("plateAppearances") is not None else None,
        }
    except (KeyError, IndexError, TypeError, ValueError) as e:
        logger.warning(f"No se pudo parsear split de bateo: {e}")
        return None
