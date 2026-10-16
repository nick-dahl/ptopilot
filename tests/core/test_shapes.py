from datetime import date

import pytest

from ptopilot.core.calendar import WorkCalendar
from ptopilot.core.shapes import TripShape, generate_shapes

US = WorkCalendar.from_code("US")
FRI, SAT, SUN, MON = 4, 5, 6, 0


def find(shapes, depart, ret, evening=False):
    matches = [
        s
        for s in shapes
        if s.depart_date == depart and s.return_date == ret and s.evening_departure == evening
    ]
    assert len(matches) == 1, f"expected exactly one {depart}->{ret} evening={evening}"
    return matches[0]


def test_days_away_and_efficiency():
    s = TripShape(date(2027, 8, 7), date(2027, 8, 15), pto_cost=5)
    assert s.days_away == 9
    assert s.efficiency == pytest.approx(1.8)
    assert TripShape(date(2027, 8, 7), date(2027, 8, 8), pto_cost=0).efficiency == 4.0


def test_ordinary_weeks_only_leave_fri_sat_and_return_sun_mon():
    # August 2027 has no US holidays.
    shapes = generate_shapes(US, date(2027, 8, 2), date(2027, 8, 27), max_days_away=16)
    assert shapes
    assert {s.depart_date.weekday() for s in shapes} <= {FRI, SAT}
    assert {s.return_date.weekday() for s in shapes} <= {SUN, MON}


def test_wed_to_thu_shapes_never_appear():
    shapes = generate_shapes(US, date(2027, 8, 2), date(2027, 8, 27), max_days_away=16)
    assert not any(s.depart_date == date(2027, 8, 4) for s in shapes)  # Wed
    assert not any(s.return_date == date(2027, 8, 12) for s in shapes)  # Thu


def test_memorial_day_stretch():
    shapes = generate_shapes(US, date(2027, 5, 24), date(2027, 6, 11), max_days_away=14)
    s = find(shapes, date(2027, 5, 29), date(2027, 6, 6))
    assert s.pto_cost == 4
    assert s.days_away == 9
    assert s.days_off == ("Memorial Day",)


def test_wednesday_departure_allowed_before_thanksgiving():
    cal = WorkCalendar.from_code("US", extra_days_off=[date(2027, 11, 26)])
    shapes = generate_shapes(cal, date(2027, 11, 20), date(2027, 11, 30), max_days_away=10)
    s = find(shapes, date(2027, 11, 24), date(2027, 11, 28))
    assert s.pto_cost == 1


def test_zero_pto_weekend_is_a_shape():
    shapes = generate_shapes(US, date(2027, 8, 2), date(2027, 8, 27), max_days_away=16)
    assert find(shapes, date(2027, 8, 7), date(2027, 8, 8)).pto_cost == 0


def test_friday_evening_variant_saves_one_pto_day():
    shapes = generate_shapes(US, date(2027, 8, 2), date(2027, 8, 27), max_days_away=16, friday_evening=True)
    regular = find(shapes, date(2027, 8, 6), date(2027, 8, 15))
    evening = find(shapes, date(2027, 8, 6), date(2027, 8, 15), evening=True)
    assert regular.pto_cost == 6
    assert evening.pto_cost == 5


def test_no_evening_variants_unless_enabled():
    shapes = generate_shapes(US, date(2027, 8, 2), date(2027, 8, 27), max_days_away=16)
    assert not any(s.evening_departure for s in shapes)


def test_max_days_away_is_respected():
    shapes = generate_shapes(US, date(2027, 8, 2), date(2027, 8, 27), max_days_away=9)
    assert max(s.days_away for s in shapes) <= 9


def test_dates_stay_within_window_plus_slack():
    start, end = date(2027, 8, 4), date(2027, 8, 25)
    shapes = generate_shapes(US, start, end, max_days_away=16, slack_days=2)
    assert min(s.depart_date for s in shapes) >= date(2027, 8, 2)
    assert max(s.return_date for s in shapes) <= date(2027, 8, 27)


def test_window_across_new_year_uses_both_years_holidays():
    shapes = generate_shapes(US, date(2027, 12, 18), date(2028, 1, 9), max_days_away=16)
    # Christmas (observed Fri Dec 24 2027) + New Year (observed Fri Dec 31 2027):
    # Sat Dec 18 -> Sun Jan 2 is 16 days for 8 PTO days.
    s = find(shapes, date(2027, 12, 18), date(2028, 1, 2))
    assert s.pto_cost == 8
    assert s.days_off == ("Christmas Day (observed)", "New Year's Day (observed)")


def test_reversed_window_is_rejected():
    with pytest.raises(ValueError):
        generate_shapes(US, date(2027, 8, 27), date(2027, 8, 2), max_days_away=16)
