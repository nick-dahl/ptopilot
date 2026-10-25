from datetime import date

import pytest

from ptopilot.core.calendar import WorkCalendar
from ptopilot.core.planner import TrackerSpec, TravelerProfile, Window, plan_itineraries
from ptopilot.core.selection import ground_days
from ptopilot.data import load_geo, load_seasons

GEO = load_geo()
SEASONS = load_seasons()
JUNE = Window(date(2027, 6, 1), date(2027, 6, 30))
SEPT = Window(date(2027, 9, 1), date(2027, 9, 30))
THAILAND = TrackerSpec("TH", min_stay_days=7, max_stay_days=12)


def profile(**overrides):
    base = {
        "home_airports": ("ORD",),
        "calendar": WorkCalendar.from_code("US"),
        "pto_available": 10,
        "min_trip_days": 3,
        "max_trip_days": 16,
        "weather_tolerance": "normal",
        "friday_evening_departure": False,
    }
    return TravelerProfile(**(base | overrides))


def test_shipped_data_files_load():
    assert GEO.destination("TH").airports == ("BKK", "HKT", "CNX")
    assert SEASONS.rating(["TH"], 9) == "avoid"


def test_thailand_in_june_but_not_rainy_september():
    its = plan_itineraries(profile(), THAILAND, [JUNE, SEPT], GEO, SEASONS)
    assert its
    assert {i.month for i in its} == {6}
    assert {i.season_rating for i in its} == {"shoulder"}


def test_relaxed_tolerance_keeps_september():
    its = plan_itineraries(profile(weather_tolerance="relaxed"), THAILAND, [JUNE, SEPT], GEO, SEASONS)
    assert {i.month for i in its} == {6, 9}


def test_every_itinerary_respects_limits():
    its = plan_itineraries(profile(), THAILAND, [JUNE], GEO, SEASONS)
    for i in its:
        s = i.shape
        assert 9 <= s.days_away <= 16  # NA -> SE_ASIA minimum is 9
        assert 7 <= ground_days(s, 3) <= 12
        assert s.pto_cost <= 10


def test_fans_out_across_destination_airports_and_caps_shapes():
    its = plan_itineraries(profile(), THAILAND, [JUNE], GEO, SEASONS)
    shapes = {i.shape for i in its}
    assert 0 < len(shapes) <= 6
    assert len(its) == len(shapes) * 3  # BKK, HKT, CNX
    assert {i.dest_airport for i in its} == {"BKK", "HKT", "CNX"}


def test_each_home_airport_gets_its_own_itineraries():
    its = plan_itineraries(profile(home_airports=("ORD", "MDW")), THAILAND, [JUNE], GEO, SEASONS)
    assert {i.origin for i in its} == {"ORD", "MDW"}


def test_overlapping_windows_do_not_duplicate_itineraries():
    early_june = Window(date(2027, 6, 1), date(2027, 6, 20))
    its = plan_itineraries(profile(), THAILAND, [JUNE, early_june], GEO, SEASONS)
    keys = [(i.origin, i.dest_airport, i.shape) for i in its]
    assert len(keys) == len(set(keys))


def test_zero_pto_left_only_allows_free_trips():
    # Company gives Tue-Wed after Memorial Day off: Sat May 29 -> Wed Jun 2 costs 0 PTO.
    cal = WorkCalendar.from_code("US", extra_days_off=[date(2027, 6, 1), date(2027, 6, 2)])
    lisbon = TrackerSpec("LIS", min_stay_days=1, max_stay_days=5)
    memorial = Window(date(2027, 5, 27), date(2027, 6, 6))
    its = plan_itineraries(profile(calendar=cal, pto_available=0), lisbon, [memorial], GEO, SEASONS)
    assert [(i.shape.depart_date, i.shape.return_date) for i in its] == [
        (date(2027, 5, 29), date(2027, 6, 2))
    ]
    assert its[0].shape.pto_cost == 0


def test_negative_pto_is_treated_as_zero():
    its = plan_itineraries(profile(pto_available=-3), THAILAND, [JUNE], GEO, SEASONS)
    assert its == []


def test_invalid_inputs_are_rejected():
    with pytest.raises(ValueError):
        TrackerSpec("TH", min_stay_days=10, max_stay_days=5)
    with pytest.raises(ValueError):
        Window(date(2027, 6, 30), date(2027, 6, 1))


def test_inverted_trip_length_range_is_rejected():
    with pytest.raises(ValueError, match="10"):
        profile(min_trip_days=10, max_trip_days=5)


NYC = ("JFK", "EWR", "PHL")


def test_open_jaw_route_pairs_arrival_and_return_airports():
    camino = TrackerSpec("CAMINO_PORTUGUES", min_stay_days=11, max_stay_days=14)
    march = Window(date(2027, 3, 1), date(2027, 3, 31))
    its = plan_itineraries(
        profile(home_airports=NYC, weather_tolerance="relaxed"), camino, [march], GEO, SEASONS
    )
    assert its
    assert {(i.dest_airport, i.return_airport) for i in its} == {("OPO", "SCQ")}
    assert all(i.open_jaw for i in its)
    assert {i.origin for i in its} == set(NYC)


def test_round_trips_return_from_the_arrival_airport():
    its = plan_itineraries(profile(), THAILAND, [JUNE], GEO, SEASONS)
    assert all(i.return_airport == i.dest_airport and not i.open_jaw for i in its)


def test_new_destinations_load_with_seasons():
    for code in ("PATAGONIA", "AZORES", "MADEIRA", "CAMINO_PORTUGUES"):
        dest = GEO.destination(code)
        assert SEASONS.rating([dest.code, dest.country], 3) in ("good", "shoulder", "avoid")
    assert SEASONS.rating(["PATAGONIA"], 7) == "avoid"  # southern winter
    assert GEO.travel_rule("JFK", GEO.destination("PATAGONIA")).overhead_days == 3


WIDE = Window(date(2027, 5, 1), date(2027, 10, 31))


def wide_profile(**overrides):
    return profile(
        home_airports=("JFK",), pto_available=30, weather_tolerance="relaxed", **overrides
    )


def test_a_too_short_target_for_a_far_place_searches_from_the_minimum():
    tokyo = TrackerSpec("TYO", min_stay_days=1, max_stay_days=60, target_days=3)
    its = plan_itineraries(wide_profile(), tokyo, [WIDE], GEO, SEASONS)
    assert its
    assert all(i.shape.days_away >= 7 for i in its)  # NA -> E_ASIA minimum


def test_a_too_short_target_for_a_distance_band_place_searches_from_the_minimum():
    from ptopilot.core.geo import Destination

    sydney = Destination("SYD_AU", "Sydney", "city", ("SYD",), "AU", "OCEANIA")
    geo = GEO.with_destinations({"SYD_AU": sydney})
    assert geo.travel_rule("JFK", sydney).min_trip_days == 9
    spec = TrackerSpec("SYD_AU", min_stay_days=1, max_stay_days=60, target_days=4)
    its = plan_itineraries(wide_profile(), spec, [WIDE], geo, SEASONS)
    assert its
    assert all(i.shape.days_away >= 9 for i in its)


def test_a_target_above_the_profile_maximum_raises_the_length_cap():
    tokyo = TrackerSpec("TYO", min_stay_days=1, max_stay_days=60, target_days=10)
    its = plan_itineraries(wide_profile(max_trip_days=8), tokyo, [WIDE], GEO, SEASONS)
    assert its
    assert max(i.shape.days_away for i in its) > 8
    assert all(i.shape.days_away <= 12 for i in its)  # target + tolerance
