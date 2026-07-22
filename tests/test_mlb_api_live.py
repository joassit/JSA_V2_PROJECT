from data_sources.mlb_api import (
    parse_era_ip_from_season_stats,
    parse_ops_from_season_stats,
    parse_schedule_games,
    parse_venue_coordinates,
    parse_weather,
)


def test_parse_schedule_games_extracts_teams_and_probables():
    payload = {
        "dates": [
            {
                "games": [
                    {
                        "gamePk": 123,
                        "teams": {
                            "home": {
                                "team": {"id": 142, "name": "Minnesota Twins"},
                                "probablePitcher": {"id": 800048, "fullName": "Parker Messick"},
                            },
                            "away": {
                                "team": {"id": 114, "name": "Cleveland Guardians"},
                                "probablePitcher": {"id": 999, "fullName": "Tanner Bibee"},
                            },
                        },
                        "venue": {"id": 5, "name": "Target Field"},
                    }
                ]
            }
        ]
    }
    games = parse_schedule_games(payload)
    assert games == [{
        "game_pk": 123, "home_team_id": 142, "away_team_id": 114,
        "home_pitcher_id": 800048, "away_pitcher_id": 999, "venue_id": 5,
        "home_team_name": "Minnesota Twins", "away_team_name": "Cleveland Guardians",
        "home_pitcher_name": "Parker Messick", "away_pitcher_name": "Tanner Bibee",
        "venue_name": "Target Field",
    }]


def test_parse_schedule_games_skips_games_without_team_id():
    payload = {"dates": [{"games": [{"gamePk": 1, "teams": {}}]}]}
    assert parse_schedule_games(payload) == []


def test_parse_schedule_games_allows_missing_probable_pitcher():
    # Un abridor probable aun no anunciado no debe descartar el juego --
    # solo faltan los ids de pitcher, el equipo si esta confirmado.
    payload = {
        "dates": [{"games": [{
            "gamePk": 5,
            "teams": {
                "home": {"team": {"id": 1}}, "away": {"team": {"id": 2}},
            },
        }]}]
    }
    games = parse_schedule_games(payload)
    assert games == [{
        "game_pk": 5, "home_team_id": 1, "away_team_id": 2,
        "home_pitcher_id": None, "away_pitcher_id": None, "venue_id": None,
        "home_team_name": None, "away_team_name": None,
        "home_pitcher_name": None, "away_pitcher_name": None, "venue_name": None,
    }]


def test_parse_schedule_games_empty_payload():
    assert parse_schedule_games({}) == []


def test_parse_ops_from_season_stats():
    payload = {"stats": [{"splits": [{"stat": {"ops": "0.789"}}]}]}
    assert parse_ops_from_season_stats(payload) == 0.789


def test_parse_ops_from_season_stats_none_without_splits():
    assert parse_ops_from_season_stats({"stats": [{"splits": []}]}) is None
    assert parse_ops_from_season_stats({}) is None


def test_parse_era_ip_from_season_stats():
    payload = {"stats": [{"splits": [{"stat": {"era": "3.45", "inningsPitched": "62.1"}}]}]}
    era, ip = parse_era_ip_from_season_stats(payload)
    assert era == 3.45
    assert ip == 62.0 + 1 / 3


def test_parse_era_ip_from_season_stats_handles_two_thirds():
    payload = {"stats": [{"splits": [{"stat": {"era": "2.00", "inningsPitched": "10.2"}}]}]}
    era, ip = parse_era_ip_from_season_stats(payload)
    assert ip == 10.0 + 2 / 3


def test_parse_era_ip_from_season_stats_none_without_splits():
    assert parse_era_ip_from_season_stats({"stats": [{"splits": []}]}) is None


def test_parse_era_ip_from_season_stats_none_missing_field():
    payload = {"stats": [{"splits": [{"stat": {"era": "3.00"}}]}]}
    assert parse_era_ip_from_season_stats(payload) is None


def test_parse_weather_real_data():
    payload = {"gameData": {"weather": {"condition": "Partly Cloudy", "temp": "78", "wind": "3 mph, In From CF"}}}
    assert parse_weather(payload) == {
        "temp_f": 78.0, "condition": "Partly Cloudy", "wind_raw": "3 mph, In From CF",
    }


def test_parse_weather_empty_dict_is_none():
    # Juego aun no jugado -- gameData.weather={} (confirmado en vivo,
    # scripts/feasibility_spike_weather.py).
    assert parse_weather({"gameData": {"weather": {}}}) is None
    assert parse_weather({"gameData": {}}) is None
    assert parse_weather({}) is None


def test_parse_venue_coordinates_real_data():
    payload = {"venues": [{"location": {"defaultCoordinates": {"latitude": 38.57994, "longitude": -121.51246}}}]}
    assert parse_venue_coordinates(payload) == (38.57994, -121.51246)


def test_parse_venue_coordinates_none_without_coordinates():
    assert parse_venue_coordinates({"venues": [{"location": {}}]}) is None
    assert parse_venue_coordinates({"venues": []}) is None
    assert parse_venue_coordinates({}) is None
