import pytest

from ptopilot.core.stats import Baseline, compute_baseline, deal_level, length_bucket, z_score


def test_no_data_means_no_baseline():
    assert compute_baseline([]) is None


def test_robust_median_and_mad_sigma():
    b = compute_baseline([100, 110, 90, 105, 95] * 4)
    assert b.median == 100
    assert b.sigma == pytest.approx(1.4826 * 5)
    assert (b.n, b.confidence) == (20, "normal")


def test_one_outlier_barely_moves_the_baseline():
    b = compute_baseline([100, 110, 90, 105, 95] * 4 + [5000])
    assert b.median == 100
    assert b.sigma == pytest.approx(1.4826 * 5)


def test_sigma_floor_when_prices_never_move():
    b = compute_baseline([500] * 20)
    assert b.sigma == pytest.approx(15)  # 3% of 500


def test_cold_start_without_google_uses_own_data_with_low_confidence():
    b = compute_baseline([400, 420, 380])
    assert b.median == 400
    assert b.confidence == "low"


def test_cold_start_blends_toward_google_typical_range():
    b = compute_baseline([400] * 5, google_range=(300, 600))
    # weight = 5/15: median = 1/3*400 + 2/3*450; sigma = 1/3*0 + 2/3*150
    assert b.median == pytest.approx(433.333, abs=0.01)
    assert b.sigma == pytest.approx(100)
    assert b.confidence == "low"


def test_google_range_alone_is_a_baseline():
    b = compute_baseline([], google_range=(300, 500))
    assert (b.median, b.sigma, b.n, b.confidence) == (400, 100, 0, "low")


def test_google_range_ignored_once_history_is_enough():
    b = compute_baseline([100, 110, 90, 105, 95] * 3, google_range=(1000, 2000))
    assert b.median == 100
    assert b.confidence == "normal"


def test_z_score():
    assert z_score(80, Baseline(100, 10, 20, "normal")) == -2.0


@pytest.mark.parametrize(
    "z, level",
    [(-0.99, "none"), (-1.0, "good"), (-1.49, "good"), (-1.5, "great"), (-3, "great"), (0.5, "none")],
)
def test_deal_level_thresholds(z, level):
    assert deal_level(z) == level


@pytest.mark.parametrize(
    "days, bucket", [(2, "short"), (5, "short"), (6, "week"), (10, "week"), (11, "long")]
)
def test_length_bucket(days, bucket):
    assert length_bucket(days) == bucket
