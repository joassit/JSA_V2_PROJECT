"""
Dashboard HTML estatico con las proyecciones del dia -- pedido explicito
del usuario, 2026-07-22 ("Dale con el 1" / "Dale, es publico, arma el
dashboard"), para exponer `scripts/build_live_projections.py` de forma
navegable en vez de solo persistida en `live_projection`.

Publicado en GitHub Pages (repo publico -- confirmado explicitamente con
el usuario) tras cada corrida del cron
(.github/workflows/build_live_projections.yml). No lee la base de
datos -- recibe los mismos `results` que ya arma el orquestador en esa
misma corrida, evitando una fila de esquema nueva solo para nombres de
equipo/pitcher/estadio (que la API de calendario ya trae, ver
data_sources/mlb_api.py::parse_schedule_games()).
"""

from __future__ import annotations

import html
from datetime import datetime, timezone

DOCS_URL = "https://github.com/joassit/JSA_V2_PROJECT/blob/main/docs/data_source_design.md"


def _pct(p: float | None) -> str:
    return f"{p * 100:.1f}%" if p is not None else "--"


def _row(r: dict) -> str:
    away = html.escape(r.get("away_team_name") or f"Team {r['away_team_id']}")
    home = html.escape(r.get("home_team_name") or f"Team {r['home_team_id']}")
    away_pitcher = html.escape(r.get("away_pitcher_name") or "?")
    home_pitcher = html.escape(r.get("home_pitcher_name") or "?")
    venue = html.escape(r.get("venue_name") or "?")
    temp = f"{r['temp_f_forecast']:.0f}°F" if r.get("temp_f_forecast") is not None else "--"
    return (
        "<tr>"
        f"<td>{away} @ {home}</td>"
        f"<td>{away_pitcher} vs {home_pitcher}</td>"
        f"<td>{venue}</td>"
        f"<td>{temp}</td>"
        f"<td>{_pct(r.get('totals_over_prob'))}</td>"
        f"<td>{_pct(r.get('totals_over_prob_weather_adjusted'))}</td>"
        f"<td>{_pct(r.get('first5_home_win_prob'))}</td>"
        f"<td>{_pct(r.get('moneyline_home_win_prob'))}</td>"
        f"<td>{_pct(r.get('runline_home_covers_prob'))}</td>"
        "</tr>"
    )


def render_dashboard(results: list[dict], target_date: str) -> str:
    """HTML estatico de una sola pagina -- una tabla con las 5
    probabilidades adoptadas (T1b, Weather1, F1-Platt, ML1b, RL1-Platt)
    por cada juego del dia. Sin JS, sin dependencias externas."""
    rows = "".join(_row(r) for r in results) or '<tr><td colspan="9">Sin juegos programados.</td></tr>'
    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    return f"""<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<title>JSA_V2 -- Proyecciones {html.escape(target_date)}</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
  :root {{ color-scheme: light dark; }}
  body {{ font-family: -apple-system, system-ui, sans-serif; max-width: 1100px; margin: 2rem auto; padding: 0 1rem; }}
  h1 {{ font-size: 1.4rem; margin-bottom: 0.25rem; }}
  .meta {{ color: #767676; font-size: 0.85rem; margin-bottom: 1.5rem; }}
  .meta a {{ color: inherit; }}
  .overflow {{ overflow-x: auto; }}
  table {{ border-collapse: collapse; width: 100%; font-size: 0.9rem; }}
  th, td {{ padding: 0.5rem 0.6rem; text-align: left; border-bottom: 1px solid #8883; white-space: nowrap; }}
  th {{ font-weight: 600; }}
  .warn {{ color: #b45309; font-size: 0.8rem; margin-top: 2rem; }}
</style>
</head>
<body>
  <h1>JSA_V2_PROJECT -- Proyecciones en vivo, {html.escape(target_date)}</h1>
  <p class="meta">Generado {generated_at} por el pipeline automatizado (cron
  diario). Formulas validadas con LOSO+bootstrap sobre 5 temporadas
  historicas -- ver <a href="{DOCS_URL}">docs/data_source_design.md</a>.</p>
  <div class="overflow">
  <table>
    <thead><tr>
      <th>Juego</th><th>Abridores</th><th>Estadio</th><th>Clima (pron.)</th>
      <th>Over 8.5 (T1b)</th><th>Over 8.5 + clima</th>
      <th>Gana local F5</th><th>Gana local (ML)</th><th>Local cubre -1.5</th>
    </tr></thead>
    <tbody>{rows}</tbody>
  </table>
  </div>
  <p class="warn">Moneyline (ML1b) no vence al mercado real -- ver
  advertencia de alcance en docs/data_source_design.md. Ninguna de estas
  proyecciones es asesoria de apuestas.</p>
</body>
</html>"""
