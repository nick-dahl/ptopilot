"""Fit checks: whether a trip overlaps a booked one or exceeds the PTO left."""

from datetime import date
from decimal import Decimal

from ptopilot.core.fit import BookedTrip, first_overlap, fit_notes, overlaps


def booked(tracker_id=1, depart=date(2027, 3, 12), ret=date(2027, 3, 21), name="Madeira"):
    return BookedTrip(tracker_id, name, 2027, depart, ret, 5, Decimal("400"), "USD")


def test_overlaps_is_inclusive():
    assert overlaps(date(2027, 3, 12), date(2027, 3, 21), date(2027, 3, 21), date(2027, 3, 25))
    assert not overlaps(date(2027, 3, 12), date(2027, 3, 21), date(2027, 3, 22), date(2027, 3, 25))


def test_first_overlap_ignores_the_given_tracker():
    b = [booked()]
    assert first_overlap(date(2027, 3, 20), date(2027, 3, 25), b) is b[0]
    assert first_overlap(date(2027, 3, 20), date(2027, 3, 25), b, ignore_tracker=1) is None
    assert first_overlap(date(2027, 4, 1), date(2027, 4, 5), b) is None


def test_fit_notes():
    b = [booked()]
    d, r = date(2027, 3, 20), date(2027, 3, 25)
    far = (date(2027, 6, 1), date(2027, 6, 5))
    assert fit_notes(d, r, 3, b, None) == ("Overlaps your booked Madeira trip.",)
    assert fit_notes(*far, 6, b, 4) == ("Doesn't fit your remaining PTO (4 left).",)
    assert fit_notes(*far, 1, b, -2) == ("Doesn't fit your remaining PTO (0 left).",)
    assert fit_notes(d, r, 6, b, 4) == (
        "Overlaps your booked Madeira trip.",
        "Doesn't fit your remaining PTO (4 left).",
    )
    assert fit_notes(d, r, 3, b, None, own_tracker_id=1) == ()
    assert fit_notes(*far, 6, b, None) == ()
    assert fit_notes(*far, 4, b, 4) == ()
