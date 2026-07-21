from datetime import date

import pytest

from analysis.closer_reconstruction import (
    parse_game_log_events, parse_roster_pitchers, reconstruct_closer_snapshots,
)


def test_parse_roster_pitchers_filters_by_position():
    payload = {
        "roster": [
            {"person": {"id": 1}, "position": {"abbreviation": "P"}},
            {"person": {"id": 2}, "position": {"abbreviation": "C"}},
            {"person": {"id": 3}, "position": {"abbreviation": "P"}},
        ],
    }
    assert parse_roster_pitchers(payload) == [1, 3]


def test_parse_game_log_events_sorted_chronologically():
    payload = {
        "stats": [{
            "splits": [
                {"date": "2024-04-15", "stat": {"saves": 1, "earnedRuns": 0, "inningsPitched": "1.0"}},
                {"date": "2024-04-10", "stat": {"saves": 0, "earnedRuns": 2, "inningsPitched": "0.2"}},
            ],
        }],
    }
    events = parse_game_log_events(payload)
    assert [e["date"] for e in events] == [date(2024, 4, 10), date(2024, 4, 15)]
    assert events[0]["saves"] == 0
    assert events[0]["er"] == 2.0
    assert events[0]["ip"] == pytest.approx(2 / 3)
    assert events[1]["saves"] == 1


def test_reconstruct_closer_snapshots_point_in_time_before_first_save():
    # Pitcher 1 consigue su primer save el 2024-04-10 (2 IP, 1 ER).
    logs = {1: [{"date": date(2024, 4, 10), "saves": 1, "er": 1.0, "ip": 1.0}]}
    team_dates = [date(2024, 4, 10), date(2024, 4, 15)]

    snapshots = reconstruct_closer_snapshots(team_dates, logs)

    # Antes del primer save: sin cerrador identificado todavia.
    assert snapshots[date(2024, 4, 10)]["closer_pitcher_id"] is None
    assert snapshots[date(2024, 4, 10)]["closer_era"] is None

    # Despues: pitcher 1 ya es el cerrador (unico con saves), ERA=9.0.
    snap_15 = snapshots[date(2024, 4, 15)]
    assert snap_15["closer_pitcher_id"] == 1
    assert snap_15["closer_era"] == pytest.approx(9.0)
    assert snap_15["closer_saves"] == 1


def test_reconstruct_closer_snapshots_picks_most_saves():
    logs = {
        1: [{"date": date(2024, 4, 1), "saves": 1, "er": 1.0, "ip": 1.0}],
        2: [
            {"date": date(2024, 4, 1), "saves": 1, "er": 0.0, "ip": 1.0},
            {"date": date(2024, 4, 5), "saves": 1, "er": 0.0, "ip": 1.0},
        ],
    }
    team_dates = [date(2024, 4, 10)]
    snapshots = reconstruct_closer_snapshots(team_dates, logs)
    # Pitcher 2 tiene 2 saves acumulados vs 1 de pitcher 1 -- gana pitcher 2.
    assert snapshots[date(2024, 4, 10)]["closer_pitcher_id"] == 2
    assert snapshots[date(2024, 4, 10)]["closer_saves"] == 2
