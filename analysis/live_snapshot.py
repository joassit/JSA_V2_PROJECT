"""
Logica pura (sin red) para armar el payload de un juego FUTURO --
proyecciones en vivo, ver docs/data_source_design.md, "Proyecciones en
vivo". Distinto de todo lo point-in-time historico: "hoy" ya es el
corte, no hace falta reconstruir nada dia por dia.
"""

from __future__ import annotations


def aggregate_bullpen_era(pitcher_era_ip: list[tuple[float, float]]) -> float | None:
    """ERA de equipo ponderado por IP -- mismo criterio que
    `bullpen_era_as_of()` de jsa/ (promedio ponderado, no simple), pero
    sobre el roster ACTIVO de hoy en vez de un roster point-in-time
    historico. None si no hay IP acumulado."""
    total_ip = sum(ip for _, ip in pitcher_era_ip if ip > 0)
    if total_ip <= 0:
        return None
    weighted = sum(era * ip for era, ip in pitcher_era_ip if ip > 0)
    return weighted / total_ip


def _avg(values: list[float | None]) -> float | None:
    clean = [v for v in values if v is not None]
    return sum(clean) / len(clean) if clean else None


def compute_league_averages(
    team_ops_values: list[float | None], team_era_values: list[float | None],
) -> dict:
    """
    Promedio simple sobre los equipos disponibles en la corrida actual
    (tipicamente los equipos que juegan hoy, no las 30 franquicias) --
    aproximacion documentada explicitamente, no un promedio de liga
    completo. Si no hay suficientes datos, las formulas adoptadas ya
    caen a sus propias constantes de respaldo (LEAGUE_AVG_ERA,
    LEAGUE_OPS_FALLBACK, LEAGUE_AVG_RUNS_PER_GAME en
    totals_candidate_audit.py) -- este calculo solo mejora sobre ese
    respaldo cuando hay datos reales disponibles.
    """
    return {
        "league_avg_ops": _avg(team_ops_values),
        "league_avg_era": _avg(team_era_values),
    }
