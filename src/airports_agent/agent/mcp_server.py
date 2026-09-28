"""MCP server exposing airport data and AirportAnalyzer reports as agent tools.

Airport codes are ICAO idents (4 letters, e.g. "KLAX", "KBOS") - not IATA codes ("LAX", "BOS").
When given a name or city instead of a code, call search_airports first to resolve it.

Every analysis report includes an `assumptions` field listing the simplifications behind its
numbers (data source limitations, the capacity formula used, UTC bucketing, etc.) - always
surface these when answering questions from a report.
"""

from typing import List, Optional, Union

from mcp.server.fastmcp import FastMCP

from apis.airports_api import Airport, AirportNotFoundError, AirportsAPI
from apis.flights_api import Direction
from airports_agent.analytics.airport_analyzer import AirportAnalyzer
from airports_agent.analytics.reports import (
    CapacityReport,
    CongestionReport,
    FlightsCountResult,
)

mcp = FastMCP("airports-agent")


@mcp.tool()
def search_airports(query: str) -> List[Airport]:
    """Find US airports (large/medium, per OurAirports data) by name, city, ICAO ident, or IATA
    code. Use this first whenever the user gives a name or city rather than an ICAO code - e.g.
    "Boston Logan", "JFK", "Anchorage" - to resolve it to an Airport with its ICAO `code`.

    Matching: an exact ICAO/IATA code match wins; otherwise falls back to a case-insensitive
    substring match on name or municipality. Returns [] if nothing matches.
    """
    return AirportsAPI().search_airports(query)


@mcp.tool()
def get_airport_by_name(airport_name: str) -> Union[Airport, str]:
    """Look up an airport by its exact official name (e.g. "General Edward Lawrence Logan
    International Airport"). Names must match exactly - if you only have a casual name or city
    (e.g. "Boston Logan", "Boston"), use search_airports instead. On no exact match, returns a
    message telling you to use search_airports rather than raising.
    """
    try:
        return AirportsAPI().get_airport_by_name(airport_name)
    except AirportNotFoundError:
        return f"No exact name match for '{airport_name}'. Use search_airports instead."


@mcp.tool()
def get_airports_by_region(region: Union[str, List[str]]) -> List[Airport]:
    """List all US airports in one or more ISO 3166-2 region codes, e.g. "US-CA" (California),
    "US-MA" (Massachusetts). Each code is a single US state - there's no informal-grouping code,
    so for a grouping like "New England" pass the list of state codes in one call, e.g.
    ["US-ME", "US-NH", "US-VT", "US-MA", "US-RI", "US-CT"].
    """
    return AirportsAPI().get_airports_per_region(region)


@mcp.tool()
def get_region_by_airport(airport_code: str) -> str:
    """Return the ISO 3166-2 region code (e.g. "US-CA") an airport belongs to, given its ICAO
    code.
    """
    return AirportsAPI().get_airport_by_code(airport_code).region


@mcp.tool()
def get_airport_info(airport_code: str) -> Airport:
    """Return full airport details (name, region, runway count, IATA code, municipality) for an
    ICAO airport code.
    """
    return AirportsAPI().get_airport_by_code(airport_code)


@mcp.tool()
def get_airport_flights_count(
    airport_code: str,
    last_n_days: Optional[int] = None,
    direction: Optional[Direction] = None,
) -> FlightsCountResult:
    """Count an airport's flights over a trailing window, split by direction (optional), including both the
    plain count and the long-haul count in the same call.

    - direction=None (default) returns both `departures` and `arrivals`; passing a direction
      returns only that one (the other field is null).
    - last_n_days overrides the default analysis window (from settings) with a custom trailing
      window ending today (UTC).
    - Each populated direction is a full FlightCountReport: `total` (all flights), `long_haul_
      count` (flights whose duration exceeds `min_duration_hours` - duration is estimated from
      ADS-B firstSeen/lastSeen and can be shortened by coverage gaps, e.g. over oceans, which can
      undercount long-haul flights), and `assumptions`. To get "what % of flights are long-haul",
      divide long_haul_count by total yourself - always surface `assumptions` when answering.
    """
    analyzer = AirportAnalyzer(airport_code, window_days=last_n_days)
    return FlightsCountResult(
        departures=(
            analyzer.get_flights_count(Direction.DEPARTURES)
            if direction in (None, Direction.DEPARTURES)
            else None
        ),
        arrivals=(
            analyzer.get_flights_count(Direction.ARRIVALS)
            if direction in (None, Direction.ARRIVALS)
            else None
        ),
    )


@mcp.tool()
def get_congestion_level(airport_code: str, last_n_days: Optional[int] = None) -> CongestionReport:
    """Assess how congested an airport is over a trailing window, relative to its runway
    capacity.

    Returns the full CongestionReport, not just the level string, so you can explain the
    reasoning: `capacity_per_hour` (theoretical, from runway count - a runway can include 20 departures / arrivals per hour),
    `peak_hour_average_flights_per_hour` (the busiest-hours average actually observed),
    `utilization_percent` (peak divided by capacity, null when capacity is 0), and `congestion_level` ("low"/"moderate"/"high"/
    "over_capacity"/"unknown"). last_n_days overrides the default analysis window from settings.
    Always surface `assumptions` (capacity formula, data source, UTC bucketing) when answering.
    """
    return AirportAnalyzer(airport_code, window_days=last_n_days).get_congestion()


@mcp.tool()
def get_airport_capacity(airport_code: str) -> CapacityReport:
    """Compare an airport's theoretical vs. practical vs. actual-observed throughput, to help
    judge whether it's under or over capacity.

    Returns `capacity_per_hour` (theoretical max, from runway count), `practical_capacity_per_
    hour` (a configured percentage of theoretical - the realistic sustainable ceiling),
    `average_flights_per_hour` (actual observed average) and `peak_hour_average_flights_per_hour`
    (actual observed peak). This tool deliberately does NOT conclude "over capacity" itself -
    compare the observed numbers against both capacity figures and explain your reasoning.
    Always surface `assumptions`.
    """
    return AirportAnalyzer(airport_code).get_capacity()


if __name__ == "__main__":
    mcp.run()
