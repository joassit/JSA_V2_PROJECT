"""
Acceso de SOLO LECTURA al historico compartido de `mlb_edge_analyzer.v2`
(jsa/), vía JSA_HISTORICAL_DATABASE_URL_READONLY (rol de Postgres de solo
lectura -- ver docs/scope_handoff.md, seccion "Acceso a datos").

Nombres de columna verificados contra `jsa/historical/db.py` del repo
hermano (acceso directo al codigo fuente, no supuestos):
- historical_game: game_pk, game_date, season, home_team_id,
  away_team_id, home_pitcher_id, away_pitcher_id, home_score,
  away_score, winner.
- historical_snapshot: game_pk, game_date, season, snapshot_hash,
  payload (JSON -- el GameSnapshot completo point-in-time-safe).
- historical_statcast_event: game_pk, game_date, season, at_bat_number,
  pitch_number, inning_topbot, batter_id, pitcher_id, launch_speed, xwoba.

Este modulo NUNCA emite INSERT/UPDATE/DELETE -- ademas del rol de
Postgres de solo lectura (proteccion real a nivel de base de datos), cada
funcion aqui usa unicamente `SELECT` explicito, y `config.READONLY_ALLOWED_TABLES`
es la lista blanca contra la que se valida cualquier nombre de tabla
antes de interpolarlo en una query.
"""

from __future__ import annotations

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

import config


class ReadonlyAccessError(RuntimeError):
    """Se uso un nombre de tabla fuera de config.READONLY_ALLOWED_TABLES."""


def _engine() -> Engine:
    if not config.JSA_HISTORICAL_DATABASE_URL_READONLY:
        raise RuntimeError(
            "JSA_HISTORICAL_DATABASE_URL_READONLY no esta configurada -- "
            "ver docs/scope_handoff.md, seccion 'Acceso a datos', para "
            "crear el rol de solo lectura en Neon."
        )
    # SQLAlchemy abre la conexion perezosamente -- no valida credenciales
    # hasta el primer query real.
    return create_engine(config.JSA_HISTORICAL_DATABASE_URL_READONLY)


def _assert_allowed(table: str) -> None:
    if table not in config.READONLY_ALLOWED_TABLES:
        raise ReadonlyAccessError(
            f"Tabla '{table}' no esta en la lista blanca de solo lectura "
            f"({sorted(config.READONLY_ALLOWED_TABLES)})."
        )


def get_games_for_season(season: int) -> list[dict]:
    """
    Juegos con resultado real de una temporada -- base para cruzar por
    game_pk contra linescore_game / pitcher_matchup_feature propios.
    """
    _assert_allowed("historical_game")
    query = text(
        """
        SELECT game_pk, game_date, season, home_team_id, away_team_id,
               home_pitcher_id, away_pitcher_id, home_score, away_score, winner
        FROM historical_game
        WHERE season = :season AND winner IS NOT NULL
        ORDER BY game_date
        """
    )
    with _engine().connect() as conn:
        rows = conn.execute(query, {"season": season}).mappings().all()
    return [dict(r) for r in rows]


def get_snapshot_payload(game_pk: int) -> dict | None:
    """
    El GameSnapshot point-in-time-safe completo (ERA/OPS con shrinkage,
    contexto, etc.) de un juego especifico -- insumo para comparar
    hipotesis nuevas contra las variables YA validadas, sin recalcularlas.
    """
    _assert_allowed("historical_snapshot")
    query = text(
        "SELECT payload FROM historical_snapshot WHERE game_pk = :game_pk LIMIT 1"
    )
    with _engine().connect() as conn:
        row = conn.execute(query, {"game_pk": game_pk}).mappings().first()
    return dict(row["payload"]) if row and row["payload"] is not None else None


def get_statcast_events_for_game(game_pk: int) -> list[dict]:
    """Eventos Statcast (xwOBA/launch_speed a nivel bateo-en-juego) de un juego."""
    _assert_allowed("historical_statcast_event")
    query = text(
        """
        SELECT game_pk, at_bat_number, pitch_number, inning_topbot,
               batter_id, pitcher_id, launch_speed, xwoba
        FROM historical_statcast_event
        WHERE game_pk = :game_pk
        ORDER BY at_bat_number, pitch_number
        """
    )
    with _engine().connect() as conn:
        rows = conn.execute(query, {"game_pk": game_pk}).mappings().all()
    return [dict(r) for r in rows]
