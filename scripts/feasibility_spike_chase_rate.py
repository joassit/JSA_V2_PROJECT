"""
Spike de factibilidad para Chase Rate (Linea 1, componente pendiente --
ver docs/data_source_design.md, "Prioridad recomendada"): confirma en
vivo, ANTES de comprometerse a ingerir nada, que:

1. `/api/v1/game/{gamePk}/playByPlay` responde 200 y trae datos
   pitch-a-pitch (no solo bateos en juego como
   `historical_statcast_event`, que ya ingiere `jsa/`).
2. Cada pitch trae zona de strike (`pitchData.strikeZoneTop/Bottom` +
   coordenadas `pitchData.coordinates.pX/pZ`) para poder clasificar
   "dentro/fuera de zona" nosotros mismos -- MISMO principio que ya
   aprendimos con sitCodes: nunca asumir el contrato de la API sin
   verificarlo en vivo (ver scripts/diagnose_sitcodes_bydaterange.py).
3. Cada pitch trae `details.code`/`description` para clasificar
   swing/take (ej. "Swinging Strike", "Foul", "In play, ..." = swing;
   "Ball", "Called Strike" = take).
4. Costo real por llamada -- 1 llamada por game_pk (13,101 total),
   mismo orden de magnitud que la ingesta de linescore ya hecha
   (13,099/13,101 exitosos, 110.1s con 8 workers).
"""

from __future__ import annotations

import sys
import os
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests

MLB_API_BASE = "https://statsapi.mlb.com/api/v1"

# No se asume un game_pk de memoria (mismo error que casi se repite con
# sitCodes) -- se resuelve un juego real desde /schedule antes de pedir
# playByPlay.
SAMPLE_DATE = "2024-04-10"


def _resolve_sample_game_pk() -> int:
    resp = requests.get(
        f"{MLB_API_BASE}/schedule", params={"sportId": 1, "date": SAMPLE_DATE}, timeout=15
    )
    resp.raise_for_status()
    dates = resp.json().get("dates") or []
    if not dates or not dates[0].get("games"):
        raise RuntimeError(f"Sin juegos en /schedule para {SAMPLE_DATE}")
    return dates[0]["games"][0]["gamePk"]


def main() -> int:
    sample_game_pk = _resolve_sample_game_pk()
    print(f"game_pk real resuelto desde /schedule ({SAMPLE_DATE}): {sample_game_pk}")

    t0 = time.monotonic()
    resp = requests.get(f"{MLB_API_BASE}/game/{sample_game_pk}/playByPlay", timeout=15)
    elapsed = time.monotonic() - t0
    print(f"status={resp.status_code} elapsed={elapsed:.3f}s")
    resp.raise_for_status()
    payload = resp.json()

    all_plays = payload.get("allPlays") or []
    print(f"allPlays: {len(all_plays)} plays")
    if not all_plays:
        print("ADVERTENCIA: allPlays vacio -- forma inesperada")
        return 1

    total_pitches = 0
    sample_pitches = []
    for play in all_plays:
        for event in play.get("playEvents") or []:
            if not event.get("isPitch"):
                continue
            total_pitches += 1
            if len(sample_pitches) < 5:
                sample_pitches.append(event)

    print(f"total de pitches en el juego: {total_pitches}")
    print("\n--- Muestra de 5 pitches (estructura real) ---")
    for i, ev in enumerate(sample_pitches):
        pitch_data = ev.get("pitchData") or {}
        coords = pitch_data.get("coordinates") or {}
        details = ev.get("details") or {}
        print(f"\nPitch {i + 1}:")
        print(f"  strikeZoneTop={pitch_data.get('strikeZoneTop')} strikeZoneBottom={pitch_data.get('strikeZoneBottom')}")
        print(f"  coordinates.pX={coords.get('pX')} coordinates.pZ={coords.get('pZ')}")
        print(f"  details.code={details.get('code')} description={details.get('description')}")
        print(f"  details.isInPlay={details.get('isInPlay')} isStrike={details.get('isStrike')} isBall={details.get('isBall')}")

    # Clasificacion swing/take basada solo en details.code -- confirma si
    # es suficiente sin tener que inferir de description (string libre,
    # menos confiable).
    codes_seen = {}
    for play in all_plays:
        for event in play.get("playEvents") or []:
            if not event.get("isPitch"):
                continue
            code = (event.get("details") or {}).get("code")
            codes_seen[code] = codes_seen.get(code, 0) + 1

    print(f"\n--- Todos los codigos de pitch vistos en el juego (para armar la clasificacion swing/take) ---")
    for code, count in sorted(codes_seen.items(), key=lambda x: -x[1]):
        print(f"  {code}: {count}")

    print(f"\nCosto proyectado: 13,101 llamadas x ~{elapsed:.3f}s = "
          f"~{13101 * elapsed:.0f}s secuencial, ~{13101 * elapsed / 8:.0f}s con 8 workers en paralelo.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
