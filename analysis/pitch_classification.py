"""
Clasificacion pura (sin red, sin DB) de pitches individuales -- insumo
de Chase Rate (Linea 1, componente pendiente). Confirmado en vivo contra
`/game/{gamePk}/playByPlay` (scripts/feasibility_spike_chase_rate.py,
runs 29764754175/29764772385): cada pitch trae `pitchData.strikeZoneTop/
Bottom`, `pitchData.coordinates.pX/pZ` y `details.code`.

Los codigos de `details.code` son un contrato PUBLICO y estable de la
MLB Stats API (documentado ampliamente en el ecosistema open-source de
sabermetria, ej. pybaseball/MLB-StatsAPI) -- a diferencia de sitCodes
combinado con byDateRange, esto NO requiere verificacion adicional en
vivo mas alla de lo que ya confirmo el spike (los codigos vistos en la
muestra real, B/F/S/C/X/*B/D/E/T/W, coinciden exactamente con esta
clasificacion).
"""

from __future__ import annotations

# Ancho medio del home plate (17 pulgadas) + radio de la bola, en pies --
# mismo criterio que usa Statcast/Baseball Savant para "zone".
PLATE_HALF_WIDTH_FT = 0.83

# Pitches donde el bateador SI ofrecio (swing) -- incluye contacto
# (D/E/X = en juego) y no-contacto con intento (S/W swinging strike,
# F/T/L/M/Q/R foul o bunt fallido).
SWING_CODES = frozenset({"S", "W", "F", "L", "M", "T", "Q", "R", "D", "E", "X"})

# Pitches donde el bateador NO ofrecio (take) -- bola, strike cantado,
# hit by pitch, bola intencional, pitchout no ofrecido, automatico.
TAKE_CODES = frozenset({"B", "*B", "C", "H", "I", "P", "V", "AC", "U", "N"})


def classify_pitch(
    px: float | None, pz: float | None, sz_top: float | None, sz_bot: float | None, code: str | None,
) -> tuple[bool, bool] | None:
    """
    Devuelve (fuera_de_zona, es_swing), o None si falta algun dato para
    clasificar (nunca se imputa un pitch no clasificable).
    """
    if px is None or pz is None or sz_top is None or sz_bot is None or code is None:
        return None
    if code not in SWING_CODES and code not in TAKE_CODES:
        return None

    in_zone = (-PLATE_HALF_WIDTH_FT <= px <= PLATE_HALF_WIDTH_FT) and (sz_bot <= pz <= sz_top)
    is_swing = code in SWING_CODES
    return (not in_zone, is_swing)


def extract_game_pitches(payload: dict) -> list[dict]:
    """
    Reduce el playByPlay crudo a una lista de
    {"is_top_inning": bool, "out_of_zone": bool, "is_swing": bool} --
    uno por pitch clasificable (se descartan los que classify_pitch()
    no puede clasificar, nunca se imputan).
    """
    pitches: list[dict] = []
    for play in payload.get("allPlays") or []:
        about = play.get("about") or {}
        is_top = about.get("isTopInning")
        if is_top is None:
            half = about.get("halfInning")
            if half is None:
                continue
            is_top = half == "top"

        for event in play.get("playEvents") or []:
            if not event.get("isPitch"):
                continue
            pitch_data = event.get("pitchData") or {}
            coords = pitch_data.get("coordinates") or {}
            details = event.get("details") or {}
            classified = classify_pitch(
                coords.get("pX"), coords.get("pZ"),
                pitch_data.get("strikeZoneTop"), pitch_data.get("strikeZoneBottom"),
                details.get("code"),
            )
            if classified is None:
                continue
            out_of_zone, is_swing = classified
            pitches.append({"is_top_inning": bool(is_top), "out_of_zone": out_of_zone, "is_swing": is_swing})
    return pitches


def chase_rate_from_counts(swings_out_zone: int, pitches_out_zone_seen: int) -> float | None:
    if pitches_out_zone_seen <= 0:
        return None
    return swings_out_zone / pitches_out_zone_seen
