"""
Test de integracion liviano de ingest_linescore -- sin red real (mockea
get_game_linescore) y sin Postgres real (SQLite en memoria, inyectado
sobre scripts.ingest_linescore.SessionLocal).
"""

import sys
import types

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from db.database import Base, LinescoreGame

# scripts/ no es un paquete formal (ver comentario en run_t1b_calibrated_audit.py)
# -- se importa por ruta de archivo para no depender de scripts/__init__.py.
import importlib.util
_spec = importlib.util.spec_from_file_location(
    "ingest_linescore_module", __file__.replace("tests/test_ingest_linescore.py", "scripts/ingest_linescore.py")
)
ingest_linescore = importlib.util.module_from_spec(_spec)
sys.modules["ingest_linescore_module"] = ingest_linescore
_spec.loader.exec_module(ingest_linescore)


@pytest.fixture()
def memory_session_local(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session_local = sessionmaker(bind=engine)
    monkeypatch.setattr(ingest_linescore, "SessionLocal", session_local)
    return session_local


def _fake_linescore_payload(home_runs_by_inning, away_runs_by_inning):
    return {
        "innings": [
            {"num": i + 1, "home": {"runs": h}, "away": {"runs": a}}
            for i, (h, a) in enumerate(zip(home_runs_by_inning, away_runs_by_inning))
        ]
    }


def test_ingest_season_writes_parsed_rows(monkeypatch, memory_session_local):
    games = [
        {"game_pk": 1001, "game_date": "2024-04-01", "season": 2024, "home_team_id": 1,
         "away_team_id": 2, "home_pitcher_id": None, "away_pitcher_id": None,
         "home_score": 5, "away_score": 3, "winner": "home"},
        {"game_pk": 1002, "game_date": "2024-04-02", "season": 2024, "home_team_id": 1,
         "away_team_id": 2, "home_pitcher_id": None, "away_pitcher_id": None,
         "home_score": 2, "away_score": 4, "winner": "away"},
    ]
    monkeypatch.setattr(ingest_linescore, "get_games_for_season", lambda season: games)

    payloads = {
        1001: _fake_linescore_payload([1, 0, 0, 1, 0, 0, 0, 0, 0], [0, 0, 1, 0, 0, 1, 0, 0, 1]),
        1002: _fake_linescore_payload([0, 1, 0, 0, 0, 0, 0, 0, 1], [0, 0, 2, 0, 1, 0, 0, 0, 1]),
    }
    monkeypatch.setattr(
        ingest_linescore, "get_game_linescore", lambda game_pk, timeout=15: payloads.get(game_pk)
    )

    result = ingest_linescore.ingest_season(2024)

    assert result["ok"] == 2
    assert result["errors"] == 0
    assert result["already_had"] == 0

    with memory_session_local() as session:
        row1 = session.get(LinescoreGame, 1001)
        assert row1.home_f5_runs == 2  # 1+0+0+1+0
        assert row1.away_f5_runs == 1  # 0+0+1+0+0
        assert row1.home_f5_result == "home"
        assert row1.home_total_runs == 2
        assert row1.away_total_runs == 3


def test_ingest_season_skips_already_ingested_without_force(monkeypatch, memory_session_local):
    games = [{"game_pk": 2001, "game_date": "2024-04-01", "season": 2024, "home_team_id": 1,
              "away_team_id": 2, "home_pitcher_id": None, "away_pitcher_id": None,
              "home_score": 1, "away_score": 0, "winner": "home"}]
    monkeypatch.setattr(ingest_linescore, "get_games_for_season", lambda season: games)

    call_count = {"n": 0}

    def _tracked_fetch(game_pk, timeout=15):
        call_count["n"] += 1
        return _fake_linescore_payload([1] + [0] * 8, [0] * 9)

    monkeypatch.setattr(ingest_linescore, "get_game_linescore", _tracked_fetch)

    first = ingest_linescore.ingest_season(2024)
    assert first["ok"] == 1
    assert call_count["n"] == 1

    second = ingest_linescore.ingest_season(2024)
    assert second["already_had"] == 1
    assert second["attempted"] == 0
    assert call_count["n"] == 1  # no se volvio a llamar a la API


def test_ingest_season_records_errors_without_crashing(monkeypatch, memory_session_local):
    games = [{"game_pk": 3001, "game_date": "2024-04-01", "season": 2024, "home_team_id": 1,
              "away_team_id": 2, "home_pitcher_id": None, "away_pitcher_id": None,
              "home_score": 1, "away_score": 0, "winner": "home"}]
    monkeypatch.setattr(ingest_linescore, "get_games_for_season", lambda season: games)
    monkeypatch.setattr(ingest_linescore, "get_game_linescore", lambda game_pk, timeout=15: None)

    result = ingest_linescore.ingest_season(2024)
    assert result["ok"] == 0
    assert result["errors"] == 1
    assert 3001 in result["error_game_pks"]
