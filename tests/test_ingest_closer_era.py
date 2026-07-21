import importlib.util
import sys
from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from db.database import Base, CloserEraSnapshot

_spec = importlib.util.spec_from_file_location(
    "ingest_closer_era_module",
    __file__.replace("tests/test_ingest_closer_era.py", "scripts/ingest_closer_era.py"),
)
mod = importlib.util.module_from_spec(_spec)
sys.modules["ingest_closer_era_module"] = mod
_spec.loader.exec_module(mod)


@pytest.fixture()
def memory_session_local(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session_local = sessionmaker(bind=engine)
    monkeypatch.setattr(mod, "SessionLocal", session_local)
    return session_local


def _games():
    return [
        {"game_pk": 1, "game_date": date(2024, 4, 10), "season": 2024,
         "home_team_id": 100, "away_team_id": 200, "home_pitcher_id": None,
         "away_pitcher_id": None, "home_score": 3, "away_score": 1, "winner": "home"},
        {"game_pk": 2, "game_date": date(2024, 4, 15), "season": 2024,
         "home_team_id": 100, "away_team_id": 200, "home_pitcher_id": None,
         "away_pitcher_id": None, "home_score": 2, "away_score": 4, "winner": "away"},
    ]


_ROSTER_PAYLOAD = {"roster": [{"person": {"id": 1}, "position": {"abbreviation": "P"}}]}
_GAMELOG_WITH_SAVE = {
    "stats": [{"splits": [{"date": "2024-04-10", "stat": {"saves": 1, "earnedRuns": 1, "inningsPitched": "1.0"}}]}],
}


def _patch_common(monkeypatch, rosters: dict[int, dict | None], gamelogs: dict[int, dict | None]):
    monkeypatch.setattr(mod, "get_games_for_season", lambda season: _games())
    roster_calls, gamelog_calls = [], []

    def fake_roster(team_id, season):
        roster_calls.append(team_id)
        return rosters.get(team_id)

    def fake_gamelog(pitcher_id, season):
        gamelog_calls.append(pitcher_id)
        return gamelogs.get(pitcher_id)

    monkeypatch.setattr(mod, "get_team_roster_full_season", fake_roster)
    monkeypatch.setattr(mod, "get_pitcher_game_log", fake_gamelog)
    return roster_calls, gamelog_calls


def test_point_in_time_closer_era_reflects_only_prior_games(monkeypatch, memory_session_local):
    _patch_common(
        monkeypatch,
        rosters={100: _ROSTER_PAYLOAD, 200: _ROSTER_PAYLOAD},
        gamelogs={1: _GAMELOG_WITH_SAVE},
    )

    mod.ingest_season(2024)

    with memory_session_local() as session:
        rows = {(r.team_id, r.as_of_date): r for r in session.query(CloserEraSnapshot).filter_by(team_id=100).all()}

    # Antes del primer juego: sin cerrador identificado todavia.
    assert rows[(100, "2024-04-10")].closer_pitcher_id is None
    # Despues del primer juego (que incluyo el save): cerrador identificado, ERA=9.0.
    assert rows[(100, "2024-04-15")].closer_pitcher_id == 1
    assert rows[(100, "2024-04-15")].closer_era == pytest.approx(9.0)


def test_one_roster_call_per_team_not_per_date(monkeypatch, memory_session_local):
    roster_calls, gamelog_calls = _patch_common(
        monkeypatch,
        rosters={100: _ROSTER_PAYLOAD, 200: _ROSTER_PAYLOAD},
        gamelogs={1: _GAMELOG_WITH_SAVE},
    )

    mod.ingest_season(2024)

    # 1 roster call por equipo (2 equipos), no por fecha.
    assert sorted(roster_calls) == [100, 200]


def test_roster_fetch_error_recorded_without_crashing(monkeypatch, memory_session_local):
    _patch_common(monkeypatch, rosters={}, gamelogs={})

    result = mod.ingest_season(2024)
    assert result["roster_fetch_errors"] == 2
    assert result["snapshots_written"] == 0


def test_skips_teams_already_done_without_force(monkeypatch, memory_session_local):
    _patch_common(
        monkeypatch,
        rosters={100: _ROSTER_PAYLOAD, 200: _ROSTER_PAYLOAD},
        gamelogs={1: _GAMELOG_WITH_SAVE},
    )

    first = mod.ingest_season(2024)
    assert first["teams_processed"] == 2

    second = mod.ingest_season(2024)
    assert second["teams_processed"] == 0
    assert second["teams_skipped_already_done"] == 2

    third = mod.ingest_season(2024, force=True)
    assert third["teams_processed"] == 2
