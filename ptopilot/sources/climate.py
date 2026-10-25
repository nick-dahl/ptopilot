"""Open-Meteo climate API: ten years of daily highs and rain for one place, fetched once when it is added."""

from __future__ import annotations

import httpx

from ptopilot import config
from ptopilot.sources.base import SourceUnavailable, snippet

API_URL = "https://climate-api.open-meteo.com/v1/climate"
TIMEOUT_S = 60


def fetch_climate(lat: float, lon: float, client: httpx.Client | None = None) -> dict:
    first, last = config.CLIMATE_YEARS
    params = {
        "latitude": lat,
        "longitude": lon,
        "start_date": f"{first}-01-01",
        "end_date": f"{last}-12-31",
        "models": config.CLIMATE_MODEL,
        "daily": "temperature_2m_max,precipitation_sum",
    }
    try:
        if client is None:
            with httpx.Client(timeout=TIMEOUT_S) as own:
                response = own.get(API_URL, params=params)
        else:
            response = client.get(API_URL, params=params)
        response.raise_for_status()
        payload = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise SourceUnavailable(f"open-meteo: {snippet(str(exc))}") from exc
    daily = payload.get("daily") if isinstance(payload, dict) else None
    if not isinstance(daily, dict) or not {"time", "temperature_2m_max", "precipitation_sum"} <= daily.keys():
        raise SourceUnavailable(f"open-meteo: unexpected payload: {snippet(str(payload))}")
    return payload
