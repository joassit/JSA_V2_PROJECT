"""
Reconstruccion pura (sin red, sin DB) del ERA point-in-time del cerrador
de un equipo -- insumo de M3 (ERA del cerrador). Confirmado en vivo
contra `/people/{id}/stats?stats=gameLog` (scripts/feasibility_spike_closer_era.py):
cada juego trae `date`, `saves`, `earnedRuns`, `inningsPitched`.

`jsa/historical/point_in_time_provider.py::bullpen_era_as_of()` YA
calcula esto (roster + stats por pitcher, identifica al cerrador via
most saves) pero lo descarta despues de derivar solo
`closer_available` (bool). Reconstruir dia-por-dia via gameLog (en vez
de recalcular roster+stats activos cada fecha, como hace
bullpen_era_as_of()) es ~100x mas barato mas no identico: usa el
roster de TEMPORADA COMPLETA como pool de candidatos, no el roster
ACTIVO de cada fecha de corte -- documentado explicitamente en
docs/data_source_design.md.
"""

from __future__ import annotations

from datetime import date


def parse_roster_pitchers(payload: dict) -> list[int]:
    """IDs de pitchers del roster de temporada completa."""
    roster = payload.get("roster") or []
    return [
        p["person"]["id"] for p in roster
        if (p.get("position") or {}).get("abbreviation") == "P" and p.get("person", {}).get("id") is not None
    ]


def parse_game_log_events(payload: dict) -> list[dict]:
    """Reduce el gameLog crudo de un pitcher a una lista ordenada
    cronologicamente de {"date": date, "saves": int, "er": float, "ip": float}."""
    splits = (payload.get("stats") or [{}])[0].get("splits") or []
    events = []
    for sp in splits:
        game_date = sp.get("date")
        stat = sp.get("stat") or {}
        if game_date is None:
            continue
        ip_str = stat.get("inningsPitched")
        ip = _parse_innings(ip_str) if ip_str is not None else 0.0
        events.append({
            "date": date.fromisoformat(game_date),
            "saves": int(stat.get("saves") or 0),
            "er": float(stat.get("earnedRuns") or 0),
            "ip": ip,
        })
    events.sort(key=lambda e: e["date"])
    return events


def _parse_innings(ip_str: str) -> float:
    """'6.1' -> 6 + 1/3, '6.2' -> 6 + 2/3 (notacion de beisbol, no decimal)."""
    whole, _, frac = str(ip_str).partition(".")
    whole_f = float(whole) if whole else 0.0
    thirds = {"0": 0.0, "1": 1 / 3, "2": 2 / 3}.get(frac, 0.0)
    return whole_f + thirds


def reconstruct_closer_snapshots(
    team_dates: list[date], pitcher_game_logs: dict[int, list[dict]],
) -> dict[date, dict]:
    """
    Para cada fecha de corte del equipo (ordenada cronologicamente),
    determina el cerrador ACUMULADO (mas saves de TODOS los pitchers del
    roster hasta ANTES de esa fecha, nunca incluye el propio dia) y su
    ERA/IP/saves acumulados a esa fecha. Recorrido tipo merge (punteros
    por pitcher) -- O(pitchers x eventos + fechas x pitchers).
    """
    cursors = {pid: 0 for pid in pitcher_game_logs}
    cum = {pid: {"saves": 0, "er": 0.0, "ip": 0.0} for pid in pitcher_game_logs}
    result: dict[date, dict] = {}

    for cutoff in sorted(team_dates):
        for pid, log in pitcher_game_logs.items():
            while cursors[pid] < len(log) and log[cursors[pid]]["date"] < cutoff:
                ev = log[cursors[pid]]
                cum[pid]["saves"] += ev["saves"]
                cum[pid]["er"] += ev["er"]
                cum[pid]["ip"] += ev["ip"]
                cursors[pid] += 1

        closer_pid, most_saves = None, 0
        for pid, c in cum.items():
            if c["saves"] > most_saves:
                most_saves = c["saves"]
                closer_pid = pid

        if closer_pid is not None and cum[closer_pid]["ip"] > 0:
            era = (cum[closer_pid]["er"] * 9) / cum[closer_pid]["ip"]
            ip = cum[closer_pid]["ip"]
        else:
            era = None
            ip = 0.0

        result[cutoff] = {
            "closer_pitcher_id": closer_pid, "closer_era": era,
            "closer_ip": ip, "closer_saves": most_saves,
        }
    return result
