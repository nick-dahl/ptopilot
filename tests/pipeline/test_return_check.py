from datetime import date, datetime

from ptopilot.core.airports import AirportCatalog, CatalogAirport
from ptopilot.core.geo import Destination, Geo, TravelRule
from ptopilot.pipeline.return_check import check_return
from ptopilot.sources.base import ExactQuery, ExactResult, FlightOption, SourceUnavailable

DEPART = date(2027, 6, 20)
TOKYO = Destination("TYO", "Tokyo", "city", ("HND", "NRT"), "JP", "asia")


def _ap(code, city, lat):
    return CatalogAirport(code, code, city, "XX", "EU", lat, 0.0, "medium")


CATALOG = AirportCatalog(
    [_ap("NRT", "Tokyo", 35.7), _ap("HND", "Tokyo", 35.5), _ap("MAD", "Madrid", 40.5)], {}
)
GEO = Geo({}, {"TYO": TOKYO}, {}, TravelRule(1.0, 3), CATALOG)


def option(price, duration, layover=None, airport=None):
    return FlightOption(
        price=price,
        carrier="XX",
        stops=1 if layover else 0,
        duration_min=duration,
        outbound_departure=datetime(2027, 6, 20, 9, 0),
        longest_layover_min=layover,
        longest_layover_airport=airport,
    )


class FakeSource:
    supports_open_jaw = False

    def __init__(self, name, options=(), error=None):
        self.name = name
        self.options = tuple(options)
        self.error = error
        self.seen: list[ExactQuery] = []

    def exact_search(self, query):
        self.seen.append(query)
        if self.error:
            raise self.error
        return ExactResult(self.name, query, query.currency, self.options, "")


def run(sources, price=1000.0, median=None, confident=False, from_airport="NRT"):
    return check_return(
        sources,
        home="ORD",
        from_airport=from_airport,
        depart=DEPART,
        destination=TOKYO,
        geo=GEO,
        catalog=CATALOG,
        price=price,
        typical_median=median,
        confident=confident,
    )


def test_return_passes_when_any_option_is_fine():
    src = FakeSource("google_flights", [option(900, 1500, 700, "MAD"), option(1200, 800)])
    assert run([src]) == ("pass", None)


def test_return_fails_with_the_cheapest_options_reason():
    src = FakeSource(
        "google_flights",
        [option(1200, 800), option(2000, 800, 600, "MAD"), option(700, 800, 700, "MAD")],
    )
    # the nonstop is fine, so make every option bad: drop it
    src.options = (option(2000, 900, 600, "MAD"), option(700, 900, 700, "MAD"))
    verdict, note = run([src])
    assert verdict == "fail"
    assert note == "11h 40m layover in Madrid"


def test_return_uses_the_round_trip_discount_to_forgive():
    moderate = option(900, 800, 330, "MAD")
    assert run([FakeSource("google_flights", [moderate])]) == ("fail", "5h 30m layover in Madrid")
    assert run([FakeSource("google_flights", [moderate])], price=550, median=1000, confident=True) == (
        "pass",
        None,
    )
    assert (
        run([FakeSource("google_flights", [moderate])], price=550, median=1000, confident=False)[0] == "fail"
    )


def test_return_is_unknown_when_sources_fail():
    down = FakeSource("google_flights", error=SourceUnavailable("blocked"))
    empty = FakeSource("serpapi", [])
    assert run([down, empty]) == ("unknown", None)
    assert run([]) == ("unknown", None)


def test_return_falls_back_to_the_next_source_when_the_first_fails():
    down = FakeSource("google_flights", error=SourceUnavailable("blocked"))
    good = FakeSource("serpapi", [option(900, 800)])
    assert run([down, good]) == ("pass", None)


def test_return_check_makes_one_search_per_source():
    a = FakeSource("google_flights", error=SourceUnavailable("blocked"))
    b = FakeSource("serpapi", [option(900, 800, 700, "MAD")])
    run([a, b])
    assert len(a.seen) == 1 and len(b.seen) == 1
    q = b.seen[0]
    assert (q.origin, q.dest_airport, q.depart_date, q.one_way) == ("NRT", "ORD", DEPART, True)


def test_ground_time_is_measured_at_the_departure_airport():
    src = FakeSource("google_flights", [option(900, 800)])
    verdict, note = run([src], from_airport="MAD")
    assert verdict == "fail"
    assert note.startswith("Lands ~")
    assert note.endswith("from Tokyo")


def test_first_source_with_options_decides():
    first = FakeSource("google_flights", [option(900, 800)])
    second = FakeSource("serpapi", [option(900, 800)])
    run([first, second])
    assert second.seen == []


def test_forgiveness_is_judged_on_the_exact_price_not_a_rounded_discount():
    moderate = option(900, 800, 330, "MAD")

    def verdict(price):
        return run([FakeSource("google_flights", [moderate])], price=price, median=100.0, confident=True)[0]

    assert verdict(60.0) == "pass"
    assert verdict(60.4) == "fail"  # 39.6% below rounds to 40, but is not 40% below


def test_an_unconfident_baseline_never_forgives():
    moderate = option(900, 800, 330, "MAD")
    assert (
        run([FakeSource("google_flights", [moderate])], price=10, median=100.0, confident=False)[0] == "fail"
    )
