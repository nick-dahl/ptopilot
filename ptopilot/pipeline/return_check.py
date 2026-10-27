"""Before an instant alert goes out, check the way home: a great fare with a miserable return is no deal."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from typing import Literal

from ptopilot.core.airports import AirportCatalog
from ptopilot.core.geo import Destination, Geo
from ptopilot.core.misery import assess, problems
from ptopilot.sources.base import ExactQuery, ExactSearchSource, FlightOption, SourceUnavailable

ReturnVerdict = Literal["pass", "fail", "unknown"]


def check_return(
    sources: Sequence[ExactSearchSource],
    *,
    home: str,
    from_airport: str,
    depart: date,
    destination: Destination,
    geo: Geo,
    catalog: AirportCatalog,
    price: float,
    typical_median: float | None,
    confident: bool,
) -> tuple[ReturnVerdict, str | None]:
    """Search `from_airport -> home` one-way on `depart` and judge every option.

    Sources are tried in order, one search each; the first that returns options decides. `price`,
    `typical_median` and `confident` come from the alert's round-trip fare and forgive one moderate
    problem as usual.
    Returns ("unknown", None) when no source produced options.
    """
    query = ExactQuery(from_airport, home, depart, depart, one_way=True)
    options: tuple[FlightOption, ...] = ()
    for source in sources:
        try:
            options = source.exact_search(query).options
        except SourceUnavailable:
            continue
        if options:
            break
    if not options:
        return "unknown", None

    fastest = min((o.duration_min for o in options if o.duration_min), default=None)
    ground = geo.ground_minutes(destination, from_airport)
    judged = []
    for o in sorted(options, key=lambda o: o.price):
        layover = catalog.get(o.longest_layover_airport) if o.longest_layover_airport else None
        found = problems(
            longest_layover_min=o.longest_layover_min,
            layover_city=layover.city if layover else None,
            duration_min=o.duration_min,
            fastest_min=fastest,
            ground_min=ground,
            destination_name=destination.name,
        )
        a = assess(found, price=price, typical_median=typical_median, typical_confident=confident)
        if a.verdict != "ruled_out":
            return "pass", None
        judged.append(a)
    return "fail", judged[0].note
