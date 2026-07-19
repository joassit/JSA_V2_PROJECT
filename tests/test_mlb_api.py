"""
Tests puros de parseo -- sin red, sin DB. Verifican la logica de
transformacion contra fixtures escritas a mano segun la forma DOCUMENTADA
(no verificada en vivo, ver docs/data_source_design.md) de la API.
"""

from data_sources.mlb_api import parse_linescore, parse_team_hitting_split


def test_parse_linescore_first_5_and_total():
    payload = {
        "innings": [
            {"num": 1, "home": {"runs": 1}, "away": {"runs": 0}},
            {"num": 2, "home": {"runs": 0}, "away": {"runs": 2}},
            {"num": 3, "home": {"runs": 0}, "away": {"runs": 0}},
            {"num": 4, "home": {"runs": 3}, "away": {"runs": 0}},
            {"num": 5, "home": {"runs": 0}, "away": {"runs": 0}},
            {"num": 6, "home": {"runs": 0}, "away": {"runs": 1}},
            # Home gana en la baja de la 9 sin necesitar batear -- sin
            # bloque "away", no debe tratarse como dato faltante.
            {"num": 9, "home": {"runs": 1}},
        ],
    }
    result = parse_linescore(payload)

    assert result["home_f5_runs"] == 4
    assert result["away_f5_runs"] == 2
    assert result["home_f5_result"] == "home"
    assert result["home_total_runs"] == 5
    assert result["away_total_runs"] == 3


def test_parse_linescore_first_5_tie():
    payload = {
        "innings": [
            {"num": i, "home": {"runs": 1 if i == 1 else 0}, "away": {"runs": 1 if i == 3 else 0}}
            for i in range(1, 6)
        ],
    }
    result = parse_linescore(payload)
    assert result["home_f5_runs"] == result["away_f5_runs"] == 1
    assert result["home_f5_result"] == "tie"


def test_parse_linescore_missing_innings_returns_none():
    assert parse_linescore({}) is None
    assert parse_linescore({"innings": []}) is None


def test_parse_team_hitting_split_happy_path():
    payload = {
        "stats": [
            {
                "splits": [
                    {"stat": {"ops": ".812", "obp": ".340", "slg": ".472", "plateAppearances": "215"}}
                ]
            }
        ]
    }
    parsed = parse_team_hitting_split(payload)
    assert parsed == {"ops": 0.812, "obp": 0.340, "slg": 0.472, "plate_appearances": 215}


def test_parse_team_hitting_split_no_splits_returns_none():
    assert parse_team_hitting_split({"stats": [{"splits": []}]}) is None


def test_parse_team_hitting_split_malformed_returns_none():
    assert parse_team_hitting_split({"stats": []}) is None
    assert parse_team_hitting_split({}) is None
