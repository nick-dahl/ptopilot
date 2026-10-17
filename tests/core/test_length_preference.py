"""Preferred trip length: how close a trip is to it, and how that steers selection and the go-now score."""

from datetime import date, timedelta

import pytest

from ptopilot import config
from ptopilot.core.scoring import go_now, length_fit
from ptopilot.core.selection import select_top
from ptopilot.core.shapes import TripShape


def shape(days_away, pto, start=date(2027, 3, 5)):
    return TripShape(start, start + timedelta(days=days_away - 1), pto, False)


@pytest.mark.parametrize(
    "days, expected", [(10, 1.0), (9, 0.75), (11, 0.75), (13, 0.25), (14, 0.0), (6, 0.0), (20, 0.0)]
)
def test_length_fit_fades_over_four_days(days, expected):
    assert length_fit(days, 10) == pytest.approx(expected)


def test_no_preference_fits_every_length():
    assert length_fit(3, None) == 1.0 and length_fit(16, None) == 1.0


def test_weights_still_sum_to_one():
    assert sum(config.GO_NOW_WEIGHTS.values()) == pytest.approx(1.0)


def test_length_fit_moves_the_go_now_score_by_its_weight():
    args = dict(z=-1.0, rating="good", efficiency=2.0, days_until_departure=60, international=True)
    gap = go_now(**args, length_fit=1.0) - go_now(**args, length_fit=0.0)
    assert abs(gap - 100 * config.GO_NOW_WEIGHTS["length"]) <= 1  # each score is rounded on its own


def test_go_now_defaults_to_a_full_length_fit():
    args = dict(z=-1.0, rating="good", efficiency=2.0, days_until_departure=60, international=True)
    assert go_now(**args) == go_now(**args, length_fit=1.0)


def test_near_ideal_trip_outranks_a_slightly_more_efficient_one():
    sixteen = shape(16, 8)  # efficiency 2.0, far from the ideal
    ten = shape(10, 6, start=date(2027, 3, 12))  # efficiency ~1.67 (2.08 with the bonus), the ideal
    assert select_top([sixteen, ten], n=1) == [sixteen]  # V1: efficiency alone
    assert select_top([sixteen, ten], n=1, ideal_days=10) == [ten]


def test_a_much_more_efficient_trip_still_wins():
    holiday_bridge = shape(9, 3)  # efficiency 3.0
    ideal = shape(10, 6, start=date(2027, 3, 12))  # efficiency ~1.67
    assert select_top([holiday_bridge, ideal], n=1, ideal_days=10) == [holiday_bridge]


def test_per_length_cap_still_applies_with_an_ideal():
    tens = [shape(10, 5, start=date(2027, 3, 1) + timedelta(days=7 * i)) for i in range(4)]
    seven = shape(7, 5, start=date(2027, 3, 3))
    picked = select_top([*tens, seven], n=4, max_per_length=2, ideal_days=10)
    assert sum(1 for s in picked if s.days_away == 10) == 2 and seven in picked
