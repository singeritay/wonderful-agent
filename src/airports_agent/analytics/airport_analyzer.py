from datetime import datetime, timedelta, timezone
from typing import List, Optional, Tuple, Union

from apis.airports_api import Airport, AirportsAPI
from apis.flights_api import Direction, Flight, FlightsAPI

from airports_agent.analytics import metrics
from airports_agent.analytics.reports import (
    CapacityReport,
    CongestionReport,
    FlightCountReport,
    LongHaulFlightCountReport,
)
from airports_agent.settings.settings import Settings, load_settings

BASE_ASSUMPTIONS = [
    "Flight counts come from OpenSky Network ADS-B data and may undercount actual traffic due to coverage gaps.",
    "Runway capacity assumes 20 flights/runway/hour, a simplification that ignores runway configuration, weather, and ATC procedures.",
    "Hours are bucketed in UTC, so 'per day' boundaries are UTC midnight, not local midnight.",
]

LONG_HAUL_ASSUMPTION = (
    "Long-haul duration is measured from OpenSky's firstSeen/lastSeen timestamps, which "
    "can be shortened by ADS-B coverage gaps (e.g. over oceans)."
)


class AirportAnalyzer:
    """Deterministic analysis for a single airport, over its configured analysis window."""

    def __init__(self, airport: Union[Airport, str], settings: Optional[Settings] = None):
        if isinstance(airport, str):
            airport = AirportsAPI().get_airport_by_code(airport)

        self.airport = airport
        self.airport_code = airport.code
        self._flights_api = FlightsAPI()
        self._settings = settings or load_settings()
        self.window_days = self._settings.analysis.window_days
        self.window_end = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        self.window_start = self.window_end - timedelta(days=self.window_days)


    def get_congestion(self) -> CongestionReport:
        total, average, peak = self._movement_stats()
        capacity = self._capacity_per_hour()
        utilization = metrics.utilization_percent(peak, capacity)
        level = metrics.congestion_level(utilization, self._settings.congestion_levels)

        return CongestionReport(
            airport=self.airport,
            window_start=self.window_start,
            window_end=self.window_end,
            total_flights=total,
            average_flights_per_hour=average,
            peak_hour_average_flights_per_hour=peak,
            capacity_per_hour=capacity,
            utilization_pct=utilization,
            congestion_level=level,
            assumptions=self._create_assumptions(),
        )

    def get_capacity(self) -> CapacityReport:
        _, average, peak = self._movement_stats()
        capacity = self._capacity_per_hour()
        practical_pct = self._settings.unmet_demand.practical_capacity_pct
        practical_capacity = capacity * (practical_pct / 100) if capacity > 0 else None

        return CapacityReport(
            airport=self.airport,
            window_start=self.window_start,
            window_end=self.window_end,
            capacity_per_hour=capacity,
            practical_capacity_per_hour=practical_capacity,
            average_flights_per_hour=average,
            peak_hour_average_flights_per_hour=peak,
            assumptions=self._create_assumptions(),
        )

    #CR: change those 4 functions to get_flights_count(direction, long_haul:bool=False) and return the appropriate report
    #this function will be called only by the MCP
    def get_departure_count(self) -> FlightCountReport:
        return self._flight_count_report(Direction.DEPARTURES)

    def get_arrival_count(self) -> FlightCountReport:
        return self._flight_count_report(Direction.ARRIVALS)

    def get_long_haul_departure_count(self) -> LongHaulFlightCountReport:
        return self._long_haul_count_report(Direction.DEPARTURES)

    def get_long_haul_arrival_count(self) -> LongHaulFlightCountReport:
        return self._long_haul_count_report(Direction.ARRIVALS)

    def _flight_count_report(self, direction: Direction) -> FlightCountReport:
        flights = self._get_flights(direction)
        return FlightCountReport(
            airport=self.airport,
            window_start=self.window_start,
            window_end=self.window_end,
            direction=direction,
            total=len(flights),
            assumptions=self._create_assumptions(),
        )

    def _long_haul_count_report(self, direction: Direction) -> LongHaulFlightCountReport:
        flights = self._get_flights(direction)
        min_hours = self._settings.long_haul.min_duration_hours
        long_haul_count = metrics.count_long_haul(flights, min_hours)

        return LongHaulFlightCountReport(
            airport=self.airport,
            window_start=self.window_start,
            window_end=self.window_end,
            direction=direction,
            long_haul_count=long_haul_count,
            min_duration_hours=min_hours,
            assumptions=self._create_assumptions() + [LONG_HAUL_ASSUMPTION],
        )

    #CR: rename to flight_stats, also, add better naming for variables (also where this function is called change the name)
    def _movement_stats(self) -> Tuple[int, float, float]:
        """Returns (total_movements, average_flights_per_hour, peak_hour_average_flights_per_hour)."""
        times = self._movement_times()
        hourly = metrics.count_flights_by_hour(times)
        total = len(times)
        average = metrics.average_per_hour(total, self.window_days)
        peak = metrics.peak_hour_average(hourly, self.window_days, self._settings.analysis.peak_hours_per_day)
        return total, average, peak

    #CR: rename to flights_times
    def _movement_times(self) -> List[datetime]:
        """Departure timestamps for flights leaving this airport, plus arrival timestamps for
        flights landing at it."""
        departures = self._get_flights(Direction.DEPARTURES)
        arrivals = self._get_flights(Direction.ARRIVALS)
        return [f.departure_time for f in departures] + [f.arrival_time for f in arrivals]

    def _get_flights(self, direction: Direction) -> List[Flight]:
        if direction is Direction.DEPARTURES:
            return self._flights_api.get_departures(self.airport_code, self.window_start, self.window_end)
        return self._flights_api.get_arrivals(self.airport_code, self.window_start, self.window_end)

    #CR: don't need this function, just call metrics.capacity_per_hour directly
    def _capacity_per_hour(self) -> int:
        return metrics.capacity_per_hour(
            self.airport.num_of_runways, self._settings.capacity.flights_per_runway_per_hour
        )

    def _create_assumptions(self) -> List[str]:
        assumptions = list(BASE_ASSUMPTIONS)
        if self.airport.num_of_runways == 0:
            assumptions.append(
                "This airport has 0 open runways in our data, so capacity/utilization cannot be computed."
            )
        return assumptions
