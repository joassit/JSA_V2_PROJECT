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


def get_game_play_by_play(game_pk: int, timeout: int = 15) -> dict | None:
    """
    JSON crudo de /game/{game_pk}/playByPlay -- pitch a pitch del juego
    completo (ambos equipos, una sola llamada), confirmado en vivo
    (scripts/feasibility_spike_chase_rate.py): cada pitch trae
    pitchData.strikeZoneTop/Bottom, pitchData.coordinates.pX/pZ y
    details.code. Nunca lanza.
    """
    try:
        resp = _session.get(f"{config.MLB_API_BASE}/game/{game_pk}/playByPlay", timeout=timeout)
        resp.raise_for_status()
        return resp.json()
    except (requests.RequestException, ValueError) as e:
        logger.warning(f"No se pudo obtener playByPlay del juego {game_pk}: {e}")
        return None


def get_team_roster_full_season(team_id: int, season: int, timeout: int = 15) -> dict | None:
    """
    JSON crudo de /teams/{team_id}/roster?rosterType=fullSeason -- pool
    de candidatos a cerrador de la temporada completa (confirmado en
    vivo, scripts/feasibility_spike_closer_era.py). Mas barato que
    reconstruir el roster ACTIVO dia por dia (lo que hace
    jsa/historical/point_in_time_provider.py::bullpen_era_as_of()) --
    limitacion aceptada: incluye jugadores que ya no estaban activos en
    una fecha de corte especifica (ej. tras un trade/DFA), documentado
    en docs/data_source_design.md.
    """
    try:
        resp = _session.get(
            f"{config.MLB_API_BASE}/teams/{team_id}/roster",
            params={"rosterType": "fullSeason", "season": season},
            timeout=timeout,
        )
        resp.raise_for_status()
        return resp.json()
    except (requests.RequestException, ValueError) as e:
        logger.warning(f"No se pudo obtener roster fullSeason del equipo {team_id}: {e}")
        return None


def get_pitcher_game_log(pitcher_id: int, season: int, timeout: int = 15) -> dict | None:
    """
    JSON crudo de /people/{pitcher_id}/stats?stats=gameLog&group=pitching
    -- saves/earnedRuns/inningsPitched por CADA juego que jugo ese
    pitcher en la temporada, confirmado en vivo. Permite reconstruir el
    ERA y los saves acumulados del cerrador dia por dia en Python (Camino
    2), sin pedirle a la API un corte point-in-time directo.
    """
    try:
        resp = _session.get(
            f"{config.MLB_API_BASE}/people/{pitcher_id}/stats",
            params={"stats": "gameLog", "group": "pitching", "season": season},
            timeout=timeout,
        )
        resp.raise_for_status()
        return resp.json()
    except (requests.RequestException, ValueError) as e:
        logger.warning(f"No se pudo obtener gameLog del pitcher {pitcher_id}: {e}")
        return None


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


def get_team_hitting_split_by_date_range(
    team_id: int, start_date: str, end_date: str, vs_hand: str, season: int, timeout: int = 15
) -> dict | None:
    """
    Igual que get_team_hitting_split() pero con stats=byDateRange.

    CONFIRMADO ROTO (2026-07-20, scripts/diagnose_sitcodes_bydaterange.py):
    `sitCodes` NO tiene efecto combinado con `stats=byDateRange` -- vl,
    vr y sin sitCodes devuelven resultados identicos, incluso en ventanas
    de 1 solo dia. Se conserva esta funcion solo porque
    scripts/feasibility_spike.py y sus tests la documentan como parte del
    historial de la investigacion -- NO USAR para ingesta real de splits
    point-in-time, usar get_team_hitting_by_date() +
    analysis.stats_utils.ops_from_raw_counts() en su lugar (Camino 2 de
    docs/data_source_design.md). start_date/end_date en formato YYYY-MM-DD.
    """
    if vs_hand not in ("L", "R"):
        raise ValueError(f"vs_hand debe ser 'L' o 'R', recibido: {vs_hand!r}")
    sit_code = "vl" if vs_hand == "L" else "vr"
    try:
        resp = _session.get(
            f"{config.MLB_API_BASE}/teams/{team_id}/stats",
            params={
                "stats": "byDateRange", "group": "hitting", "season": season,
                "sitCodes": sit_code, "startDate": start_date, "endDate": end_date,
            },
            timeout=timeout,
        )
        resp.raise_for_status()
        return resp.json()
    except (requests.RequestException, ValueError) as e:
        logger.warning(
            f"No se pudo obtener split byDateRange vs {vs_hand} del equipo {team_id}: {e}"
        )
        return None


