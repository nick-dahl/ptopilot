from datetime import date

import pytest

from ptopilot.core.calendar import WorkCalendar

US = WorkCalendar.from_code("US")


def test_weekends_are_not_workdays():
    assert US.is_workday(date(2027, 8, 4))  # Wed
    assert not US.is_workday(date(2027, 8, 7))  # Sat
    assert not US.is_workday(date(2027, 8, 8))  # Sun


def test_thanksgiving_is_off_but_day_after_is_not_by_default():
    assert not US.is_workday(date(2027, 11, 25))
    assert US.is_workday(date(2027, 11, 26))


def test_extra_company_days_off():
    cal = WorkCalendar.from_code("US", extra_days_off=[date(2027, 11, 26)])
    assert not cal.is_workday(date(2027, 11, 26))


def test_weekend_holiday_uses_observed_weekday():
    # July 4 2027 is a Sunday; Monday July 5 is the observed holiday.
    assert not US.is_workday(date(2027, 7, 5))
    assert US.holiday_name(date(2027, 7, 5)) == "Independence Day (observed)"


def test_ignored_holidays_become_workdays_including_observed():
    cal = WorkCalendar.from_code(
        "US", ignored_holidays=["Columbus Day", "Juneteenth National Independence Day"]
    )
    assert cal.is_workday(date(2027, 10, 11))  # Columbus Day
    assert cal.is_workday(date(2027, 6, 18))  # Juneteenth (observed)
    assert not cal.is_workday(date(2027, 5, 31))  # Memorial Day still off


def test_pto_cost_counts_only_workdays():
    # Sat May 29 -> Sun Jun 6 2027 spans Memorial Day: Tue-Fri are the only workdays.
    assert US.pto_cost(date(2027, 5, 29), date(2027, 6, 6)) == 4


def test_uk_easter_differs_between_england_and_scotland():
    eng = WorkCalendar.from_code("GB-ENG")
    sct = WorkCalendar.from_code("GB-SCT")
    assert eng.pto_cost(date(2027, 3, 26), date(2027, 3, 29)) == 0  # Good Fri -> Easter Mon
    assert sct.pto_cost(date(2027, 3, 26), date(2027, 3, 29)) == 1  # no Easter Monday in Scotland


def test_uk_summer_bank_holiday_differs_between_england_and_scotland():
    eng = WorkCalendar.from_code("gb-eng")
    sct = WorkCalendar.from_code("GB-SCT")
    assert not eng.is_workday(date(2027, 8, 30)) and eng.is_workday(date(2027, 8, 2))
    assert not sct.is_workday(date(2027, 8, 2)) and sct.is_workday(date(2027, 8, 30))


def test_weekday_days_off_lists_names_in_order():
    cal = WorkCalendar.from_code("US", extra_days_off=[date(2027, 11, 26)])
    assert cal.weekday_days_off(date(2027, 11, 20), date(2027, 11, 28)) == (
        "Thanksgiving Day",
        "Company day off",
    )


def test_weekday_days_off_skips_weekend_holidays():
    # Juneteenth itself is Sat Jun 19 2027; only the observed Friday saves PTO.
    assert US.weekday_days_off(date(2027, 6, 18), date(2027, 6, 20)) == (
        "Juneteenth National Independence Day (observed)",
    )


def test_ignored_holidays_match_case_insensitively():
    cal = WorkCalendar.from_code("US", ignored_holidays=["columbus day"])
    assert cal.is_workday(date(2027, 10, 11))


def test_unknown_ignored_holiday_name_is_a_clear_error():
    with pytest.raises(ValueError, match="Columbo Day"):
        WorkCalendar.from_code("US", ignored_holidays=["Columbo Day"])


def test_unknown_calendar_code_is_a_clear_error():
    with pytest.raises(ValueError, match="XX"):
        WorkCalendar.from_code("XX")
