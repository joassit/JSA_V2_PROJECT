"""
Spike de factibilidad para clima/temperatura -- posible insumo NUEVO para
T1b/T1-Platt (Totales), ver docs/data_source_design.md. Verifica en vivo,
ANTES de comprometerse a ingerir/consumir nada:

1. `/game/{gamePk}/feed/live` (v1.1) -> `gameData.weather` (temp/
   condition/wind) responde para un juego HISTORICO ya completado --
   insumo necesario para construir el dataset de entrenamiento (13,101
   juegos). PRIMER INTENTO (`/api/v1/game/{gamePk}/boxscore`) confirmo en
   vivo que ESE endpoint especifico NUNCA trae `gameData.weather`
   (siempre None, tanto para juegos completados como futuros) -- error
   de suposicion inicial, corregido aqui probando el endpoint correcto
   (`feed/live`, que es donde MLB Stats API expone el clima real).
2. El mismo campo para un juego FUTURO/programado de hoy -- clave para
   saber si el clima esta disponible ANTES del juego (proyeccion en
   vivo real) o solo DESPUES (util solo para el historico, inutil para
   proyecciones futuras salvo que se integre una API de pronostico
   externa aparte).

No se ingiere ni se persiste nada aqui -- solo lectura, solo para
verificar el contrato real de la API antes de diseñar cualquier ingesta.
"""

from __future__ import annotations

import os
import sys
import time
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests

MLB_API_BASE = "https://statsapi.mlb.com/api/v1"
MLB_API_BASE_V11 = "https://statsapi.mlb.com/api/v1.1"


def _fetch_schedule(target_date: str) -> dict:
    resp = requests.get(
        f"{MLB_API_BASE}/schedule",
        params={"sportId": 1, "date": target_date},
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()


def _fetch_live_feed(game_pk: int) -> dict:
    t0 = time.monotonic()
    resp = requests.get(f"{MLB_API_BASE_V11}/game/{game_pk}/feed/live", timeout=15)
    elapsed = time.monotonic() - t0
    resp.raise_for_status()
    print(f"  feed/live gamePk={game_pk}: status={resp.status_code} elapsed={elapsed:.3f}s")
    return resp.json()


def _print_weather(label: str, feed: dict) -> dict | None:
    """
    Devuelve el dict de clima SOLO si tiene datos reales -- un dict vacio
    ({}) no es None, pero tampoco es clima disponible (bug real
    encontrado en la primera version de este spike: `is not None` daba
    falso positivo con {}). `temp`/`condition` presentes = dato real.
    """
    weather = (feed.get("gameData") or {}).get("weather")
    print(f"  [{label}] gameData.weather = {weather}")
    if not weather or not weather.get("temp"):
        return None
    return weather


def main() -> int:
    today = date.today()

    # --- Parte 1: juego HISTORICO completado (ayer) ---
    yesterday = (today - timedelta(days=1)).isoformat()
    print(f"Buscando calendario de ayer ({yesterday}) para un juego completado...")
    hist_payload = _fetch_schedule(yesterday)
    hist_games = (hist_payload.get("dates") or [{}])[0].get("games") or []
    completed = [g for g in hist_games if (g.get("status") or {}).get("detailedState") == "Final"]
    if not completed:
        print("ADVERTENCIA: no se encontro ningun juego 'Final' de ayer -- "
              "no se pudo verificar el caso historico")
        historical_weather = None
    else:
        game_pk = completed[0]["gamePk"]
        feed = _fetch_live_feed(game_pk)
        historical_weather = _print_weather("HISTORICO (completado)", feed)

    # --- Parte 2: juego FUTURO/programado de hoy ---
    print(f"\nBuscando calendario de hoy ({today.isoformat()}) para un juego programado...")
    today_payload = _fetch_schedule(today.isoformat())
    today_games = (today_payload.get("dates") or [{}])[0].get("games") or []
    scheduled = [g for g in today_games if (g.get("status") or {}).get("detailedState") in ("Scheduled", "Pre-Game")]
    if not scheduled:
        print("ADVERTENCIA: no se encontro ningun juego 'Scheduled'/'Pre-Game' de hoy")
        future_weather = None
    else:
        game_pk = scheduled[0]["gamePk"]
        feed = _fetch_live_feed(game_pk)
        future_weather = _print_weather("FUTURO (programado, aun sin jugar)", feed)

    print("\n=== CONCLUSION ===")
    print(f"Clima disponible para juego historico completado: {historical_weather is not None}")
    print(f"Clima disponible para juego futuro (antes de jugarse): {future_weather is not None}")
    if historical_weather is not None and future_weather is None:
        print("El clima solo esta disponible DESPUES del juego -- sirve para el "
              "dataset de entrenamiento historico, pero NO para proyecciones en "
              "vivo de juegos futuros sin integrar una API de pronostico externa.")
    elif historical_weather is not None and future_weather is not None:
        print("El clima esta disponible ANTES del juego -- factible tambien para "
              "proyecciones en vivo, no solo para el historico.")

    return 0 if historical_weather is not None else 1


if __name__ == "__main__":
    raise SystemExit(main())
