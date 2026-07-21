"""
Spike de factibilidad para coordenadas de estadios -- necesarias para
pedirle pronostico a Open-Meteo (latitude/longitude, no nombres de
ciudad). Verifica en vivo, ANTES de escribir cualquier mapeo a mano:

1. `/api/v1/teams?sportId=1&hydrate=venue` -- trae venue.id/name por
   equipo, y (a confirmar) si location.defaultCoordinates viene incluido.
2. Si no viene ahi, `/api/v1/venues/{venueId}?hydrate=location` para un
   venue de muestra -- confirma si la API expone coordenadas en algun
   endpoint antes de decidir usar un dataset externo/manual.

No se ingiere ni se persiste nada aqui -- solo lectura, y el resultado
determina COMO se construye analysis/ballpark_locations.py (desde la API
real, no de memoria).
"""

from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests

MLB_API_BASE = "https://statsapi.mlb.com/api/v1"


def main() -> int:
    resp = requests.get(
        f"{MLB_API_BASE}/teams", params={"sportId": 1, "hydrate": "venue"}, timeout=15,
    )
    resp.raise_for_status()
    teams = resp.json().get("teams") or []
    print(f"{len(teams)} equipos encontrados.\n")

    sample_venue_id = None
    for t in teams[:5]:
        venue = t.get("venue") or {}
        print(f"team_id={t.get('id')} name={t.get('name')!r}")
        print(f"  venue_id={venue.get('id')} venue_name={venue.get('name')!r}")
        print(f"  venue keys: {sorted(venue.keys())}")
        if "location" in venue:
            print(f"  venue.location = {json.dumps(venue['location'])}")
        if sample_venue_id is None and venue.get("id"):
            sample_venue_id = venue["id"]
        print()

    if sample_venue_id is None:
        print("ADVERTENCIA: no se encontro ningun venue_id de muestra.")
        return 1

    print(f"=== Probando /venues/{sample_venue_id}?hydrate=location ===")
    resp2 = requests.get(
        f"{MLB_API_BASE}/venues/{sample_venue_id}", params={"hydrate": "location"}, timeout=15,
    )
    resp2.raise_for_status()
    venues = resp2.json().get("venues") or []
    if not venues:
        print("ADVERTENCIA: /venues/{id} no devolvio nada.")
        return 1
    print(json.dumps(venues[0], indent=2))

    has_coords = "defaultCoordinates" in (venues[0].get("location") or {})
    print(f"\n=== CONCLUSION === /venues/{{id}}?hydrate=location "
          f"{'SI' if has_coords else 'NO'} trae defaultCoordinates.")
    return 0 if has_coords else 1


if __name__ == "__main__":
    raise SystemExit(main())
