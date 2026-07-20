import random

from analysis.totals_candidate_audit import (
    TOTALS_LINE,
    baseline_total_runs,
    evaluate_t1,
    poisson_over_prob,
    project_total_runs,
)


def test_project_total_runs_all_league_average_hand_computed():
    """
    Con todo en el promedio de liga y park_factor=1.0:
    off_factor = 1.0, pitching_factor = 1.0
    mu_home = 4.50*1*1*1 + HOME_FIELD_RUNS_BONUS(0.15) = 4.65
    mu_away = 4.50*1*1*1 = 4.50
    total = 9.15 -- calculado a mano contra la formula re-derivada de jsa/.
    """
    payload = {
        "league_avg_era": 4.30, "league_avg_ops": 0.750, "league_avg_runs_per_game": 4.50,
        "park_factor": 1.0,
        "home_ops": 0.750, "away_ops": 0.750,
        "home_starter_xera": 4.30, "away_starter_xera": 4.30,
        "home_bullpen_era": 4.30, "away_bullpen_era": 4.30,
    }
    total = project_total_runs(payload)
    assert total is not None
    assert abs(total - 9.15) < 1e-9


def test_project_total_runs_missing_fields_falls_back_to_league_defaults():
    # Payload minimo (solo un campo cualquiera) -- todo lo demas cae a
    # los defaults de liga hardcodeados, mismo resultado que el caso de
    # "todo en el promedio de liga" de arriba.
    payload = {"game_id": "x"}
    total = project_total_runs(payload)
    assert total is not None
    assert abs(total - 9.15) < 1e-9


def test_project_total_runs_none_or_empty_payload_is_none():
    assert project_total_runs(None) is None
    assert project_total_runs({}) is None


def test_project_total_runs_strong_offense_increases_projection():
    weak = {"home_ops": 0.600, "away_ops": 0.600}
    strong = {"home_ops": 0.950, "away_ops": 0.950}
    assert project_total_runs(strong) > project_total_runs(weak)


def test_project_total_runs_weak_pitching_increases_projection():
    ace_pitching = {"home_starter_xera": 2.50, "away_starter_xera": 2.50}
    bad_pitching = {"home_starter_xera": 6.50, "away_starter_xera": 6.50}
    assert project_total_runs(bad_pitching) > project_total_runs(ace_pitching)


def test_baseline_total_runs_ignores_team_specific_fields():
    a = baseline_total_runs({"home_ops": 0.950, "league_avg_runs_per_game": 4.5})
    b = baseline_total_runs({"home_ops": 0.500, "league_avg_runs_per_game": 4.5})
    assert a == b == 9.0


def test_baseline_total_runs_handles_none_payload():
    assert baseline_total_runs(None) == 9.0


def test_poisson_over_prob_monotonic_in_mu():
    assert poisson_over_prob(20.0) > poisson_over_prob(5.0)


def test_poisson_over_prob_bounded_0_1():
    for mu in (0.1, 1.0, 9.0, 30.0):
        p = poisson_over_prob(mu)
        assert 0.0 <= p <= 1.0


def _make_game(game_pk, season, payload, home_score, away_score):
    return {
        "game_pk": game_pk, "season": season, "payload": payload,
        "home_score": home_score, "away_score": away_score,
    }


def test_evaluate_t1_coverage_excludes_incomplete_games():
    games = [
        _make_game(1, 2024, {"league_avg_runs_per_game": 4.5}, 5, 4),
        _make_game(2, 2024, None, 3, 2),  # sin snapshot -- no cuenta para coverage
        _make_game(3, 2024, {"league_avg_runs_per_game": 4.5}, None, None),  # sin resultado
    ]
    result = evaluate_t1(games, n_resamples=20, seed=1)
    assert result["n_games_total"] == 3
    assert result["n_games_covered"] == 1
    assert abs(result["coverage_pct"] - (100 / 3)) < 1e-6


def test_evaluate_t1_groups_by_season():
    rng = random.Random(5)
    games = []
    for season in (2023, 2024):
        for i in range(50):
            payload = {"league_avg_runs_per_game": 4.5, "home_ops": rng.uniform(0.6, 0.9)}
            total = rng.randint(2, 15)
            games.append(_make_game(f"{season}-{i}", season, payload, total // 2, total - total // 2))

    result = evaluate_t1(games, n_resamples=30, seed=2)
    assert set(result["by_season"].keys()) == {2023, 2024}
    assert result["by_season"][2023]["n"] == 50
    assert result["by_season"][2024]["n"] == 50
    assert result["n_games_covered"] == 100
    assert result["coverage_pct"] == 100.0


def test_evaluate_t1_returns_verdict_keys():
    games = [_make_game(i, 2024, {"league_avg_runs_per_game": 4.5}, i % 5 + 3, i % 4 + 2) for i in range(30)]
    result = evaluate_t1(games, n_resamples=20, seed=3)
    for key in ("delta_brier_mean", "ci_low", "ci_high", "significant", "effect_size_ok", "meets_all_3_conditions"):
        assert key in result
