import pytest

from ptopilot.core.scoring import deal_component, efficiency_component, go_now, timing_component


def test_perfect_trip_scores_100():
    assert go_now(z=-2.5, rating="good", efficiency=3.0, days_until_departure=60, international=True) == 100


def test_poor_trip_scores_low():
    # 0.5*0 + 0.2*0.2 + 0.15*0 + 0.1*0 + 0.05*0.5 = 0.065
    poor = go_now(
        z=0.0, rating="avoid", efficiency=1.0, days_until_departure=10, international=True, length_fit=0.0
    )
    assert poor == 6


def test_missing_z_contributes_nothing():
    assert deal_component(None) == 0.0


@pytest.mark.parametrize("z, expected", [(0.5, 0.0), (0.0, 0.0), (-1.25, 0.5), (-2.5, 1.0), (-4.0, 1.0)])
def test_deal_component(z, expected):
    assert deal_component(z) == pytest.approx(expected)


@pytest.mark.parametrize("eff, expected", [(0.8, 0.0), (1.0, 0.0), (2.0, 0.5), (3.0, 1.0), (8.0, 1.0)])
def test_efficiency_component(eff, expected):
    assert efficiency_component(eff) == pytest.approx(expected)


@pytest.mark.parametrize(
    "days, international, expected",
    [
        (29, True, 0.5),
        (30, True, 1.0),
        (120, True, 1.0),
        (121, True, 0.5),
        (20, False, 0.5),
        (21, False, 1.0),
        (90, False, 1.0),
        (91, False, 0.5),
    ],
)
def test_timing_sweet_spot(days, international, expected):
    assert timing_component(days, international) == expected
