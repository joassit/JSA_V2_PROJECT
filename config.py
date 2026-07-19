"""
Configuracion central de JSA_V2_PROJECT.

Aislamiento deliberado (ver docs/scope_handoff.md, seccion "Acceso a
datos" -- revision 2026-07-19: un solo Neon compartido, aislamiento por
SCHEMA de Postgres, no por proyecto/secret separado): UNA sola connection
string (`JSA_SHARED_DATABASE_URL`), pero el rol de Postgres detras de esa
URL (`jsa_v2`) solo tiene SELECT en `public` (tablas historicas de jsa/) y
lectura+escritura exclusiva en su propio schema `team_strength` (via
`ALTER ROLE jsa_v2 SET search_path = team_strength, public`). El
aislamiento de escritura es un permiso real de Postgres, no una
convencion de codigo -- este modulo NO decide que schema se usa, eso ya
lo fija el rol al conectarse.
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

# --- Unico secret de base de datos: mismo Neon que jsa/, rol propio de esta rama ---
# Lee/escribe con el rol `jsa_v2` (ver docs/scope_handoff.md): SELECT en
# `public.historical_game`/`historical_snapshot`/`historical_statcast_event`
# (schema de jsa/, compartido) + lectura/escritura total en su propio
# schema `team_strength` (linescore_game, handedness_split_snapshot,
# pitcher_matchup_feature, candidate_audit_result). Nunca la connection
# string de escritura de jsa/ (`JSA_HISTORICAL_DATABASE_URL`) -- ese
# secret no existe en este repo a proposito.
JSA_SHARED_DATABASE_URL = os.getenv("JSA_SHARED_DATABASE_URL")

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
