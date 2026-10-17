import pytest

from ptopilot.core.geo import Geo, Palette, palette, tint
from ptopilot.data import load_geo

DATA = {
    "airports": {
        "PDL": {"country": "PT", "zone": "EUROPE"},
        "PUQ": {"country": "CL", "zone": "S_AMERICA"},
        "XXX": {"country": "AQ", "zone": "ANTARCTICA"},
    },
    "destinations": {
        "AZORES": {"name": "Azores", "kind": "region", "airports": ["PDL"], "color": "#0E7490"},
        "PATAGONIA": {"name": "Patagonia", "kind": "region", "airports": ["PUQ"]},
        "POLE": {"name": "South Pole", "kind": "region", "airports": ["XXX"]},
    },
    "travel": {"default": {"overhead_days": 1, "min_trip_days": 2}, "pairs": []},
}
GEO = Geo.from_dict(DATA)


def test_explicit_color_is_used_and_normalized_to_lowercase():
    assert palette(GEO.destination("AZORES")).color == "#0e7490"


def test_missing_color_falls_back_to_the_zone_default():
    assert palette(GEO.destination("PATAGONIA")).color == "#7c2d12"


def test_unknown_zone_falls_back_to_neutral():
    assert palette(GEO.destination("POLE")).color == "#374151"


def test_tint_mixes_a_quarter_of_the_color_into_white():
    assert tint("#000000") == "#bfbfbf"
    assert tint("#ffffff") == "#ffffff"
    assert palette(GEO.destination("AZORES")) == Palette("#0e7490", tint("#0e7490"))


@pytest.mark.parametrize("bad", ["teal", "#0e749", "#0e7490ff", "0e7490", 123])
def test_invalid_color_is_rejected(bad):
    data = {**DATA, "destinations": {"A": {"name": "A", "kind": "city", "airports": ["PDL"], "color": bad}}}
    with pytest.raises(ValueError, match="color"):
        Geo.from_dict(data)


def test_every_seeded_destination_has_its_own_color():
    geo = load_geo()
    colors = [palette(d).color for d in geo.destinations()]
    assert len(colors) == len(set(colors))
    assert palette(geo.destination("MADEIRA")).color == "#15803d"
