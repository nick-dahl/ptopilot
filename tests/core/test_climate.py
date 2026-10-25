import json
from pathlib import Path

import httpx
import pytest

from ptopilot.core.climate import monthly_climate, rate_months
from ptopilot.sources.base import SourceUnavailable
from ptopilot.sources.climate import fetch_climate

FIXTURES = Path(__file__).parents[1] / "sources" / "fixtures"
TOKYO = json.loads((FIXTURES / "real_open_meteo_tokyo_2011_2020.json").read_text())


def test_monthly_climate_from_the_real_tokyo_record():
    months = monthly_climate(TOKYO)
    assert len(months) == 12
    assert 7 < months[0].tmax_mean < 10 and 27 < months[7].tmax_mean < 31  # Jan cold, Aug hot


def test_rating_rules():
    ratings, notes = rate_months(monthly_climate(TOKYO))
    assert ratings[0] == "avoid"  # January, ~8 C max
    assert ratings[4] == "good"  # May, ~21 C, ~11 wet days
    assert ratings[9] == "good"  # October, ~21 C, ~12.5 wet days
    assert ratings[5] == "shoulder"  # June, ~24 C but ~16 wet days
    assert ratings[3] == "shoulder"  # April, ~17 C
    assert notes[1] == "~8°C, 6 wet days"  # format: "~{tmax:.0f}°C, {wet:.0f} wet days"


def test_fetch_failures_are_source_unavailable():
    client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(503)))
    with pytest.raises(SourceUnavailable):
        fetch_climate(35.5, 139.8, client)


def _trimmed(keep):
    daily = TOKYO["daily"]
    idx = [i for i, d in enumerate(daily["time"]) if keep(d)]
    return {"daily": {k: [v[i] for i in idx] for k, v in daily.items()}}


def test_a_payload_missing_months_is_source_unavailable():
    with pytest.raises(SourceUnavailable):
        monthly_climate(_trimmed(lambda d: int(d[5:7]) <= 6))


def test_a_month_with_all_null_temperatures_is_source_unavailable():
    payload = _trimmed(lambda d: True)
    daily = payload["daily"]
    for i, d in enumerate(daily["time"]):
        if d[5:7] == "03":
            daily["temperature_2m_max"][i] = None
    with pytest.raises(SourceUnavailable):
        monthly_climate(payload)
