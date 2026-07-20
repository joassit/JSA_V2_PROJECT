"""
Verifica en vivo, contra el Neon compartido real, que el diseño de
aislamiento por schema (docs/scope_handoff.md, seccion "Acceso a datos")
funciona como se espera -- corre DESPUES de que el usuario confirma que
JSA_SHARED_DATABASE_URL ya esta configurado como secret.

5 checks, en este orden:
1. INFORMATIVO, no bloqueante: `current_schema()`/`search_path` de la
   sesion. Neon conecta via un pooler estilo PgBouncer que no siempre
   reaplica `ALTER ROLE ... SET search_path` por sesion logica (confirmado
   en produccion 2026-07-20 -- el rolconfig quedaba guardado pero
   `SHOW search_path` seguia devolviendo el default) -- por eso
   db/database.py YA NO depende de esto: usa `schema_translate_map` para
   forzar `team_strength.<tabla>` explicitamente en cada query, sin
   importar el estado de la sesion del pooler. Este check se deja solo
   como diagnostico, no afecta el resultado final.
2. Privilegios reales sobre el schema `team_strength` (existencia +
   CREATE + USAGE) -- diagnostico directo, no depende de que un CREATE
   TABLE tenga exito.
3. Lectura de `historical_game` (schema `public`) -- cuenta filas, prueba
   que el GRANT SELECT funciona y trae un numero cercano a 13,101.
4. Verificacion NEGATIVA: un intento de INSERT sobre `historical_game`
   DEBE fallar con error de permisos -- envuelto en una transaccion que
   siempre hace ROLLBACK (nunca se compromete pase lo que pase), asi que
   incluso si el permiso estuviera mal configurado y el INSERT
   "funcionara", no se persiste nada. Si este check NO falla, es una
   alerta de que el aislamiento de escritura esta roto -- se reporta como
   tal, no se trata como exito.
5. Escritura real en el schema propio: `db.database.init_db()` crea las
   tablas propias, y una fila de prueba en `linescore_game` confirma que
   cae en `team_strength` (no en `public`).

No borra nada de `historical_game` ni de ninguna tabla del historico
compartido -- unicamente lee, y el unico intento de escritura ahi se
revierte siempre.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import date, datetime, timezone

# Permite `python scripts/verify_shared_db_access.py` desde cualquier cwd
# -- sin esto, `import config` falla porque Python solo agrega la carpeta
# del script (scripts/) a sys.path, no la raiz del repo donde vive
# config.py. Mismo patron que conftest.py usa para pytest.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

import config
from db.database import LinescoreGame, SessionLocal, init_db

# game_pk claramente falso (nunca puede colisionar con un juego real de
# MLB Stats API) -- solo se usa dentro de una transaccion que siempre se
# revierte.
_SENTINEL_GAME_PK = -999999999


def check_schema_and_search_path() -> dict:
    with SessionLocal() as session:
        current_schema = session.execute(text("SELECT current_schema()")).scalar()
        search_path = session.execute(text("SHOW search_path")).scalar()
    ok = current_schema == "team_strength"
    return {"ok": ok, "current_schema": current_schema, "search_path": search_path}


def check_read_historical_game() -> dict:
    with SessionLocal() as session:
        count = session.execute(text("SELECT COUNT(*) FROM public.historical_game")).scalar()
    return {"ok": count is not None and count > 0, "row_count": count}


def check_write_denied_on_historical_game() -> dict:
    """
    Debe fallar. `ok=True` aqui significa "el permiso de escritura SI
    esta bloqueado" (el resultado deseado) -- no "la escritura tuvo
    exito".
    """
    session = SessionLocal()
    try:
        session.execute(
            text(
                """
                INSERT INTO public.historical_game
                    (recorded_at, season, game_pk, game_date, home_team, away_team,
                     home_team_id, away_team_id, is_double_header)
                VALUES
                    (:recorded_at, 1900, :game_pk, :game_date, 'sentinel', 'sentinel', -1, -1, 0)
                """
            ),
            {
                "recorded_at": datetime.now(timezone.utc),
                "game_pk": _SENTINEL_GAME_PK,
                "game_date": date(1900, 1, 1),
            },
        )
        # Si llegamos aqui, el INSERT no fue rechazado por Postgres --
        # eso es una falla de aislamiento, no un exito. Se revierte de
        # todas formas, sin excepcion.
        return {"ok": False, "reason": "insert_no_fue_rechazado_permiso_mal_configurado"}
    except DBAPIError as e:
        return {"ok": True, "reason": "insert_rechazado_como_se_esperaba", "detail": str(e.orig)[:300]}
    finally:
        session.rollback()
        session.close()


def check_team_strength_schema_privileges() -> dict:
    """
    Diagnostico directo (no depende de que un CREATE TABLE tenga exito):
    ¿existe el schema `team_strength`, y el rol actual tiene CREATE/USAGE
    sobre el? Si esto sale en False, el problema es la configuracion del
    rol/schema en Neon (ver docs/scope_handoff.md), no este codigo.
    """
    with SessionLocal() as session:
        exists = session.execute(
            text("SELECT 1 FROM information_schema.schemata WHERE schema_name = 'team_strength'")
        ).scalar()
        has_create = session.execute(
            text("SELECT has_schema_privilege(current_user, 'team_strength', 'CREATE')")
        ).scalar() if exists else False
        has_usage = session.execute(
            text("SELECT has_schema_privilege(current_user, 'team_strength', 'USAGE')")
        ).scalar() if exists else False
    return {
        "ok": bool(exists) and bool(has_create) and bool(has_usage),
        "schema_exists": bool(exists),
        "has_create": bool(has_create),
        "has_usage": bool(has_usage),
    }


def check_write_own_schema() -> dict:
    init_db()
    with SessionLocal() as session:
        session.merge(LinescoreGame(
            game_pk=_SENTINEL_GAME_PK,
            game_date="1900-01-01",
            season=1900,
            home_f5_runs=0,
            away_f5_runs=0,
            home_f5_result="tie",
            home_total_runs=0,
            away_total_runs=0,
        ))
        session.commit()

        schema = session.execute(
            text(
                "SELECT table_schema FROM information_schema.tables "
                "WHERE table_name = 'linescore_game' LIMIT 1"
            )
        ).scalar()

        # Limpieza: esta fila es solo de verificacion, no un juego real.
        # Via ORM (no text() crudo) -- schema_translate_map SOLO reescribe
        # SQL construido por Core/ORM, nunca texto plano, asi que un
        # `DELETE FROM linescore_game` en texto crudo apuntaria al schema
        # equivocado exactamente por la misma razon que search_path no es
        # confiable (ver check_schema_and_search_path).
        row = session.get(LinescoreGame, _SENTINEL_GAME_PK)
        if row is not None:
            session.delete(row)
        session.commit()

    return {"ok": schema == "team_strength", "table_schema": schema}


# schema_and_search_path es INFORMATIVO -- db/database.py ya no depende
# de search_path (usa schema_translate_map, ver ese archivo), asi que un
# search_path "incorrecto" del lado del pooler ya no bloquea el resultado.
_INFORMATIONAL_CHECKS = [
    ("schema_and_search_path", check_schema_and_search_path),
]
_BLOCKING_CHECKS = [
    ("team_strength_schema_privileges", check_team_strength_schema_privileges),
    ("read_historical_game", check_read_historical_game),
    ("write_denied_on_historical_game", check_write_denied_on_historical_game),
    ("write_own_schema", check_write_own_schema),
]


def main() -> int:
    if not config.JSA_SHARED_DATABASE_URL:
        print(json.dumps({"ok": False, "reason": "JSA_SHARED_DATABASE_URL no configurada"}))
        return 1

    # Cada check corre aislado -- un check que lanza una excepcion NO
    # detiene a los siguientes, y su resultado se reporta como parte del
    # diagnostico en vez de perder toda la corrida (checks posteriores
    # siguen dando informacion util incluso si uno falla).
    results: dict = {}
    for name, check_fn in _INFORMATIONAL_CHECKS + _BLOCKING_CHECKS:
        try:
            results[name] = check_fn()
        except Exception as e:  # noqa: BLE001 -- diagnostico, se reporta, no se oculta
            results[name] = {"ok": False, "exception": f"{type(e).__name__}: {e}"}

    print(json.dumps(results, indent=2, default=str))

    blocking_ok = all(results[name].get("ok") for name, _ in _BLOCKING_CHECKS)
    if not blocking_ok:
        print("\nRESULTADO: al menos un check bloqueante fallo -- revisar el "
              "diseno de rol/schema en Neon antes de construir ingesta sobre esto.")
        return 1

    print("\nRESULTADO: los checks bloqueantes pasaron. El rol `jsa_v2` lee "
          "`public.historical_game`, NO puede escribir ahi, y SI puede "
          "escribir en su propio schema `team_strength` (via "
          "schema_translate_map, sin depender de search_path del pooler). "
          "Listo para empezar T1 (Totales) -- ver docs/data_source_design.md.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
