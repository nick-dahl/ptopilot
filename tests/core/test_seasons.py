from datetime import date

import pytest

from ptopilot.core.seasons import SeasonTable, is_allowed, trip_month

TABLE = SeasonTable.from_dict(
    {
        "TH": {
            "months": [
                "good",
                "good",
                "shoulder",
                "shoulder",
                "shoulder",
                "shoulder",
                "shoulder",
                "shoulder",
                "avoid",
                "avoid",
                "good",
                "good",
            ],
            "notes": {9: "Wettest month"},
        }
    }
)


def test_rating_by_code_and_month():
    assert TABLE.rating(["TH"], 1) == "good"
    assert TABLE.rating(["TH"], 6) == "shoulder"
    assert TABLE.rating(["TH"], 9) == "avoid"


def test_rating_falls_back_through_codes():
    assert TABLE.rating(["BKK", "TH"], 9) == "avoid"


def test_unknown_destination_counts_as_good():
    assert TABLE.rating(["ZZZ"], 9) == "good"


def test_note_lookup():
    assert TABLE.note(["TH"], 9) == "Wettest month"
    assert TABLE.note(["TH"], 1) is None
    assert TABLE.note(["ZZZ"], 1) is None


def test_bad_season_entry_is_rejected():
    with pytest.raises(ValueError, match="XX"):
        SeasonTable.from_dict({"XX": {"months": ["good"] * 11}})
    with pytest.raises(ValueError):
        SeasonTable.from_dict({"XX": {"months": ["good"] * 11 + ["rainy"]}})


@pytest.mark.parametrize(
    "rating, tolerance, expected",
    [
        ("good", "strict", True),
        ("shoulder", "strict", False),
        ("shoulder", "normal", True),
        ("avoid", "normal", False),
        ("avoid", "relaxed", True),
    ],
)
def test_tolerance(rating, tolerance, expected):
    assert is_allowed(rating, tolerance) is expected


def test_trip_month_uses_majority_of_days():
    # Jun 26 - Jul 10: 5 days in June, 10 in July
    assert trip_month(date(2027, 6, 26), date(2027, 7, 10)) == 7


def test_trip_month_tie_goes_to_earlier_month():
    # Jun 27 - Jul 4: 4 days each
    assert trip_month(date(2027, 6, 27), date(2027, 7, 4)) == 6


def test_trip_month_across_new_year():
    # Dec 26 - Jan 9: 6 days in Dec, 9 in Jan
    assert trip_month(date(2027, 12, 26), date(2028, 1, 9)) == 1
