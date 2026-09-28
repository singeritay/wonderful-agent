from datetime import datetime, timedelta
from unittest.mock import MagicMock

import pytest

from apis.airports_api import Airport
from apis.flights_api import Flight
from airports_agent.analytics.airport_analyzer import AirportAnalyzer, AirportNotFoundError
from airports_agent.settings.settings import (
    AnalysisSettings,
    CapacitySettings,
    CongestionLevelSettings,
    LlmSettings,
    LongHaulSettings,
    Settings,
    UnmetDemandSettings,
)


def make_settings(
    window_days=1,
    peak_hours_per_day=1,
    capacity_per_runway=20,
    low_below=50,
    moderate_below=80,
    high_up_to=100,
    min_duration_hours=5,
    practical_capacity_pct=85,
):
    return Settings(
        data_dir="data",
        capacity=CapacitySettings(flights_per_runway_per_hour=capacity_per_runway),
        analysis=AnalysisSettings(window_days=window_days, peak_hours_per_day=peak_hours_per_day),
        congestion_levels=CongestionLevelSettings(
            low_below=low_below, moderate_below=moderate_below, high_up_to=high_up_to
        ),
        long_haul=LongHaulSettings(min_duration_hours=min_duration_hours),
        unmet_demand=UnmetDemandSettings(practical_capacity_pct=practical_capacity_pct),
        llm=LlmSettings(model="test-model"),
    )


def make_flight(departure_time, arrival_time=None, dep_code="KBOS", arr_code="KJFK"):
    return Flight(
        id="abc123",
        call_sign="UAL123",
        departure_airport_code=dep_code,
        arrival_airport_code=arr_code,
        departure_time=departure_time,
        arrival_time=arrival_time or departure_time + timedelta(hours=1),
    )


def make_analyzer(airport=None, get_departures=None, get_arrivals=None, settings=None):
    airports_api = MagicMock()
    airports_api.get_airport_by_code.return_value = airport

    flights_api = MagicMock()
    flights_api.get_departures.side_effect = get_departures or (lambda code, begin, end: [])
    flights_api.get_arrivals.side_effect = get_arrivals or (lambda code, begin, end: [])

    return AirportAnalyzer(airports_api, flights_api, settings or make_settings()), airports_api, flights_api


def test_get_congestion_worked_example():
    # 2 runways -> capacity 40/h; 10 departures in one hour, no arrivals -> peak avg 10 -> 25% -> low
    airport = Airport(code="KBOS", name="Boston Logan", region="US-MA", num_of_runways=2)
    analyzer, _, _ = make_analyzer(
        airport=airport,
        get_departures=lambda code, begin, end: [make_flight(begin + timedelta(hours=8)) for _ in range(10)],
        settings=make_settings(window_days=1, peak_hours_per_day=1),
    )

    report = analyzer.get_congestion("KBOS")

    assert report.capacity_per_hour == 40
    assert report.total_flights == 10
    assert report.peak_hour_average_flights_per_hour == 10
    assert report.utilization_pct == 25.0
    assert report.congestion_level == "low"


def test_get_congestion_uses_configured_window_days():
    airport = Airport(code="KBOS", name="Boston Logan", region="US-MA", num_of_runways=2)
    analyzer, _, _ = make_analyzer(airport=airport, settings=make_settings(window_days=3))

    report = analyzer.get_congestion("KBOS")

    assert report.window_end - report.window_start == timedelta(days=3)
    assert report.window_end.time() == datetime.min.time()


def test_get_congestion_zero_runways_is_unknown():
    airport = Airport(code="ZZZ", name="No Runways", region="US-XX", num_of_runways=0)
    analyzer, _, _ = make_analyzer(airport=airport)

    report = analyzer.get_congestion("ZZZ")

    assert report.utilization_pct is None
    assert report.congestion_level == "unknown"
    assert any("0 open runways" in a for a in report.assumptions)


def test_get_congestion_airport_not_found_raises():
    analyzer, _, _ = make_analyzer(airport=None)

    with pytest.raises(AirportNotFoundError):
        analyzer.get_congestion("ZZZZ")


def test_get_congestion_only_counts_relevant_movements():
    # departures use departure_time, arrivals use arrival_time - not both timestamps of every flight
    airport = Airport(code="KBOS", name="Boston Logan", region="US-MA", num_of_runways=1)
    analyzer, _, flights_api = make_analyzer(
        airport=airport,
        get_departures=lambda code, begin, end: [
            make_flight(begin + timedelta(hours=1), begin + timedelta(hours=20))  # arrival elsewhere, ignored
        ],
        get_arrivals=lambda code, begin, end: [
            make_flight(begin + timedelta(hours=10), begin + timedelta(hours=2))  # departure elsewhere, ignored
        ],
        settings=make_settings(window_days=1, peak_hours_per_day=3),
    )

    report = analyzer.get_congestion("KBOS")

    # 1 departure movement + 1 arrival movement = 2 total, not 4
    assert report.total_flights == 2