def get_team_hitting_by_date(team_id: int, game_date: str, season: int, timeout: int = 15) -> dict | None:
    """
    Linea de bateo cruda del equipo para UN SOLO dia (`stats=byDateRange`,
    `startDate=endDate=game_date`). Sin `sitCodes` -- confirmado en vivo
    (scripts/diagnose_sitcodes_bydaterange.py, corridas 29716014513 y
    29716111744) que ese parametro NO tiene efecto combinado con
    `byDateRange`, ni siquiera en ventanas de 1 dia. La clasificacion por
    mano del lanzador rival se hace en `scripts/ingest_handedness_splits.py`
    acumulando estos conteos crudos dia por dia (Camino 2 de
    docs/data_source_design.md), no delegandola en la API.
    """
    try:
        resp = _session.get(
            f"{config.MLB_API_BASE}/teams/{team_id}/stats",
            params={
                "stats": "byDateRange", "group": "hitting", "season": season,
                "startDate": game_date, "endDate": game_date,
            },
            timeout=timeout,
        )
        resp.raise_for_status()
        return resp.json()
    except (requests.RequestException, ValueError) as e:
        logger.warning(f"No se pudo obtener linea de bateo diaria del equipo {team_id} @ {game_date}: {e}")
        return None


def parse_team_hitting_raw(payload: dict) -> dict | None:
    """Conteos crudos (no ops/obp/slg precalculados) de una linea de
    bateo -- insumo para acumular splits por mano nosotros mismos."""
    try:
        splits = payload["stats"][0]["splits"]
        if not splits:
            return None
        stat = splits[0]["stat"]
        return {
            "ab": int(stat.get("atBats") or 0),
            "h": int(stat.get("hits") or 0),
            "bb": int(stat.get("baseOnBalls") or 0),
            "hbp": int(stat.get("hitByPitch") or 0),
            "sf": int(stat.get("sacFlies") or 0),
            "tb": int(stat.get("totalBases") or 0),
            "pa": int(stat.get("plateAppearances") or 0),
        }
    except (KeyError, IndexError, TypeError, ValueError) as e:
        logger.warning(f"No se pudo parsear linea de bateo cruda: {e}")
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


# --- Proyecciones EN VIVO (juegos futuros) -- ver docs/data_source_design.md,
# "Proyecciones en vivo". A diferencia de todo lo anterior (point-in-time
# historico), aqui "hoy" ya ES el corte -- no hace falta reconstruir dia
# por dia, `stats=season` de la API ya da el acumulado correcto.

def get_schedule_with_probables(target_date: str, timeout: int = 15) -> dict | None:
    """JSON crudo de /schedule?hydrate=probablePitcher,team -- confirmado
    en vivo (scripts/feasibility_spike_live_schedule.py). `target_date`
    en formato YYYY-MM-DD."""
    try:
        resp = _session.get(
            f"{config.MLB_API_BASE}/schedule",
            params={"sportId": 1, "date": target_date, "hydrate": "probablePitcher,team"},
            timeout=timeout,
        )
        resp.raise_for_status()
        return resp.json()
    except (requests.RequestException, ValueError) as e:
        logger.warning(f"No se pudo obtener el calendario de {target_date}: {e}")
        return None


