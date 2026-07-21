"""
Spike de factibilidad para Open-Meteo -- API de pronostico de clima
gratuita, SIN API key, necesaria porque MLB Stats API solo registra
clima real DESPUES de que el juego ocurre (confirmado en vivo,
scripts/feasibility_spike_weather.py) -- inutil para proyecciones de
juegos futuros sin esta fuente externa.

Verifica en vivo, ANTES de comprometerse a integrarla al pipeline:
1. El endpoint responde con pronostico horario de temperatura para una
   ubicacion real (Yankee Stadium) y una fecha real (hoy + mañana).
2. Costo real por llamada.

No se ingiere ni se persiste nada aqui -- solo lectura.
"""

from __future__ import annotations

import os
import sys
import time
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests

OPEN_METEO_BASE = "https://api.open-meteo.com/v1/forecast"

# Yankee Stadium -- coordenadas publicas conocidas, solo para el spike.
TEST_LATITUDE = 40.8296
TEST_LONGITUDE = -73.9262


def _fetch_forecast(target_date: str) -> dict:
    t0 = time.monotonic()
    resp = requests.get(
        OPEN_METEO_BASE,
        params={
            "latitude": TEST_LATITUDE, "longitude": TEST_LONGITUDE,
            "hourly": "temperature_2m", "temperature_unit": "fahrenheit",
            "start_date": target_date, "end_date": target_date,
            "timezone": "auto",
        },
        timeout=15,
    )
    elapsed = time.monotonic() - t0
    resp.raise_for_status()
    print(f"forecast {target_date}: status={resp.status_code} elapsed={elapsed:.3f}s")
    return resp.json()


def main() -> int:
    today = date.today()
    ok = True

    for offset in (0, 1):
        target = (today + timedelta(days=offset)).isoformat()
        payload = _fetch_forecast(target)
        hourly = payload.get("hourly") or {}
        times, temps = hourly.get("time") or [], hourly.get("temperature_2m") or []
        print(f"  {len(times)} horas de pronostico para {target}")

        evening = [(t, temp) for t, temp in zip(times, temps) if t.endswith(("18:00", "19:00", "20:00", "21:00"))]
        print(f"  Horario de primer pitch tipico (18-21h): {evening}")
        if not evening:
            print(f"  ADVERTENCIA: sin datos de pronostico para el horario de primer pitch en {target}")
            ok = False

    print(f"\n=== CONCLUSION === Open-Meteo {'SI' if ok else 'NO'} responde con pronostico usable.")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