def test_rank_expansion_candidates_orders_by_utilization_then_flights_then_unknown_last():
    airport_high = Airport(code="AAA", name="High", region="US-MA", num_of_runways=1)
    airport_low = Airport(code="BBB", name="Low", region="US-MA", num_of_runways=1)
    airport_unknown = Airport(code="CCC", name="Unknown", region="US-MA", num_of_runways=0)

    counts = {"AAA": 15, "BBB": 5, "CCC": 0}

    airports_api = MagicMock()
    airports_api.get_airports_per_region.return_value = [airport_high, airport_low, airport_unknown]
    airports_api.get_airport_by_code.side_effect = lambda code: {
        "AAA": airport_high, "BBB": airport_low, "CCC": airport_unknown
    }[code]

    flights_api = MagicMock()
    flights_api.get_departures.side_effect = lambda code, begin, end: [
        make_flight(begin + timedelta(hours=8)) for _ in range(counts[code])
    ]
    flights_api.get_arrivals.side_effect = lambda code, begin, end: []

    analyzer = AirportAnalyzer(airports_api, flights_api, make_settings(window_days=1, peak_hours_per_day=1))
    entries = analyzer.rank_expansion_candidates(["US-MA"])

    assert [e.airport.code for e in entries] == ["AAA", "BBB", "CCC"]
    assert entries[0].utilization_pct == 75.0
    assert entries[1].utilization_pct == 25.0
    assert entries[2].utilization_pct is None


def test_rank_expansion_candidates_respects_limit():
    airport_a = Airport(code="AAA", name="A", region="US-MA", num_of_runways=1)
    airport_b = Airport(code="BBB", name="B", region="US-MA", num_of_runways=1)

    airports_api = MagicMock()
    airports_api.get_airports_per_region.return_value = [airport_a, airport_b]
    airports_api.get_airport_by_code.side_effect = lambda code: {"AAA": airport_a, "BBB": airport_b}[code]

    flights_api = MagicMock()
    flights_api.get_departures.side_effect = lambda code, begin, end: []
    flights_api.get_arrivals.side_effect = lambda code, begin, end: []

    analyzer = AirportAnalyzer(airports_api, flights_api, make_settings())
    entries = analyzer.rank_expansion_candidates(["US-MA"], limit=1)

    assert len(entries) == 1


def test_get_long_haul_share():
    airport = Airport(code="PANC", name="Anchorage", region="US-AK", num_of_runways=3)
    analyzer, _, _ = make_analyzer(
        airport=airport,
        get_departures=lambda code, begin, end: [
            make_flight(begin, begin + timedelta(hours=6)),
            make_flight(begin, begin + timedelta(hours=2)),
        ],
        settings=make_settings(min_duration_hours=5),
    )

    report = analyzer.get_long_haul_share("PANC")

    assert report.long_haul_flights == 1
    assert report.total_departures == 2
    assert report.long_haul_pct == 50.0
    assert report.min_duration_hours == 5


def test_get_unmet_demand():
    airport = Airport(code="KSFO", name="SFO", region="US-CA", num_of_runways=2)  # capacity 40
    analyzer, _, _ = make_analyzer(
        airport=airport,
        get_departures=lambda code, begin, end: [make_flight(begin + timedelta(hours=8)) for _ in range(40)],
        settings=make_settings(window_days=1, peak_hours_per_day=1, practical_capacity_pct=85),
    )

    report = analyzer.get_unmet_demand("KSFO")

    assert report.capacity_per_hour == 40
    assert report.practical_capacity_per_hour == 34.0
    assert report.hours_at_or_above_practical_capacity == 1
    assert report.pct_of_active_hours_over_capacity == 100.0
    assert report.excess_flights == 6


def test_get_unmet_demand_unknown_capacity():
    airport = Airport(code="ZZZ", name="No Runways", region="US-XX", num_of_runways=0)
    analyzer, _, _ = make_analyzer(airport=airport)

    report = analyzer.get_unmet_demand("ZZZ")

    assert report.practical_capacity_per_hour is None
    assert report.hours_at_or_above_practical_capacity == 0


def test_search_airports_delegates_to_airports_api():
    airports_api = MagicMock()
    airports_api.search_airports.return_value = [
        Airport(code="KBOS", name="Boston", region="US-MA", num_of_runways=2)
    ]
    flights_api = MagicMock()
    analyzer = AirportAnalyzer(airports_api, flights_api, make_settings())

    result = analyzer.search_airports("boston")

    airports_api.search_airports.assert_called_once_with("boston")
    assert result[0].code == "KBOS"