def parse_schedule_games(payload: dict) -> list[dict]:
    """Reduce el calendario crudo a una lista de
    {game_pk, home_team_id, away_team_id, home_pitcher_id, away_pitcher_id,
    venue_id} -- solo juegos con ambos abridores probables ya anunciados.
    `venue_id` se usa para el pronostico de clima (ver
    analysis/ballpark_locations.py) -- puede ser None si el calendario no
    trae `venue` para ese juego."""
    games: list[dict] = []
    for d in payload.get("dates") or []:
        for g in d.get("games") or []:
            teams = g.get("teams") or {}
            home, away = teams.get("home") or {}, teams.get("away") or {}
            home_team_id = (home.get("team") or {}).get("id")
            away_team_id = (away.get("team") or {}).get("id")
            home_pitcher_id = (home.get("probablePitcher") or {}).get("id")
            away_pitcher_id = (away.get("probablePitcher") or {}).get("id")
            if None in (home_team_id, away_team_id):
                continue
            games.append({
                "game_pk": g.get("gamePk"),
                "home_team_id": home_team_id, "away_team_id": away_team_id,
                "home_pitcher_id": home_pitcher_id, "away_pitcher_id": away_pitcher_id,
                "venue_id": (g.get("venue") or {}).get("id"),
            })
    return games


def get_team_ops_season(team_id: int, season: int, timeout: int = 15) -> dict | None:
    """JSON crudo de OPS de equipo, temporada a la fecha ACTUAL --
    `stats=season` (sin sitCodes ni byDateRange, mismo patron que
    `data/stats.py::get_team_ops()` del proyecto legado). "Hoy" ya es el
    corte, no hace falta reconstruir nada."""
    try:
        resp = _session.get(
            f"{config.MLB_API_BASE}/teams/{team_id}/stats",
            params={"stats": "season", "group": "hitting", "season": season},
            timeout=timeout,
        )
        resp.raise_for_status()
        return resp.json()
    except (requests.RequestException, ValueError) as e:
        logger.warning(f"No se pudo obtener OPS en vivo del equipo {team_id}: {e}")
        return None


def get_pitcher_era_season(pitcher_id: int, season: int, timeout: int = 15) -> dict | None:
    """JSON crudo de ERA/IP de un pitcher, temporada a la fecha ACTUAL."""
    try:
        resp = _session.get(
            f"{config.MLB_API_BASE}/people/{pitcher_id}/stats",
            params={"stats": "season", "group": "pitching", "season": season},
            timeout=timeout,
        )
        resp.raise_for_status()
        return resp.json()
    except (requests.RequestException, ValueError) as e:
        logger.warning(f"No se pudo obtener ERA en vivo del pitcher {pitcher_id}: {e}")
        return None


def get_team_active_roster(team_id: int, timeout: int = 15) -> dict | None:
    """JSON crudo del roster ACTIVO actual (sin `date=`, refleja el
    roster de HOY) -- distinto de get_team_roster_full_season(), que
    trae el pool de TODA la temporada (usado para el pool de candidatos
    a cerrador, no para bullpen en vivo)."""
    try:
        resp = _session.get(
            f"{config.MLB_API_BASE}/teams/{team_id}/roster",
            params={"rosterType": "active"},
            timeout=timeout,
        )
        resp.raise_for_status()
        return resp.json()
    except (requests.RequestException, ValueError) as e:
        logger.warning(f"No se pudo obtener el roster activo del equipo {team_id}: {e}")
        return None


def parse_ops_from_season_stats(payload: dict) -> float | None:
    try:
        splits = payload["stats"][0]["splits"]
        if not splits:
            return None
        ops = splits[0]["stat"].get("ops")
        return float(ops) if ops is not None else None
    except (KeyError, IndexError, TypeError, ValueError) as e:
        logger.warning(f"No se pudo parsear OPS de season stats: {e}")
        return None


def parse_era_ip_from_season_stats(payload: dict) -> tuple[float, float] | None:
    """(era, innings_pitched) o None si falta algun dato."""
    try:
        splits = payload["stats"][0]["splits"]
        if not splits:
            return None
        stat = splits[0]["stat"]
        era, ip_str = stat.get("era"), stat.get("inningsPitched")
        if era is None or ip_str is None:
            return None
        whole, _, frac = str(ip_str).partition(".")
        whole_f = float(whole) if whole else 0.0
        thirds = {"0": 0.0, "1": 1 / 3, "2": 2 / 3}.get(frac, 0.0)
        return float(era), whole_f + thirds
    except (KeyError, IndexError, TypeError, ValueError) as e:
        logger.warning(f"No se pudo parsear ERA/IP de season stats: {e}")
        return None


