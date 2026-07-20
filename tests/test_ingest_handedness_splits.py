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
    # Equipo 100 juega 2 veces de local contra el 200: primero vs un
    # abridor diestro (pitcher_id=1), despues vs uno zurdo (pitcher_id=2)
    # -- permite verificar que la acumulacion es point-in-time (el split
    # del 2do juego SI refleja el 1ro, el del 1ro NO refleja nada previo).
    return [
        {"game_pk": 1, "game_date": date(2024, 4, 10), "season": 2024,
         "home_team_id": 100, "away_team_id": 200, "home_pitcher_id": None,
         "away_pitcher_id": 1, "home_score": 3, "away_score": 1, "winner": "home"},
        {"game_pk": 2, "game_date": date(2024, 4, 15), "season": 2024,
         "home_team_id": 100, "away_team_id": 200, "home_pitcher_id": None,
         "away_pitcher_id": 2, "home_score": 2, "away_score": 4, "winner": "away"},
    ]


_LINE_GAME1 = {"ab": 30, "h": 10, "bb": 3, "hbp": 0, "sf": 0, "tb": 18, "pa": 33}


def _patch_common(monkeypatch, lines: dict[tuple[int, str], dict], hands: dict[int, str]):
    monkeypatch.setattr(mod, "get_games_for_season", lambda season: _games())
    monkeypatch.setattr(mod, "get_pitcher_throws", lambda pid: hands.get(pid))

    calls = []

    def fake_get_daily(team_id, game_date, season):
        calls.append((team_id, game_date, season))
        return lines.get((team_id, game_date))

    monkeypatch.setattr(mod, "get_team_hitting_by_date", fake_get_daily)
    monkeypatch.setattr(mod, "parse_team_hitting_raw", lambda raw: raw)
    return calls


def test_point_in_time_split_reflects_only_prior_games(monkeypatch, memory_session_local):
    lines = {(100, "2024-04-10"): _LINE_GAME1}
    _patch_common(monkeypatch, lines, hands={1: "R", 2: "L"})

    mod.ingest_season(2024)

    with memory_session_local() as session:
        rows = {(r.as_of_date, r.vs_hand): r for r in session.query(HandednessSplitSnapshot).filter_by(team_id=100).all()}

    # Antes del primer juego: sin muestra todavia en ninguna mano.
    assert rows[("2024-04-10", "R")].ops is None
    assert rows[("2024-04-10", "L")].ops is None

    # Antes del segundo juego: vs R ya refleja el 1er juego (rival diestro).
    from analysis.stats_utils import ops_from_raw_counts
    expected_ops = ops_from_raw_counts(**{k: v for k, v in _LINE_GAME1.items() if k != "pa"})
    assert rows[("2024-04-15", "R")].ops == pytest.approx(expected_ops)
    assert rows[("2024-04-15", "R")].plate_appearances == _LINE_GAME1["pa"]
    # vs L sigue sin muestra -- el rival del 2do juego es zurdo, pero ese
    # juego mismo nunca se filtra hacia atras.
    assert rows[("2024-04-15", "L")].ops is None


def test_daily_fetch_happens_once_per_team_per_date_not_per_hand(monkeypatch, memory_session_local):
    lines = {(100, "2024-04-10"): _LINE_GAME1, (100, "2024-04-15"): _LINE_GAME1}
    calls = _patch_common(monkeypatch, lines, hands={1: "R", 2: "L"})

    mod.ingest_season(2024)

    team_100_calls = [c for c in calls if c[0] == 100]
    # 1 llamada por fecha jugada (no 2 por mano, a diferencia de la
    # version Camino 1) -- 2 fechas para el equipo 100.
    assert len(team_100_calls) == 2
    assert {c[1] for c in team_100_calls} == {"2024-04-10", "2024-04-15"}


def test_unknown_opponent_hand_does_not_crash_and_leaves_split_unaccumulated(monkeypatch, memory_session_local):
    lines = {(200, "2024-04-10"): _LINE_GAME1, (200, "2024-04-15"): _LINE_GAME1}
    # home_pitcher_id es None en ambos juegos -- el rival del equipo 200
    # nunca se resuelve.
    _patch_common(monkeypatch, lines, hands={1: "R", 2: "L"})

    result = mod.ingest_season(2024)
    # El equipo 100 tambien se procesa (misma temporada) pero no tiene
    # lineas mockeadas -- solo verificamos que el equipo 200 (sin mano
    # de rival resuelta) no explota y queda sin acumular.
    assert result["daily_fetch_errors"] >= 0

    with memory_session_local() as session:
        rows = session.query(HandednessSplitSnapshot).filter_by(team_id=200).all()
    assert all(r.ops is None for r in rows)


def test_skips_teams_already_done_without_force_and_recomputes_with_force(monkeypatch, memory_session_local):
    lines = {(100, "2024-04-10"): _LINE_GAME1, (100, "2024-04-15"): _LINE_GAME1}
    calls = _patch_common(monkeypatch, lines, hands={1: "R", 2: "L"})

    first = mod.ingest_season(2024)
    assert first["teams_processed"] == 2  # equipos 100 y 200
    n_calls_after_first = len(calls)
    assert n_calls_after_first > 0

    second = mod.ingest_season(2024)
    assert second["teams_processed"] == 0
    assert second["teams_skipped_already_done"] == 2
    assert len(calls) == n_calls_after_first  # sin llamadas nuevas

    third = mod.ingest_season(2024, force=True)
    assert third["teams_processed"] == 2
    assert len(calls) == n_calls_after_first * 2


def test_fetch_error_recorded_without_crashing(monkeypatch, memory_session_local):
    _patch_common(monkeypatch, lines={}, hands={1: "R", 2: "L"})

    result = mod.ingest_season(2024)
    # Ninguna fecha tiene linea disponible en el dict `lines` -- todas
    # las llamadas "fallan" (devuelven None).
    assert result["daily_fetch_errors"] == result["daily_fetches"]
    assert result["daily_fetches"] > 0
