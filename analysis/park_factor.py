"""
Park Factor -- insumo de las formulas ADOPTADAS (T1b, F1) para
proyecciones en vivo. Sin red nueva: se calcula enteramente a partir de
`historical_game` (home_score/away_score/home_team_id/away_team_id, ya
accesibles via el rol de solo lectura) -- ningun dato adicional de MLB
Stats API.

Metodologia sabermetrica estandar (basic park factor, mismo criterio
que FanGraphs): para cada equipo, se comparan las carreras totales
(anotadas + permitidas) por juego EN CASA contra las carreras totales
por juego DE VISITA -- aisla el efecto del parque del nivel real de
ofensiva/pitcheo del equipo (presente en ambas muestras). Se normaliza
dividiendo por el promedio de todos los equipos, para que la liga
completa promedie 1.0.

Simplificacion aceptada explicitamente: 1 parque = 1 team_id (no
distingue reubicaciones temporales, ej. la situacion de Athletics en
2025). Sin regresion hacia la media por tamano de muestra -- valor
conceptual, mismo criterio que otras constantes de este proyecto
(ej. STARTER_WEIGHT_F5).
"""

from __future__ import annotations


def _zero_stats() -> dict:
    return {"home_rf": 0, "home_ra": 0, "home_g": 0, "road_rf": 0, "road_ra": 0, "road_g": 0}


def compute_raw_park_factor(
    home_runs_for: float, home_runs_against: float, home_games: int,
    road_runs_for: float, road_runs_against: float, road_games: int,
) -> float | None:
    """(carreras totales por juego EN CASA) / (carreras totales por
    juego DE VISITA) del mismo equipo. None si no hay muestra suficiente
    en algun lado."""
    if home_games <= 0 or road_games <= 0:
        return None
    home_rpg = (home_runs_for + home_runs_against) / home_games
    road_rpg = (road_runs_for + road_runs_against) / road_games
    if road_rpg <= 0:
        return None
    return home_rpg / road_rpg


def normalize_park_factors(raw_factors: dict[int, float]) -> dict[int, float]:
    """Divide cada factor crudo por el promedio de todos los equipos --
    la liga completa promedia exactamente 1.0 despues de esto."""
    values = list(raw_factors.values())
    if not values:
        return {}
    mean = sum(values) / len(values)
    if mean <= 0:
        return {team_id: 1.0 for team_id in raw_factors}
    return {team_id: v / mean for team_id, v in raw_factors.items()}


def compute_park_factors_from_games(games: list[dict]) -> dict[int, float]:
    """
    games: lista de dicts con 'home_team_id', 'away_team_id',
    'home_score', 'away_score' (mismo shape que
    data_sources.historical_readonly.get_games_for_season()). Devuelve
    {team_id: park_factor normalizado}, promedio de liga = 1.0.
    """
    stats: dict[int, dict] = {}
    for g in games:
        home_id, away_id = g.get("home_team_id"), g.get("away_team_id")
        home_score, away_score = g.get("home_score"), g.get("away_score")
        if home_id is None or away_id is None or home_score is None or away_score is None:
            continue

        home_stats = stats.setdefault(home_id, _zero_stats())
        home_stats["home_rf"] += home_score
        home_stats["home_ra"] += away_score
        home_stats["home_g"] += 1

        road_stats = stats.setdefault(away_id, _zero_stats())
        road_stats["road_rf"] += away_score
        road_stats["road_ra"] += home_score
        road_stats["road_g"] += 1

    raw: dict[int, float] = {}
    for team_id, s in stats.items():
        pf = compute_raw_park_factor(
            s["home_rf"], s["home_ra"], s["home_g"], s["road_rf"], s["road_ra"], s["road_g"],
        )
        if pf is not None:
            raw[team_id] = pf

    return normalize_park_factors(raw)