# --- Clima -- ver docs/data_source_design.md, "Resultado real de
# Weather1". MLB Stats API SOLO registra clima real DESPUES de que el
# juego ocurre (confirmado en vivo, scripts/feasibility_spike_weather.py)
# -- estas 2 funciones son para el HISTORICO (ingesta point-in-time-safe
# porque el juego ya paso). Para clima de juegos FUTUROS ver
# get_forecast_temperature() (Open-Meteo) mas abajo.

def get_game_weather_raw(game_pk: int, timeout: int = 15) -> dict | None:
    """JSON crudo de /feed/live (v1.1) -- unico endpoint con gameData.weather."""
    try:
        resp = _session.get(f"{config.MLB_API_BASE_V11}/game/{game_pk}/feed/live", timeout=timeout)
        resp.raise_for_status()
        return resp.json()
    except (requests.RequestException, ValueError) as e:
        logger.warning(f"No se pudo obtener el clima del juego {game_pk}: {e}")
        return None


def parse_weather(payload: dict) -> dict | None:
    """{'temp_f', 'condition', 'wind_raw'} o None si no hay clima real
    (dict vacio {} -- juego aun no jugado, ver spike de factibilidad)."""
    weather = (payload.get("gameData") or {}).get("weather") or {}
    temp = weather.get("temp")
    if temp is None:
        return None
    try:
        temp_f = float(temp)
    except (TypeError, ValueError):
        return None
    return {"temp_f": temp_f, "condition": weather.get("condition"), "wind_raw": weather.get("wind")}


def get_venue_location_raw(venue_id: int, timeout: int = 15) -> dict | None:
    """JSON crudo de /venues/{id}?hydrate=location -- confirmado en vivo
    (scripts/feasibility_spike_venues.py) que trae `defaultCoordinates`
    real, sin necesidad de ningun mapeo estadio->lat/lon escrito a mano."""
    try:
        resp = _session.get(
            f"{config.MLB_API_BASE}/venues/{venue_id}", params={"hydrate": "location"}, timeout=timeout,
        )
        resp.raise_for_status()
        return resp.json()
    except (requests.RequestException, ValueError) as e:
        logger.warning(f"No se pudo obtener la ubicacion del venue {venue_id}: {e}")
        return None


def parse_venue_coordinates(payload: dict) -> tuple[float, float] | None:
    """(latitude, longitude) o None si falta algun dato."""
    try:
        venues = payload.get("venues") or []
        if not venues:
            return None
        coords = (venues[0].get("location") or {}).get("defaultCoordinates") or {}
        lat, lon = coords.get("latitude"), coords.get("longitude")
        if lat is None or lon is None:
            return None
        return float(lat), float(lon)
    except (KeyError, TypeError, ValueError) as e:
        logger.warning(f"No se pudo parsear coordenadas de venue: {e}")
        return None


def get_forecast_temperature(latitude: float, longitude: float, target_date: str, timeout: int = 15) -> float | None:
    """
    Temperatura pronosticada (°F) para una fecha/ubicacion -- Open-Meteo,
    gratuita, sin API key (confirmado en vivo,
    scripts/feasibility_spike_open_meteo.py). Promedio del pronostico
    horario entre las 18:00 y 21:00 hora local del estadio (horario tipico
    de primer pitch de MLB) -- aproximacion simple, no especifica el
    horario exacto del juego (eso requeriria cruzar con el horario real
    del calendario, fuera de alcance de esta primera version).
    """
    try:
        resp = _session.get(
            config.OPEN_METEO_BASE,
            params={
                "latitude": latitude, "longitude": longitude,
                "hourly": "temperature_2m", "temperature_unit": "fahrenheit",
                "start_date": target_date, "end_date": target_date,
                "timezone": "auto",
            },
            timeout=timeout,
        )
        resp.raise_for_status()
        payload = resp.json()
        hourly = payload.get("hourly") or {}
        times, temps = hourly.get("time") or [], hourly.get("temperature_2m") or []
        evening = [t for time_str, t in zip(times, temps) if time_str.endswith(("18:00", "19:00", "20:00", "21:00"))]
        if not evening:
            return None
        return sum(evening) / len(evening)
    except (requests.RequestException, ValueError, KeyError) as e:
        logger.warning(f"No se pudo obtener el pronostico de clima ({latitude},{longitude},{target_date}): {e}")
        return None
