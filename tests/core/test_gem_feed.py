from datetime import date

from ptopilot.core.gem_feed import next_gem
from ptopilot.gems import Gem


def gem(slug, styles=("rail",), airports=("AAA",), status="approved"):
    return Gem(
        slug=slug, name=slug, country="PT", airports=tuple(airports), return_airports=(),
        styles=tuple(styles),
        best_months=(5,), headline="h", body="b", budget="b", daily_cost_usd=50, claims=(), status=status,
        approved_on=date(2026, 1, 1), photo=None,
    )  # fmt: skip


def test_best_style_match_wins_ties_by_catalogue_order():
    gems = [gem("a", ["beach"]), gem("b", ["rail", "food_wine"]), gem("c", ["rail", "food_wine"])]
    assert next_gem(gems, [], ["rail", "food_wine"], set(), 1).slug == "b"


def test_every_fourth_issue_is_a_wildcard():
    gems = [gem("a", ["beach"]), gem("b", ["rail"])]
    assert next_gem(gems, [], ["rail"], set(), 3).slug == "b"
    assert next_gem(gems, [], ["rail"], set(), 4).slug == "a"


def test_no_styles_means_catalogue_order():
    gems = [gem("a", ["beach"]), gem("b", ["rail"])]
    assert next_gem(gems, [], [], set(), 1).slug == "a"


def test_tracked_places_are_never_issued():
    gems = [gem("a", airports=["LIS"]), gem("b", airports=["OPO"])]
    assert next_gem(gems, [], [], {"LIS"}, 1).slug == "b"


def test_already_issued_and_unapproved_are_skipped():
    gems = [gem("a"), gem("b", status="draft"), gem("c", status="retired"), gem("d")]
    assert next_gem(gems, ["a"], [], set(), 1).slug == "d"
    assert next_gem(gems, ["a", "d"], [], set(), 1) is None
