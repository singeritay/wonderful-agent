from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import Dict, Iterable, List, Literal, Optional

from apis.flights_api import Flight
from airports_agent.settings.settings import CongestionLevelSettings

CongestionLevel = Literal["low", "moderate", "high", "over_capacity", "unknown"]


def count_flights_by_hour(flights_times: Iterable[datetime]) -> Dict[datetime, int]:
    """Bucket timestamps into UTC hour buckets, e.g. 14:37 -> 14:00."""
    counts: Dict[datetime, int] = {}
    for t in flights_times:
        hour = t.replace(minute=0, second=0, microsecond=0)
        counts[hour] = counts.get(hour, 0) + 1
    return counts


def peak_hour_average(flights_by_hour: Dict[datetime, int], window_days: int, peak_hours_per_day: int) -> float:
    """Average of the top `peak_hours_per_day` hourly counts per day, averaged over `window_days`.
    Hours (and whole days) with no flights are treated as 0.
    """
    if window_days <= 0 or peak_hours_per_day <= 0:
        return 0.0

    flights_by_day: Dict[date, List[int]] = defaultdict(list)
    for hour, count in flights_by_hour.items():
        flights_by_day[hour.date()].append(count)

    daily_peak_averages = []
    for day_counts in flights_by_day.values():
        top_hours_counts = sorted(day_counts, reverse=True)[:peak_hours_per_day]
        top_hours_counts += [0] * (peak_hours_per_day - len(top_hours_counts))  # fill with zeros if there are fewer than peak_hours_per_day counts
        daily_peak_averages.append(sum(top_hours_counts) / peak_hours_per_day)  # average the top N counts for the day

    return sum(daily_peak_averages) / window_days


def average_per_hour(total_flights: int, window_days: int) -> float:
    if window_days <= 0:
        return 0.0
    return total_flights / (window_days * 24)


def capacity_per_hour(runways: int, per_runway: int) -> int:
    return runways * per_runway


def utilization_percent(flights_per_hour: float, capacity: int) -> Optional[float]:
    if capacity <= 0:
        return None
    return (flights_per_hour / capacity) * 100


def congestion_level(pct: Optional[float], levels: CongestionLevelSettings) -> CongestionLevel:
    if pct is None:
        return "unknown"
    if pct > levels.high_up_to:
        return "over_capacity"
    if pct >= levels.moderate_below:
        return "high"
    if pct >= levels.low_below:
        return "moderate"
    return "low"


def count_long_haul(flights: List[Flight], min_hours: float) -> int:
    """Number of flights whose duration (arrival_time - departure_time) exceeds `min_hours`."""
    threshold = timedelta(hours=min_hours)
    return sum(1 for f in flights if (f.arrival_time - f.departure_time) > threshold)
