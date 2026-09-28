from datetime import datetime, timedelta, timezone
from typing import List, Optional, Tuple, Union

from airports_agent.apis.airports_api import Airport, AirportsAPI
from airports_agent.apis.flights_api import Direction, Flight, FlightsAPI

from airports_agent.analytics import metrics
from airports_agent.analytics.reports import (
    CapacityReport,
    CongestionReport,
    FlightCountReport,
)
from airports_agent.settings.settings import Settings, load_settings

BASE_ASSUMPTIONS = [
    "Flight counts come from OpenSky Network ADS-B data and may undercount actual traffic due to coverage gaps.",
    "Runway capacity assumes a fixed amount of flights (usually 20)/runway/hour, a simplification that ignores runway configuration, weather, and ATC procedures.",
    "Hours are bucketed in UTC, so 'per day' boundaries are UTC midnight, not local midnight.",
]

LONG_HAUL_ASSUMPTION = (
    "Long-haul duration is measured from OpenSky's firstSeen/lastSeen timestamps, which "
    "can be shortened by ADS-B coverage gaps (e.g. over oceans)."
)


class AirportAnalyzer:
    """Deterministic analysis for a single airport, over its configured analysis window."""

    def __init__(
        self,
        airport: Union[Airport, str],
        settings: Optional[Settings] = None,
        window_days: Optional[int] = None,
    ):
        if isinstance(airport, str):
            airport = AirportsAPI().get_airport_by_code(airport)

        self.airport = airport
        self.airport_code = airport.code
        self._flights_api = FlightsAPI()
        self._settings = settings or load_settings()
        self.window_days = window_days or self._settings.analysis.window_days
        self.window_end = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        self.window_start = self.window_end - timedelta(days=self.window_days)


    def get_congestion(self) -> CongestionReport:
        total_flights, average_flights_per_hour, peak_hour_average_flights_per_hour = self._flight_stats()
        capacity = metrics.capacity_per_hour(
            self.airport.num_of_runways, self._settings.capacity.flights_per_runway_per_hour
        )
        utilization = metrics.utilization_percent(peak_hour_average_flights_per_hour, capacity)
        level = metrics.congestion_level(utilization, self._settings.congestion_levels)

        return CongestionReport(
            airport=self.airport,
            window_start=self.window_start,
            window_end=self.window_end,
            total_flights=total_flights,
            average_flights_per_hour=average_flights_per_hour,
            peak_hour_average_flights_per_hour=peak_hour_average_flights_per_hour,
            capacity_per_hour=capacity,
            utilization_percent=utilization,
            congestion_level=level,
            assumptions=self._create_assumptions(),
        )

    def get_capacity(self) -> CapacityReport:
        _, average_flights_per_hour, peak_hour_average_flights_per_hour = self._flight_stats()
        capacity = metrics.capacity_per_hour(
            self.airport.num_of_runways, self._settings.capacity.flights_per_runway_per_hour
        )
        practical_pct = self._settings.capacity.practical_capacity_pct
        practical_capacity = capacity * (practical_pct / 100) if capacity > 0 else None

        return CapacityReport(
            airport=self.airport,
            window_start=self.window_start,
            window_end=self.window_end,
            capacity_per_hour=capacity,
            practical_capacity_per_hour=practical_capacity,
            average_flights_per_hour=average_flights_per_hour,
            peak_hour_average_flights_per_hour=peak_hour_average_flights_per_hour,
            assumptions=self._create_assumptions(),
        )

    def get_flights_count(self, direction: Direction) -> FlightCountReport:
        """Fetches flights for `direction` once and reports both the plain count and the
        long-haul count."""
        flights = self._get_flights(direction)
        min_hours = self._settings.long_haul.min_duration_hours
        long_haul_count = metrics.count_long_haul(flights, min_hours)

        return FlightCountReport(
            airport=self.airport,
            window_start=self.window_start,
            window_end=self.window_end,
            direction=direction,
            total=len(flights),
            long_haul_count=long_haul_count,
            min_duration_hours=min_hours,
            assumptions=self._create_assumptions() + [LONG_HAUL_ASSUMPTION],
        )

    def _flight_stats(self) -> Tuple[int, float, float]:
        """Returns (total_flights, average_flights_per_hour, peak_hour_average_flights_per_hour)."""
        flight_times = self._flights_times()
        flights_by_hour = metrics.count_flights_by_hour(flight_times)
        total_flights = len(flight_times)
        average_flights_per_hour = metrics.average_per_hour(total_flights, self.window_days)
        peak_hour_average_flights_per_hour = metrics.peak_hour_average(
            flights_by_hour, self.window_days, self._settings.analysis.peak_hours_per_day
        )
        return total_flights, average_flights_per_hour, peak_hour_average_flights_per_hour

    def _flights_times(self) -> List[datetime]:
        """Departure timestamps for flights leaving this airport, plus arrival timestamps for
        flights landing at it."""
        departures = self._get_flights(Direction.DEPARTURES)
        arrivals = self._get_flights(Direction.ARRIVALS)
        return [f.departure_time for f in departures] + [f.arrival_time for f in arrivals]

    def _get_flights(self, direction: Direction) -> List[Flight]:
        if direction is Direction.DEPARTURES:
            return self._flights_api.get_departures(self.airport_code, self.window_start, self.window_end)
        return self._flights_api.get_arrivals(self.airport_code, self.window_start, self.window_end)

    def _create_assumptions(self) -> List[str]:
        assumptions = list(BASE_ASSUMPTIONS)
        if self.airport.num_of_runways == 0:
            assumptions.append(
                "This airport has 0 open runways in our data, so capacity/utilization cannot be computed."
            )
        return assumptions
