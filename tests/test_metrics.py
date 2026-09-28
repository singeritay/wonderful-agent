from datetime import datetime, timedelta, timezone

from airports_agent.apis.flights_api import Flight
from airports_agent.analytics import metrics
from airports_agent.settings.settings import CongestionLevelSettings


def dt(hour, minute=0, day=1):
    return datetime(2026, 1, day, hour, minute, tzinfo=timezone.utc)


def make_flight(departure_time, arrival_time):
    return Flight(
        id="abc123",
        call_sign="UAL123",
        departure_airport_code="KBOS",
        arrival_airport_code="KJFK",
        departure_time=departure_time,
        arrival_time=arrival_time,
    )


def make_levels(low_below=50, moderate_below=80, high_up_to=100):
    return CongestionLevelSettings(low_below=low_below, moderate_below=moderate_below, high_up_to=high_up_to)


# --- count_flights_by_hour ---

def test_count_flights_by_hour_buckets_by_hour():
    times = [dt(8, 5), dt(8, 40), dt(9, 0), dt(8, 59)]
    counts = metrics.count_flights_by_hour(times)
    assert counts == {dt(8): 3, dt(9): 1}


def test_count_flights_by_hour_empty():
    assert metrics.count_flights_by_hour([]) == {}


# --- peak_hour_average ---

def test_peak_hour_average_sparse_hours_pad_with_zero():
    # Single day, only 2 hours have flights, but peak_hours_per_day=3
    hourly = {dt(8): 30, dt(9): 10}
    # top 3 of [30, 10, 0] = 40 / 3 per day, / 1 window day
    avg = metrics.peak_hour_average(hourly, window_days=1, peak_hours_per_day=3)
    assert avg == (30 + 10 + 0) / 3


def test_peak_hour_average_missing_day_counts_as_zero():
    # 3-day window, flights only on day 1
    hourly = {dt(8, day=1): 30, dt(9, day=1): 30, dt(10, day=1): 30}
    avg = metrics.peak_hour_average(hourly, window_days=3, peak_hours_per_day=3)
    # day 1 peak avg = 30; days 2 and 3 contribute 0
    assert avg == 30 / 3


def test_peak_hour_average_no_data():
    assert metrics.peak_hour_average({}, window_days=3, peak_hours_per_day=3) == 0.0


# --- average_per_hour ---

def test_average_per_hour():
    assert metrics.average_per_hour(total_flights=240, window_days=2) == 5.0


def test_average_per_hour_zero_window():
    assert metrics.average_per_hour(total_flights=10, window_days=0) == 0.0


# --- capacity_per_hour ---

def test_capacity_per_hour():
    assert metrics.capacity_per_hour(runways=2, per_runway=20) == 40


# --- utilization_percent ---

def test_utilization_percent_worked_example():
    # 2 runways, 10 flights/hour -> 10 / 40 = 25%
    capacity = metrics.capacity_per_hour(runways=2, per_runway=20)
    assert metrics.utilization_percent(10, capacity) == 25.0


def test_utilization_percent_zero_capacity_is_none():
    assert metrics.utilization_percent(10, 0) is None


# --- congestion_level ---

def test_congestion_level_worked_example_is_low():
    assert metrics.congestion_level(25.0, make_levels()) == "low"


def test_congestion_level_none_is_unknown():
    assert metrics.congestion_level(None, make_levels()) == "unknown"


def test_congestion_level_boundaries():
    levels = make_levels(low_below=50, moderate_below=80, high_up_to=100)
    assert metrics.congestion_level(49.99, levels) == "low"
    assert metrics.congestion_level(50, levels) == "moderate"
    assert metrics.congestion_level(79.99, levels) == "moderate"
    assert metrics.congestion_level(80, levels) == "high"
    assert metrics.congestion_level(100, levels) == "high"
    assert metrics.congestion_level(100.01, levels) == "over_capacity"


# --- count_long_haul ---

def test_count_long_haul_worked_example():
    flights = [
        make_flight(dt(0), dt(0) + timedelta(hours=6)),  # long haul
        make_flight(dt(0), dt(0) + timedelta(hours=2)),  # short haul
    ]
    assert metrics.count_long_haul(flights, min_hours=5) == 1


def test_count_long_haul_threshold_is_exclusive():
    flights = [make_flight(dt(0), dt(0) + timedelta(hours=5))]  # exactly 5h
    assert metrics.count_long_haul(flights, min_hours=5) == 0

    flights = [make_flight(dt(0), dt(0) + timedelta(hours=5, minutes=1))]  # just over 5h
    assert metrics.count_long_haul(flights, min_hours=5) == 1


def test_count_long_haul_no_flights():
    assert metrics.count_long_haul([], min_hours=5) == 0
