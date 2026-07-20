import importlib.util
import sys
from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from db.database import Base, ChaseRateSnapshot

_spec = importlib.util.spec_from_file_location(
    "ingest_chase_rate_module",
    __file__.replace("tests/test_ingest_chase_rate.py", "scripts/ingest_chase_rate.py"),
)
mod = importlib.util.module_from_spec(_spec)
sys.modules["ingest_chase_rate_module"] = mod
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


def _payload_for_game_1():
    # Top inning (equipo 200 batea): 1 pitch fuera de zona con swing (chase).
    # Bottom inning (equipo 100 batea): 1 pitch fuera de zona sin swing (take).
    return {
        "allPlays": [
            {
                "about": {"isTopInning": True},
                "playEvents": [{
                    "isPitch": True,
                    "pitchData": {"strikeZoneTop": 3.5, "strikeZoneBottom": 1.5, "coordinates": {"pX": 1.5, "pZ": 2.3}},
                    "details": {"code": "S"},
                }],
            },
            {
                "about": {"isTopInning": False},
                "playEvents": [{
                    "isPitch": True,
                    "pitchData": {"strikeZoneTop": 3.5, "strikeZoneBottom": 1.5, "coordinates": {"pX": -1.5, "pZ": 2.3}},
                    "details": {"code": "B"},
                }],
            },
        ],
    }


def _patch_common(monkeypatch, payloads: dict[int, dict | None]):
    monkeypatch.setattr(mod, "get_games_for_season", lambda season: _games())
    calls = []

    def fake_get_pbp(game_pk):
        calls.append(game_pk)
        return payloads.get(game_pk)

    monkeypatch.setattr(mod, "get_game_play_by_play", fake_get_pbp)
    return calls


def test_point_in_time_chase_rate_reflects_only_prior_games(monkeypatch, memory_session_local):
    payloads = {1: _payload_for_game_1(), 2: _payload_for_game_1()}
    _patch_common(monkeypatch, payloads)

    mod.ingest_season(2024)

    with memory_session_local() as session:
        rows = {(r.team_id, r.as_of_date): r for r in session.query(ChaseRateSnapshot).all()}

    # Antes del primer juego: sin muestra todavia para ningun equipo.
    assert rows[(100, "2024-04-10")].chase_rate is None
    assert rows[(200, "2024-04-10")].chase_rate is None

    # Antes del segundo juego: el equipo 200 (away, top inning) ya vio 1
    # pitch fuera de zona con swing -> chase_rate=1.0. El equipo 100
    # (home, bottom inning) vio 1 pitch fuera de zona sin swing -> 0.0.
    assert rows[(200, "2024-04-15")].chase_rate == pytest.approx(1.0)
    assert rows[(100, "2024-04-15")].chase_rate == pytest.approx(0.0)


def test_one_fetch_per_unique_game_pk(monkeypatch, memory_session_local):
    payloads = {1: _payload_for_game_1(), 2: _payload_for_game_1()}
    calls = _patch_common(monkeypatch, payloads)

    mod.ingest_season(2024)

    # 2 game_pk unicos -- una sola llamada por juego, no por equipo.
    assert sorted(calls) == [1, 2]


def test_fetch_error_recorded_without_crashing(monkeypatch, memory_session_local):
    _patch_common(monkeypatch, payloads={})

    result = mod.ingest_season(2024)
    assert result["game_fetch_errors"] == result["unique_games_fetched"]
    assert result["unique_games_fetched"] == 2


def test_skips_teams_already_done_without_force(monkeypatch, memory_session_local):
    payloads = {1: _payload_for_game_1(), 2: _payload_for_game_1()}
    calls = _patch_common(monkeypatch, payloads)

    first = mod.ingest_season(2024)
    assert first["teams_processed"] == 2
    n_calls_after_first = len(calls)

    second = mod.ingest_season(2024)
    assert second["teams_processed"] == 0
    assert len(calls) == n_calls_after_first

    third = mod.ingest_season(2024, force=True)
    assert third["teams_processed"] == 2
