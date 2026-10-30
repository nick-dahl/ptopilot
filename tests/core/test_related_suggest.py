from ptopilot import config
from ptopilot.core.airports import AirportCatalog
from ptopilot.core.geo import Destination
from ptopilot.core.related import RelatedGroup, load_groups, suggest

CAT = AirportCatalog.load()


def _dest(code, *airports, zone="EUROPE", country="XX"):
    return Destination(code, code, "city", tuple(airports), country, zone)


def test_every_group_airport_is_a_large_or_medium_catalog_airport():
    groups = load_groups()
    assert len(groups) >= 10
    for g in groups:
        for code in g.airports:
            a = CAT.get(code)
            assert a is not None and a.size in ("large", "medium"), (g.name, code)


def test_required_groups_are_present():
    by_name = {g.name: g.airports for g in load_groups()}
    assert by_name["Central European capitals"] == ("BUD", "PRG", "VIE")
    assert by_name["Atlantic islands"] == ("PDL", "FNC", "TFS", "LPA")
    assert by_name["Patagonia"] == ("PUQ", "FTE", "USH")
    covered = {c for g in load_groups() for c in g.airports}
    assert {"LIS", "OPO", "SCQ", "HND", "NRT", "BKK", "HKT"} <= covered


def test_thematic_suggestions_are_the_other_group_members():
    out = suggest(_dest("BUD", "BUD"), CAT, load_groups())
    assert [(s.airport, s.kind, s.label) for s in out if s.kind == "theme"] == [
        ("PRG", "theme", "Central European capitals"),
        ("VIE", "theme", "Central European capitals"),
    ]


def test_near_airports_within_65_km_any_country_nearest_first():
    london = suggest(_dest("LON", "LHR", "LGW"), CAT, [])
    codes = [s.airport for s in london]
    assert "LTN" in codes and "STN" not in codes and "SEN" not in codes
    ltn = next(s for s in london if s.airport == "LTN")
    assert ltn.kind == "near" and ltn.label == f"~{round(ltn.km)} km away"
    assert [s.km for s in london] == sorted(s.km for s in london)
    paris = suggest(_dest("PAR", "CDG", "ORY"), CAT, [])
    assert "BVA" in [s.airport for s in paris]


def test_theme_comes_first_and_the_cap_is_five():
    groups = [RelatedGroup("Big", ("LHR", "BUD", "PRG", "VIE", "LIS", "OPO", "MAD"))]
    out = suggest(_dest("LON", "LHR", "LGW"), CAT, groups)
    assert len(out) == config.RELATED_MAX_SUGGESTIONS
    assert [s.kind for s in out] == ["theme"] * 5
    short = suggest(_dest("LON", "LHR", "LGW"), CAT, [RelatedGroup("G", ("LHR", "BUD"))])
    assert [(s.airport, s.kind) for s in short][:2] == [("BUD", "theme"), ("LCY", "near")]


def test_excluded_and_own_airports_are_never_suggested():
    out = suggest(_dest("LON", "LHR", "LGW"), CAT, load_groups(), exclude={"LTN"})
    assert "LTN" not in [s.airport for s in out] and not {"LHR", "LGW"} & {s.airport for s in out}
    out = suggest(_dest("BUD", "BUD"), CAT, load_groups(), exclude=["PRG"])
    assert [s.airport for s in out] == ["VIE"]
    dup = suggest(_dest("LON", "LHR"), CAT, [RelatedGroup("G", ("LHR", "LTN"))])
    assert [(s.airport, s.kind) for s in dup if s.airport == "LTN"] == [("LTN", "theme")]


def test_small_airports_are_not_suggested_as_near():
    assert [a.code for _, a in CAT.within("BES", 65, frozenset({"small"}))] == ["OUI"]  # a small one is near
    assert "OUI" not in [s.airport for s in suggest(_dest("BRE", "BES"), CAT, [])]
