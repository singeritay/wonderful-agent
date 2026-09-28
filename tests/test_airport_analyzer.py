from datetime import datetime, timedelta
from unittest.mock import patch

import pytest

from apis.airports_api import Airport, AirportNotFoundError
from apis.flights_api import Direction, Flight
from airports_agent.analytics.airport_analyzer import AirportAnalyzer
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


def make_analyzer(airport, get_departures=None, get_arrivals=None, settings=None):
    with patch("airports_agent.analytics.airport_analyzer.FlightsAPI") as mock_flights_api_cls:
        mock_flights_api_cls.return_value.get_departures.side_effect = get_departures or (
            lambda code, begin, end: []
        )
        mock_flights_api_cls.return_value.get_arrivals.side_effect = get_arrivals or (
            lambda code, begin, end: []
        )
        analyzer = AirportAnalyzer(airport, settings or make_settings())
    return analyzer, mock_flights_api_cls.return_value


def test_constructor_accepts_airport_object_directly():
    airport = Airport(code="KBOS", name="Boston Logan", region="US-MA", num_of_runways=2)
    analyzer, _ = make_analyzer(airport)

    assert analyzer.airport == airport
    assert analyzer.airport_code == "KBOS"


def test_constructor_resolves_airport_code_via_airports_api():
    airport = Airport(code="KBOS", name="Boston Logan", region="US-MA", num_of_runways=2)
    with patch("airports_agent.analytics.airport_analyzer.AirportsAPI") as mock_airports_api_cls, \
         patch("airports_agent.analytics.airport_analyzer.FlightsAPI"):
        mock_airports_api_cls.return_value.get_airport_by_code.return_value = airport
        analyzer = AirportAnalyzer("KBOS", make_settings())

    assert analyzer.airport == airport
    assert analyzer.airport_code == "KBOS"
    mock_airports_api_cls.return_value.get_airport_by_code.assert_called_once_with("KBOS")


def test_constructor_propagates_not_found():
    with patch("airports_agent.analytics.airport_analyzer.AirportsAPI") as mock_airports_api_cls, \
         patch("airports_agent.analytics.airport_analyzer.FlightsAPI"):
        mock_airports_api_cls.return_value.get_airport_by_code.side_effect = AirportNotFoundError("nope")
        with pytest.raises(AirportNotFoundError):
            AirportAnalyzer("ZZZZ", make_settings())


def test_get_congestion_worked_example():
    # 2 runways -> capacity 40/h; 10 departures in one hour, no arrivals -> peak avg 10 -> 25% -> low
    airport = Airport(code="KBOS", name="Boston Logan", region="US-MA", num_of_runways=2)
    analyzer, _ = make_analyzer(
        airport,
        get_departures=lambda code, begin, end: [make_flight(begin + timedelta(hours=8)) for _ in range(10)],
        settings=make_settings(window_days=1, peak_hours_per_day=1),
    )

    report = analyzer.get_congestion()

    assert report.capacity_per_hour == 40
    assert report.total_flights == 10
    assert report.peak_hour_average_flights_per_hour == 10
    assert report.utilization_percent == 25.0
    assert report.congestion_level == "low"


def test_get_congestion_uses_configured_window_days():
    airport = Airport(code="KBOS", name="Boston Logan", region="US-MA", num_of_runways=2)
    analyzer, _ = make_analyzer(airport, settings=make_settings(window_days=3))

    report = analyzer.get_congestion()

    assert report.window_end - report.window_start == timedelta(days=3)
    assert report.window_end.time() == datetime.min.time()


def test_constructor_window_days_override_takes_precedence_over_settings():
    airport = Airport(code="KBOS", name="Boston Logan", region="US-MA", num_of_runways=2)

    with patch("airports_agent.analytics.airport_analyzer.FlightsAPI"):
        analyzer = AirportAnalyzer(airport, make_settings(window_days=7), window_days=2)

    assert analyzer.window_days == 2
    assert analyzer.window_end - analyzer.window_start == timedelta(days=2)


