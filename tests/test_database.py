"""
Tests del esquema propio contra SQLite en memoria -- nunca contra el
TEAM_STRENGTH_DATABASE_URL real del entorno (se crea un engine propio en
cada test, independiente del engine global del modulo).
"""

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from db.database import Base, CandidateAuditResult, LinescoreGame


def _memory_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def test_linescore_game_roundtrip():
    session = _memory_session()
    session.add(LinescoreGame(
        game_pk=745444,
        game_date="2024-06-01",
        season=2024,
        home_f5_runs=4,
        away_f5_runs=2,
        home_f5_result="home",
        home_total_runs=5,
        away_total_runs=3,
        innings_raw=[{"num": 1, "home": {"runs": 1}, "away": {"runs": 0}}],
    ))
    session.commit()

    row = session.get(LinescoreGame, 745444)
    assert row.home_f5_result == "home"
    assert row.innings_raw[0]["num"] == 1


def test_candidate_audit_result_roundtrip():
    session = _memory_session()
    session.add(CandidateAuditResult(
        run_id="spike-2026-07-19",
        hypothesis_name="t1_totals_specialization",
        target="totals",
        n_games=13101,
        coverage_pct=100.0,
        auc=0.55,
        delta_brier_mean=-0.0015,
        ci_low=-0.0021,
        ci_high=-0.0009,
        significant=True,
        effect_size_ok=True,
        meets_all_3_conditions=True,
    ))
    session.commit()

    row = session.query(CandidateAuditResult).filter_by(hypothesis_name="t1_totals_specialization").one()
    assert row.meets_all_3_conditions is True
