from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import Dict, Iterable, List, Literal, Optional, Tuple

from apis.flights_api import Flight

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
        top_hours_counts += [0] * (peak_hours_per_day - len(top_hours_counts)) # fill with zeros if there are fewer than peak_hours_per_day counts
        daily_peak_averages.append(sum(top_hours_counts) / peak_hours_per_day) # average the top N counts for the day

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


def congestion_level(
    pct: Optional[float], low_below: float, moderate_below: float, high_up_to: float
) -> CongestionLevel:
    #CR: modify this function so it would get a CongestionLevelSettings object instead of 3 floats, and use the fields from that object.
    #CR: is there a way to make this function prettier? if so - do it. if not, delete this comment
    if pct is None:
        return "unknown"
    if pct < low_below:
        return "low"
    if pct < moderate_below:
        return "moderate"
    if pct <= high_up_to:
        return "high"
    return "over_capacity"


#CR: will be deleted or changed, see explanation in airport_analyzer.py
def long_haul_share(flights: List[Flight], min_hours: float) -> Tuple[int, int, float]:
    """Returns (long_haul_count, total, pct_long_haul)."""
    total = len(flights)
    if total == 0:
        return 0, 0, 0.0

    threshold = timedelta(hours=min_hours)
    long_haul_count = sum(1 for f in flights if (f.arrival_time - f.departure_time) > threshold)
    return long_haul_count, total, (long_haul_count / total) * 100


def unmet_demand(hourly: Dict[datetime, int], capacity: int, practical_pct: float) -> Tuple[int, float, int]:
    """Returns (hours_above_practical_capacity, pct_of_active_hours, excess_flights).

    Practical capacity = capacity * practical_pct / 100. An "active" hour is one with at
    least one flight. If capacity is unknown (<= 0), unmet demand can't be assessed.
    """
    if capacity <= 0:
        return 0, 0.0, 0

    practical_capacity = capacity * (practical_pct / 100)
    active_hours = [count for count in hourly.values() if count > 0]
    if not active_hours:
        return 0, 0.0, 0

    over_capacity_hours = [count for count in active_hours if count >= practical_capacity]
    hours_above = len(over_capacity_hours)
    pct_of_active_hours = (hours_above / len(active_hours)) * 100
    excess_flights = round(sum(count - practical_capacity for count in over_capacity_hours))

    return hours_above, pct_of_active_hours, excess_flights
