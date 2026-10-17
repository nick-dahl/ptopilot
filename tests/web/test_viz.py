from datetime import date, timedelta
from decimal import Decimal

from ptopilot.core.geo import Palette
from ptopilot.web.viz import BarGeometry, TrendPoint, bar_geometry, trend_chart

TEAL = Palette("#0e7490", "#c3dde3")
D0 = date(2027, 3, 1)


def points(*prices, gaps=()):
    """One point per day from D0, skipping the day offsets in `gaps`."""
    out, day = [], D0
    for price in prices:
        while (day - D0).days in gaps:
            day += timedelta(days=1)
        out.append(TrendPoint(day, Decimal(price)))
        day += timedelta(days=1)
    return out


def test_bar_puts_the_typical_band_around_the_median():
    g = bar_geometry(Decimal(700), median=700, sigma=50)
    assert g == BarGeometry(dot=50.0, band_start=33.3, band_end=66.7)


def test_cheaper_price_sits_left_of_the_band():
    g = bar_geometry(Decimal(600), median=700, sigma=50)
    assert g.dot < g.band_start


def test_dot_never_leaves_the_track():
    assert bar_geometry(Decimal(1), median=700, sigma=50).dot == 2.0
    assert bar_geometry(Decimal(99999), median=700, sigma=50).dot == 98.0


def test_no_baseline_means_no_bar():
    assert bar_geometry(Decimal(700), median=None, sigma=None) is None


def test_zero_sigma_uses_the_floor_instead_of_dividing_by_zero():
    g = bar_geometry(Decimal(700), median=700, sigma=0)
    assert g.band_start < g.dot < g.band_end


def test_fewer_than_three_points_has_no_chart():
    assert trend_chart(points(700, 690), None, TEAL) is None


def test_chart_reports_its_range_and_dates():
    chart = trend_chart(points(700, 650, 680), None, TEAL)
    assert (chart.low, chart.high) == (Decimal(650), Decimal(700))
    assert (chart.first, chart.last) == (D0, D0 + timedelta(days=2))
    assert chart.svg.count("<polyline") == 1 and "#0e7490" in chart.svg


def test_missing_days_break_the_line_into_segments():
    chart = trend_chart(points(700, 690, 680, 670, gaps=(2,)), None, TEAL)
    assert chart.svg.count("<polyline") == 2


def test_band_is_drawn_when_known_and_widens_the_range():
    chart = trend_chart(points(700, 690, 680), (Decimal(600), Decimal(760)), TEAL)
    assert "<rect" in chart.svg and "#c3dde3" in chart.svg
    assert (chart.low, chart.high) == (Decimal(600), Decimal(760))
    assert "<rect" not in trend_chart(points(700, 690, 680), None, TEAL).svg


def test_latest_price_is_marked():
    assert trend_chart(points(700, 690, 680), None, TEAL).svg.count("<circle") == 1


def test_flat_prices_still_draw():
    chart = trend_chart(points(700, 700, 700), None, TEAL)
    assert "nan" not in chart.svg.lower() and chart.svg.count("<polyline") == 1


def test_a_lone_day_between_gaps_is_still_drawn():
    chart = trend_chart(points(700, 690, 680, 670, 660, gaps=(2, 4)), None, TEAL)
    assert chart.svg.count("<polyline") == 2
    assert chart.svg.count("<circle") == 2