def test_get_congestion_zero_runways_is_unknown():
    airport = Airport(code="ZZZ", name="No Runways", region="US-XX", num_of_runways=0)
    analyzer, _ = make_analyzer(airport)

    report = analyzer.get_congestion()

    assert report.utilization_percent is None
    assert report.congestion_level == "unknown"
    assert any("0 open runways" in a for a in report.assumptions)


def test_get_congestion_only_counts_relevant_movements():
    # departures use departure_time, arrivals use arrival_time - not both timestamps of every flight
    airport = Airport(code="KBOS", name="Boston Logan", region="US-MA", num_of_runways=1)
    analyzer, _ = make_analyzer(
        airport,
        get_departures=lambda code, begin, end: [
            make_flight(begin + timedelta(hours=1), begin + timedelta(hours=20))  # arrival elsewhere, ignored
        ],
        get_arrivals=lambda code, begin, end: [
            make_flight(begin + timedelta(hours=10), begin + timedelta(hours=2))  # departure elsewhere, ignored
        ],
        settings=make_settings(window_days=1, peak_hours_per_day=3),
    )

    report = analyzer.get_congestion()

    # 1 departure movement + 1 arrival movement = 2 total, not 4
    assert report.total_flights == 2


def test_get_capacity():
    airport = Airport(code="KSFO", name="SFO", region="US-CA", num_of_runways=2)  # capacity 40
    analyzer, _ = make_analyzer(
        airport,
        get_departures=lambda code, begin, end: [make_flight(begin + timedelta(hours=8)) for _ in range(40)],
        settings=make_settings(window_days=1, peak_hours_per_day=1, practical_capacity_pct=85),
    )

    report = analyzer.get_capacity()

    assert report.capacity_per_hour == 40
    assert report.practical_capacity_per_hour == 34.0
    assert report.peak_hour_average_flights_per_hour == 40


def test_get_capacity_unknown_when_no_runways():
    airport = Airport(code="ZZZ", name="No Runways", region="US-XX", num_of_runways=0)
    analyzer, _ = make_analyzer(airport)

    report = analyzer.get_capacity()

    assert report.capacity_per_hour == 0
    assert report.practical_capacity_per_hour is None


def test_get_flights_count_departures_includes_long_haul_count_from_one_fetch():
    airport = Airport(code="PANC", name="Anchorage", region="US-AK", num_of_runways=3)
    analyzer, flights_api = make_analyzer(
        airport,
        get_departures=lambda code, begin, end: [
            make_flight(begin, begin + timedelta(hours=6)),  # long haul
            make_flight(begin, begin + timedelta(hours=2)),  # short haul
        ],
        settings=make_settings(min_duration_hours=5),
    )

    report = analyzer.get_flights_count(Direction.DEPARTURES)

    assert report.direction == Direction.DEPARTURES
    assert report.total == 2
    assert report.long_haul_count == 1
    assert report.min_duration_hours == 5
    flights_api.get_departures.assert_called_once()
    flights_api.get_arrivals.assert_not_called()


def test_get_flights_count_arrivals_includes_long_haul_count_from_one_fetch():
    airport = Airport(code="PANC", name="Anchorage", region="US-AK", num_of_runways=3)
    analyzer, flights_api = make_analyzer(
        airport,
        get_arrivals=lambda code, begin, end: [
            make_flight(begin, begin + timedelta(hours=6)),  # long haul
            make_flight(begin, begin + timedelta(hours=2)),  # short haul
        ],
        settings=make_settings(min_duration_hours=5),
    )

    report = analyzer.get_flights_count(Direction.ARRIVALS)

    assert report.direction == Direction.ARRIVALS
    assert report.total == 2
    assert report.long_haul_count == 1
    flights_api.get_arrivals.assert_called_once()
    flights_api.get_departures.assert_not_called()
