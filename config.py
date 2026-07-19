"""
Configuracion central de JSA_V2_PROJECT.

Aislamiento deliberado (ver docs/scope_handoff.md): DOS conexiones de
base de datos distintas, nunca la misma.
"""

import os

# MLB Stats API -- misma API oficial gratuita que ya usa el resto del
# ecosistema (mlb_edge_analyzer.v2/jsa). Sin API key.
MLB_API_BASE = "https://statsapi.mlb.com/api/v1"

# Temporadas cubiertas por el historico ya validado en jsa/ (13,101
# juegos). Cualquier ingesta de este proyecto debe restringirse a este
# rango para poder cruzar por game_pk contra historical_game/
# historical_snapshot.
HISTORICAL_SEASONS = list(range(2022, 2027))

# --- Base de datos PROPIA (lectura + escritura) ---
# linescore_game, handedness_split_snapshot, pitcher_matchup_feature,
# candidate_audit_result -- nunca las tablas del historico compartido.
TEAM_STRENGTH_DATABASE_URL = os.getenv("TEAM_STRENGTH_DATABASE_URL")

# --- Base de datos del historico compartido (SOLO LECTURA) ---
# Rol de Postgres de solo lectura sobre historical_game/
# historical_snapshot/historical_statcast_event del repo hermano
# mlb_edge_analyzer.v2 (jsa/). Ver docs/scope_handoff.md, seccion
# "Acceso a datos", para el procedimiento de creacion del rol en Neon.
# Nunca debe apuntar a la misma connection string que usa la ingesta
# real de jsa/ (JSA_HISTORICAL_DATABASE_URL, sin _READONLY) -- ese
# secret no existe en este repo a proposito.
JSA_HISTORICAL_DATABASE_URL_READONLY = os.getenv("JSA_HISTORICAL_DATABASE_URL_READONLY")

# Tablas a las que este proyecto tiene permiso de LECTURA en el
# historico compartido -- lista blanca explicita, ver
# data_sources/historical_readonly.py (nunca se construye SQL con
# nombres de tabla fuera de esta lista).
READONLY_ALLOWED_TABLES = frozenset({
    "historical_game",
    "historical_snapshot",
    "historical_statcast_event",
})

# --- Protocolo de validacion (docs/scope_handoff.md) ---
BOOTSTRAP_RESAMPLES = 500
MIN_EFFECT_SIZE_DELTA_BRIER = 0.001
