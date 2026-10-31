"""The destination page's date grid: depart weeks by trip length, each cell the best price there."""

from datetime import date, timedelta
from decimal import Decimal

from ptopilot.web.grid import date_grid
from ptopilot.web.history import TripOption


def opt(price, depart, days, level="good", state="new", verdict="ok", dest="PDL", home=None, cid=1):
    return TripOption(
        candidate_id=cid,
        tracker_id=1,
        origin="JFK",
        dest_airport=dest,
        return_airport=home or dest,
        depart_date=depart,
        return_date=depart + timedelta(days=days - 1),
        evening_departure=False,
        price=Decimal(price),
        currency="USD",
        pto_cost=5,
        days_away=days,
        season_rating="good",
        weather_note=None,
        carrier=None,
        stops=None,
        overnight=None,
        deep_link=None,
        deal_level=level,
        go_now=50,
        state=state,
        median=None,
        sigma=None,
        bar=None,
        verdict=verdict,
    )


WED, FRI = date(2027, 3, 3), date(2027, 3, 5)  # the week of Monday March 1
NEXT_SAT = date(2027, 3, 13)  # the week of Monday March 8


def test_grid_rows_are_departure_weeks_and_columns_trip_lengths():
    options = [
        opt(700, NEXT_SAT, 9),
        opt(650, FRI, 10, home="TER"),  # open-jaw trips share the axes
        opt(600, WED, 8),
        opt(500, WED, 15),  # outside the band: not in the grid
    ]
    grid = date_grid(options, (7, 11))
    assert grid.weeks == [date(2027, 3, 1), date(2027, 3, 8)]
    assert grid.lengths == [7, 8, 9, 10, 11]
    assert grid.cells[(date(2027, 3, 1), 10)].price == Decimal(650)
    assert grid.cells[(date(2027, 3, 8), 9)].price == Decimal(700)
    assert (date(2027, 3, 1), 7) not in grid.cells


def test_grid_shows_at_most_twelve_weeks_earliest_first():
    options = [opt(600 + i, date(2027, 3, 1) + timedelta(weeks=i), 9) for i in reversed(range(15))]
    grid = date_grid(options, (7, 11))
    assert len(grid.weeks) == 12 and grid.weeks[0] == date(2027, 3, 1)
    assert grid.weeks[-1] == date(2027, 3, 1) + timedelta(weeks=11)


def test_grid_cell_takes_the_cheapest_non_dimmed_option():
    options = [
        opt(500, WED, 9, state="excluded", cid=1),
        opt(550, FRI, 9, verdict="ruled_out", level="none", cid=2),
        opt(640, FRI, 9, level="great", cid=3),
        opt(700, WED, 9, cid=4),
    ]
    cell = date_grid(options, (7, 11)).cells[(date(2027, 3, 1), 9)]
    assert (cell.price, cell.level, cell.dimmed) == (Decimal(640), "great", False)
    assert cell.option_key == options[2].option_key


def test_grid_cell_is_dimmed_when_every_option_is():
    options = [opt(500, WED, 9, state="snoozed"), opt(450, FRI, 9, verdict="ruled_out", level="none")]
    cell = date_grid(options, (7, 11)).cells[(date(2027, 3, 1), 9)]
    assert cell.dimmed and cell.price == Decimal(450)


def test_option_keys_are_unique_per_trip():
    a, b = opt(600, WED, 9), opt(600, WED, 9, home="TER")
    assert a.option_key != b.option_key and " " not in a.option_key


def test_no_trips_is_an_empty_grid():
    grid = date_grid([], (7, 11))
    assert grid.weeks == [] and grid.cells == {}
