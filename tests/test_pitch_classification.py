from analysis.pitch_classification import (
    chase_rate_from_counts, classify_pitch, extract_game_pitches,
)


def test_classify_pitch_ball_in_zone_is_not_out_of_zone():
    # Bola dentro de la zona clasica de strike (0,0 es el centro).
    out_of_zone, is_swing = classify_pitch(px=0.0, pz=2.3, sz_top=3.5, sz_bot=1.5, code="B")
    assert out_of_zone is False
    assert is_swing is False


def test_classify_pitch_ball_outside_zone_horizontally():
    out_of_zone, is_swing = classify_pitch(px=1.5, pz=2.3, sz_top=3.5, sz_bot=1.5, code="B")
    assert out_of_zone is True
    assert is_swing is False


def test_classify_pitch_swing_outside_zone_is_a_chase():
    out_of_zone, is_swing = classify_pitch(px=1.5, pz=2.3, sz_top=3.5, sz_bot=1.5, code="S")
    assert out_of_zone is True
    assert is_swing is True


def test_classify_pitch_missing_data_returns_none():
    assert classify_pitch(px=None, pz=2.3, sz_top=3.5, sz_bot=1.5, code="B") is None
    assert classify_pitch(px=0.0, pz=2.3, sz_top=3.5, sz_bot=1.5, code=None) is None


def test_classify_pitch_unknown_code_returns_none():
    assert classify_pitch(px=0.0, pz=2.3, sz_top=3.5, sz_bot=1.5, code="ZZZ_no_existe") is None


def test_extract_game_pitches_uses_is_top_inning_when_present():
    payload = {
        "allPlays": [
            {
                "about": {"isTopInning": True},
                "playEvents": [
                    {
                        "isPitch": True,
                        "pitchData": {"strikeZoneTop": 3.5, "strikeZoneBottom": 1.5, "coordinates": {"pX": 1.5, "pZ": 2.3}},
                        "details": {"code": "S"},
                    },
                    {"isPitch": False},  # no es un pitch (ej. sustitucion) -- se ignora
                ],
            },
        ],
    }
    pitches = extract_game_pitches(payload)
    assert len(pitches) == 1
    assert pitches[0] == {"is_top_inning": True, "out_of_zone": True, "is_swing": True}


def test_extract_game_pitches_falls_back_to_half_inning_string():
    payload = {
        "allPlays": [
            {
                "about": {"halfInning": "bottom"},
                "playEvents": [
                    {
                        "isPitch": True,
                        "pitchData": {"strikeZoneTop": 3.5, "strikeZoneBottom": 1.5, "coordinates": {"pX": 0.0, "pZ": 2.3}},
                        "details": {"code": "B"},
                    },
                ],
            },
        ],
    }
    pitches = extract_game_pitches(payload)
    assert pitches == [{"is_top_inning": False, "out_of_zone": False, "is_swing": False}]


def test_extract_game_pitches_skips_unclassifiable_pitches():
    payload = {
        "allPlays": [
            {
                "about": {"isTopInning": True},
                "playEvents": [
                    {"isPitch": True, "pitchData": {}, "details": {"code": "B"}},  # sin coordenadas
                ],
            },
        ],
    }
    assert extract_game_pitches(payload) == []


def test_chase_rate_from_counts():
    assert chase_rate_from_counts(swings_out_zone=3, pitches_out_zone_seen=10) == 0.3
    assert chase_rate_from_counts(swings_out_zone=0, pitches_out_zone_seen=0) is None
