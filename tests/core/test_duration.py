from datetime import date, timedelta

from ptopilot.core.duration import duration_label, expected_days

TODAY = date(2027, 5, 1)
DIP = 800.0


def series(dips: list[tuple[int, int]], days: int = 58, skip: tuple[int, ...] = ()):
    """Daily 1000s going back `days` days; each (start, length) is a dip of that length, `start` days ago."""
    dip_days = {start - i for start, length in dips for i in range(length)}
    out = []
    for ago in range(days, 0, -1):
        if ago in skip:
            continue
        out.append((TODAY - timedelta(days=ago), DIP if ago in dip_days else 1000.0))
    return out


def test_typical_dip_length_is_the_estimate():
    s = series([(45, 2), (38, 3), (30, 4)])
    assert expected_days(s, TODAY, DIP, 60) == 3


def test_a_gap_ends_a_dip():
    # a 4-day dip with a missing day inside is a 2-day and a 1-day dip -> median 1.5, rounded up
    s = series([(45, 4)], skip=(43,))
    assert expected_days(s, TODAY, DIP, 60) == 2


def test_no_dip_today_means_no_duration():
    s = series([(45, 2), (38, 3), (30, 4)])
    assert expected_days(s, TODAY, 1000.0, 60) is None
    assert expected_days(s, TODAY, 1200.0, 60) is None


def test_fewer_than_two_past_dips_is_not_enough_history():
    assert expected_days(series([(40, 3)]), TODAY, DIP, 60) is None


def test_shallower_dips_do_not_count():
    s = [(d, 900.0 if p == DIP else p) for d, p in series([(45, 2), (38, 3), (30, 4)])]
    assert expected_days(s, TODAY, DIP, 60) is None


def test_the_current_run_is_not_a_past_dip():
    s = series([(45, 3), (38, 3), (30, 3), (2, 2)])  # yesterday's dip is today's own
    assert expected_days(s, TODAY, DIP, 60) == 3
    assert expected_days(series([(45, 3), (2, 2)]), TODAY, DIP, 60) is None


def test_thin_history_is_not_enough_to_judge():
    assert expected_days(series([], days=9), TODAY, DIP, 60) is None  # today lacks 10 points
    s = series([(50, 2), (40, 3), (30, 4)], days=58)
    assert expected_days(s[-9:], TODAY, DIP, 60) is None


def test_early_days_without_a_window_are_not_dips():
    # the dip at the very start has no trailing window of 10 points, so it cannot count
    s = series([(58, 3), (40, 3)])
    assert expected_days(s, TODAY, DIP, 60) is None


def test_duration_is_capped_by_days_to_departure():
    s = series([(48, 6), (35, 6), (20, 6)])
    assert expected_days(s, TODAY, DIP, 60) == 6
    assert expected_days(s, TODAY, DIP, 2) == 2


def test_labels():
    assert (
        duration_label(1) == "likely gone within ~1 day" and duration_label(3) == "likely gone within ~3 days"
    )
    assert duration_label(7) == "likely gone within ~7 days"
    assert duration_label(9) == "likely to hold for a week or more"
    assert duration_label(None, dips_found=False) == "not enough history yet" and duration_label(None) is None
