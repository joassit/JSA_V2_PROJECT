from analysis.dashboard import render_dashboard


def _sample_result(**overrides) -> dict:
    base = {
        "game_pk": 823519, "home_team_id": 147, "away_team_id": 114,
        "home_team_name": "New York Yankees", "away_team_name": "Cleveland Guardians",
        "home_pitcher_name": "Carlos Rodon", "away_pitcher_name": "Tanner Bibee",
        "venue_name": "Yankee Stadium", "temp_f_forecast": 76.5,
        "totals_over_prob": 0.499, "totals_over_prob_weather_adjusted": 0.524,
        "first5_home_win_prob": 0.458, "moneyline_home_win_prob": 0.523,
        "runline_home_covers_prob": 0.376,
    }
    base.update(overrides)
    return base


def test_render_dashboard_includes_teams_and_percentages():
    html = render_dashboard([_sample_result()], "2026-07-22")
    assert "New York Yankees" in html
    assert "Cleveland Guardians" in html
    assert "Yankee Stadium" in html
    assert "52.4%" in html  # totals_over_prob_weather_adjusted
    assert "2026-07-22" in html


def test_render_dashboard_handles_missing_fields_without_crashing():
    result = _sample_result(
        home_team_name=None, venue_name=None, temp_f_forecast=None,
        totals_over_prob_weather_adjusted=None,
    )
    html = render_dashboard([result], "2026-07-22")
    assert "Team 147" in html
    assert "--" in html


def test_render_dashboard_empty_results_shows_no_games_message():
    html = render_dashboard([], "2026-07-22")
    assert "Sin juegos programados" in html


def test_render_dashboard_escapes_html_in_names():
    result = _sample_result(home_team_name="<script>alert(1)</script>")
    html = render_dashboard([result], "2026-07-22")
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html
