"""
Base de datos PROPIA de JSA_V2_PROJECT (lectura + escritura).

Usa la MISMA connection string que data_sources/historical_readonly.py
(config.JSA_SHARED_DATABASE_URL) -- el aislamiento entre "tablas propias"
y "tablas historicas de jsa/" ya NO es por engine/secret separado, es por
schema de Postgres: el rol `jsa_v2` detras de esa URL tiene
`search_path = team_strength, public`, asi que las tablas de este archivo
(sin schema calificado) caen automaticamente en `team_strength`, dueno
exclusivo de ese schema -- Postgres, no este codigo, es quien impide que
una tabla propia termine en `public`. Ver docs/scope_handoff.md, seccion
"Acceso a datos" (revision 2026-07-19).

Sin JSA_SHARED_DATABASE_URL configurada, cae a SQLite local (cero
configuracion, util para tests y desarrollo) -- mismo criterio que
DATABASE_URL en el proyecto legado. SQLite no tiene schemas Postgres, asi
que en modo local las tablas propias simplemente viven en el unico
namespace del archivo .db -- no hay tablas historicas de jsa/ que
proteger localmente de todas formas (esas solo existen en el Neon
compartido).
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    JSON, Boolean, DateTime, Float, ForeignKey, Integer, String,
    UniqueConstraint, create_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

import config


class Base(DeclarativeBase):
    pass


class LinescoreGame(Base):
    """
    Resultado por entrada de un juego historico -- ground truth que no
    existe en `historical_game` del repo hermano. Base de la Linea 2
    (especializacion por mercado First 5 / Totales).
    """
    __tablename__ = "linescore_game"

    game_pk: Mapped[int] = mapped_column(Integer, primary_key=True)
    game_date: Mapped[str] = mapped_column(String, nullable=False)
    season: Mapped[int] = mapped_column(Integer, nullable=False)

    home_f5_runs: Mapped[int | None] = mapped_column(Integer)
    away_f5_runs: Mapped[int | None] = mapped_column(Integer)
    # 'home' / 'away' / 'tie' -- empate es un resultado valido en F5 (el
    # juego sigue), a diferencia del ganador del juego completo.
    home_f5_result: Mapped[str | None] = mapped_column(String)

    home_total_runs: Mapped[int | None] = mapped_column(Integer)
    away_total_runs: Mapped[int | None] = mapped_column(Integer)

    # Linescore completo tal como lo devolvio la API, sin recortar --
    # conserva la posibilidad de granularidad Early/Middle/Late Game
    # futura sin tener que re-ingerir.
    innings_raw: Mapped[dict | None] = mapped_column(JSON)

    source: Mapped[str] = mapped_column(String, default="mlb_stats_api_linescore")
    ingested_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )


class HandednessSplitSnapshot(Base):
    """
    Split de bateo de un equipo vs. una mano de lanzador, congelado
    point-in-time (a la fecha de captura, no acumulado a hoy) -- insumo
    de la Linea 1 (matchup pitcher-vs-lineup por mano).
    """
    __tablename__ = "handedness_split_snapshot"
    __table_args__ = (
        UniqueConstraint("team_id", "as_of_date", "vs_hand", name="uq_split_team_date_hand"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    team_id: Mapped[int] = mapped_column(Integer, nullable=False)
    as_of_date: Mapped[str] = mapped_column(String, nullable=False)
    season: Mapped[int] = mapped_column(Integer, nullable=False)
    vs_hand: Mapped[str] = mapped_column(String, nullable=False)  # 'L' o 'R'

    ops: Mapped[float | None] = mapped_column(Float)
    obp: Mapped[float | None] = mapped_column(Float)
    slg: Mapped[float | None] = mapped_column(Float)
    plate_appearances: Mapped[int | None] = mapped_column(Integer)

    source: Mapped[str] = mapped_column(String, default="mlb_stats_api_sitcodes")
    ingested_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )


class ChaseRateSnapshot(Base):
    """
    Chase rate de un equipo (ofensiva), congelado point-in-time -- % de
    pitches FUERA de zona a los que el equipo le tira, acumulado
    UNICAMENTE con juegos anteriores a `as_of_date` (nunca incluye el
    propio dia). Insumo de la Linea 1, componente pendiente de
    "Chase Rate" -- ver docs/data_source_design.md.
    """
    __tablename__ = "chase_rate_snapshot"
    __table_args__ = (
        UniqueConstraint("team_id", "as_of_date", name="uq_chase_team_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    team_id: Mapped[int] = mapped_column(Integer, nullable=False)
    as_of_date: Mapped[str] = mapped_column(String, nullable=False)
    season: Mapped[int] = mapped_column(Integer, nullable=False)

    chase_rate: Mapped[float | None] = mapped_column(Float)
    pitches_out_zone_seen: Mapped[int] = mapped_column(Integer, default=0)
    swings_out_zone: Mapped[int] = mapped_column(Integer, default=0)

    source: Mapped[str] = mapped_column(String, default="mlb_stats_api_playbyplay")
    ingested_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )


class CloserEraSnapshot(Base):
    """
    ERA especifico del cerrador de un equipo, congelado point-in-time --
    `jsa/historical/point_in_time_provider.py::bullpen_era_as_of()` YA
    calcula esto internamente (roster + stats por pitcher, identifica al
    cerrador via most saves) pero lo descarta despues de derivar solo
    `closer_available` (bool) -- ver docs/data_source_design.md,
    "Resultado real de M3". Reconstruido dia por dia desde `gameLog` de
    cada pitcher del roster de temporada completa (Camino 2 -- nunca le
    pide a la API un corte point-in-time directo).
    """
    __tablename__ = "closer_era_snapshot"
    __table_args__ = (
        UniqueConstraint("team_id", "as_of_date", name="uq_closer_team_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    team_id: Mapped[int] = mapped_column(Integer, nullable=False)
    as_of_date: Mapped[str] = mapped_column(String, nullable=False)
    season: Mapped[int] = mapped_column(Integer, nullable=False)

    closer_pitcher_id: Mapped[int | None] = mapped_column(Integer)
    closer_era: Mapped[float | None] = mapped_column(Float)
    closer_ip: Mapped[float] = mapped_column(Float, default=0.0)
    closer_saves: Mapped[int] = mapped_column(Integer, default=0)

    source: Mapped[str] = mapped_column(String, default="mlb_stats_api_gamelog")
    ingested_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )


class ParkFactor(Base):
    """
    Park factor por equipo (1 parque = 1 team_id), calculado desde
    `historical_game` -- ver analysis/park_factor.py. Insumo de las
    formulas ADOPTADAS (T1b, F1) para proyecciones en vivo. No
    point-in-time -- se recalcula con todo el historico disponible cada
    vez que se corre el script, no hay "fecha de corte" relevante para
    esto (el parque no cambia de temporada a temporada, salvo casos
    raros documentados aparte).
    """
    __tablename__ = "park_factor"

    team_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    park_factor: Mapped[float] = mapped_column(Float, nullable=False)
    seasons_used: Mapped[str] = mapped_column(String, nullable=False)
    games_used: Mapped[int] = mapped_column(Integer, nullable=False)

    source: Mapped[str] = mapped_column(String, default="historical_game_computed")
    computed_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )


class PitcherMatchupFeature(Base):
    """
    Feature point-in-time-safe por juego: OPS del lineup rival contra la
    mano de CADA abridor especifico, listo para cruzar con
    historical_game.winner (via el rol de solo lectura) en un
    candidate audit LOSO.
    """
    __tablename__ = "pitcher_matchup_feature"

    game_pk: Mapped[int] = mapped_column(Integer, primary_key=True)
    game_date: Mapped[str] = mapped_column(String, nullable=False)
    season: Mapped[int] = mapped_column(Integer, nullable=False)

    home_pitcher_id: Mapped[int | None] = mapped_column(Integer)
    away_pitcher_id: Mapped[int | None] = mapped_column(Integer)
    home_pitcher_throws: Mapped[str | None] = mapped_column(String)
    away_pitcher_throws: Mapped[str | None] = mapped_column(String)

    # OPS del lineup HOME contra la mano del abridor AWAY, y viceversa.
    home_lineup_ops_vs_away_hand: Mapped[float | None] = mapped_column(Float)
    away_lineup_ops_vs_home_hand: Mapped[float | None] = mapped_column(Float)

    computed_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )


class CandidateAuditResult(Base):
    """
    Resultado de un candidate audit LOSO + bootstrap -- mismo esquema de
    decision que jsa/historical/*_candidate_audit.py, para que un futuro
    cross_model pueda leerlo con el mismo criterio.
    """
    __tablename__ = "candidate_audit_result"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(String, nullable=False)
    hypothesis_name: Mapped[str] = mapped_column(String, nullable=False)
    target: Mapped[str] = mapped_column(String, nullable=False)  # ej. "moneyline", "first5", "totals"

    n_games: Mapped[int] = mapped_column(Integer, nullable=False)
    coverage_pct: Mapped[float] = mapped_column(Float, nullable=False)
    auc: Mapped[float | None] = mapped_column(Float)

    delta_brier_mean: Mapped[float] = mapped_column(Float, nullable=False)
    ci_low: Mapped[float] = mapped_column(Float, nullable=False)
    ci_high: Mapped[float] = mapped_column(Float, nullable=False)
    significant: Mapped[bool] = mapped_column(Boolean, nullable=False)
    effect_size_ok: Mapped[bool] = mapped_column(Boolean, nullable=False)
    meets_all_3_conditions: Mapped[bool] = mapped_column(Boolean, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )


def _resolve_url() -> str:
    return config.JSA_SHARED_DATABASE_URL or "sqlite:///team_strength.db"


def _build_engine():
    url = _resolve_url()
    if url.startswith("sqlite"):
        # SQLite no tiene el concepto de schema de Postgres -- las tablas
        # propias simplemente viven en el unico namespace del archivo .db.
        return create_engine(url)

    # No confiar en `ALTER ROLE ... SET search_path` del lado del servidor:
    # Neon conecta via un pooler estilo PgBouncer, que no siempre reaplica
    # el rolconfig por sesion logica (confirmado en produccion 2026-07-20 --
    # el rolconfig quedo guardado pero `SHOW search_path` seguia devolviendo
    # el default de Postgres). `schema_translate_map` reescribe cada
    # referencia de tabla SIN schema calificado (todos los modelos de este
    # archivo) a `team_strength.<tabla>` en tiempo de compilacion del SQL,
    # del lado del cliente -- funciona sin importar el pooling ni el estado
    # de sesion del servidor.
    return create_engine(url, execution_options={"schema_translate_map": {None: "team_strength"}})


engine = _build_engine()
SessionLocal = sessionmaker(bind=engine)


def init_db() -> None:
    """Crea las tablas propias si no existen. Nunca toca el historico compartido."""
    Base.metadata.create_all(engine)


if __name__ == "__main__":
    init_db()
    print(f"Tablas creadas en {_resolve_url()}")
