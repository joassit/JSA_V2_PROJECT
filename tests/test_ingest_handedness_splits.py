import importlib.util
import sys
from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from db.database import Base, HandednessSplitSnapshot

_spec = importlib.util.spec_from_file_location(
    "ingest_handedness_splits_module",
    __file__.replace("tests/test_ingest_handedness_splits.py", "scripts/ingest_handedness_splits.py"),
)
mod = importlib.util.module_from_spec(_spec)
sys.modules["ingest_handedness_splits_module"] = mod
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
    ]


def test_ingest_season_fetches_both_hands_for_both_teams(monkeypatch, memory_session_local):
    monkeypatch.setattr(mod, "get_games_for_season", lambda season: _games())

    calls = []

    def fake_get_split(team_id, start_date, end_date, vs_hand, season):
        calls.append((team_id, start_date, end_date, vs_hand, season))
        return {"raw": True}

    monkeypatch.setattr(mod, "get_team_hitting_split_by_date_range", fake_get_split)
    monkeypatch.setattr(mod, "parse_team_hitting_split", lambda raw: {"ops": 0.75, "obp": 0.33, "slg": 0.42, "plate_appearances": 100})

    result = mod.ingest_season(2024)

    # 2 equipos x 2 manos = 4 llamadas
    assert result["attempted"] == 4
    assert result["ok"] == 4
    assert len(calls) == 4
    team_ids = {c[0] for c in calls}
    assert team_ids == {100, 200}
    hands = {c[3] for c in calls}
    assert hands == {"L", "R"}


def test_cutoff_is_day_before_game_date(monkeypatch, memory_session_local):
    monkeypatch.setattr(mod, "get_games_for_season", lambda season: _games())

    calls = []

    def fake_get_split(team_id, start_date, end_date, vs_hand, season):
        calls.append(end_date)
        return {"raw": True}

    monkeypatch.setattr(mod, "get_team_hitting_split_by_date_range", fake_get_split)
    monkeypatch.setattr(mod, "parse_team_hitting_split", lambda raw: {"ops": 0.75, "obp": 0.33, "slg": 0.42, "plate_appearances": 100})

    mod.ingest_season(2024)

    # El juego es 2024-04-10 -- el corte debe ser 2024-04-09, nunca el mismo dia.
    assert all(c == "2024-04-09" for c in calls)


def test_upsert_writes_row_with_expected_values(monkeypatch, memory_session_local):
    monkeypatch.setattr(mod, "get_games_for_season", lambda season: _games())
    monkeypatch.setattr(mod, "get_team_hitting_split_by_date_range", lambda *a, **k: {"raw": True})
    monkeypatch.setattr(mod, "parse_team_hitting_split", lambda raw: {"ops": 0.812, "obp": 0.34, "slg": 0.47, "plate_appearances": 55})

    mod.ingest_season(2024)

    with memory_session_local() as session:
        row = session.query(HandednessSplitSnapshot).filter_by(team_id=100, vs_hand="L").one()
        # as_of_date es la fecha del JUEGO al que aplica el snapshot (para
        # facilitar el join por game_date despues) -- el corte real
        # enviado a la API (end_date, un dia antes) ya se verifica aparte
        # en test_cutoff_is_day_before_game_date.
        assert row.as_of_date == "2024-04-10"
        assert row.ops == 0.812
        assert row.plate_appearances == 55


def test_skips_existing_without_force_and_overwrites_with_force(monkeypatch, memory_session_local):
    monkeypatch.setattr(mod, "get_games_for_season", lambda season: _games())

    call_count = {"n": 0}

    def fake_get_split(team_id, start_date, end_date, vs_hand, season):
        call_count["n"] += 1
        return {"raw": True}

    monkeypatch.setattr(mod, "get_team_hitting_split_by_date_range", fake_get_split)
    monkeypatch.setattr(mod, "parse_team_hitting_split", lambda raw: {"ops": 0.700, "obp": 0.30, "slg": 0.40, "plate_appearances": 10})

    first = mod.ingest_season(2024)
    assert first["ok"] == 4
    assert call_count["n"] == 4

    second = mod.ingest_season(2024)
    assert second["attempted"] == 0
    assert second["already_had"] == 4
    assert call_count["n"] == 4  # no llamadas nuevas

    third = mod.ingest_season(2024, force=True)
    assert third["attempted"] == 4
    assert call_count["n"] == 8


def test_errors_recorded_without_crashing(monkeypatch, memory_session_local):
    monkeypatch.setattr(mod, "get_games_for_season", lambda season: _games())
    monkeypatch.setattr(mod, "get_team_hitting_split_by_date_range", lambda *a, **k: None)
    monkeypatch.setattr(mod, "parse_team_hitting_split", lambda raw: None)

    result = mod.ingest_season(2024)
    assert result["ok"] == 0
    assert result["errors"] == 4
