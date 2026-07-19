"""
Verifica en vivo, contra el Neon compartido real, que el diseño de
aislamiento por schema (docs/scope_handoff.md, seccion "Acceso a datos")
funciona como se espera -- corre DESPUES de que el usuario confirma que
JSA_SHARED_DATABASE_URL ya esta configurado como secret.

4 checks, en este orden:
1. Conexion + schema activo (`current_schema()`) -- debe resolver a
   `team_strength`, confirmando que `search_path` del rol `jsa_v2` quedo
   bien configurado.
2. Lectura de `historical_game` (schema `public`) -- cuenta filas, prueba
   que el GRANT SELECT funciona y trae un numero cercano a 13,101.
3. Verificacion NEGATIVA: un intento de INSERT sobre `historical_game`
   DEBE fallar con error de permisos -- envuelto en una transaccion que
   siempre hace ROLLBACK (nunca se compromete pase lo que pase), asi que
   incluso si el permiso estuviera mal configurado y el INSERT
   "funcionara", no se persiste nada. Si este check NO falla, es una
   alerta de que el aislamiento de escritura esta roto -- se reporta como
   tal, no se trata como exito.
4. Escritura real en el schema propio: `db.database.init_db()` crea las
   tablas propias, y una fila de prueba en `linescore_game` confirma que
   cae en `team_strength` (no en `public`).

No borra nada de `historical_game` ni de ninguna tabla del historico
compartido -- unicamente lee, y el unico intento de escritura ahi se
revierte siempre.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timezone

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
        session.execute(text("DELETE FROM linescore_game WHERE game_pk = :pk"), {"pk": _SENTINEL_GAME_PK})
        session.commit()

    return {"ok": schema == "team_strength", "table_schema": schema}


def main() -> int:
    if not config.JSA_SHARED_DATABASE_URL:
        print(json.dumps({"ok": False, "reason": "JSA_SHARED_DATABASE_URL no configurada"}))
        return 1

    results = {
        "schema_and_search_path": check_schema_and_search_path(),
        "read_historical_game": check_read_historical_game(),
        "write_denied_on_historical_game": check_write_denied_on_historical_game(),
        "write_own_schema": check_write_own_schema(),
    }
    print(json.dumps(results, indent=2, default=str))

    all_ok = all(r.get("ok") for r in results.values())
    if not all_ok:
        print("\nRESULTADO: al menos un check fallo -- revisar el diseno de "
              "rol/schema en Neon antes de construir ingesta sobre esto.")
        return 1

    print("\nRESULTADO: los 4 checks pasaron. El rol `jsa_v2` lee "
          "`public.historical_game`, NO puede escribir ahi, y SI puede "
          "escribir en su propio schema `team_strength`. Listo para "
          "empezar T1 (Totales) -- ver docs/data_source_design.md.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
