from datetime import datetime, timedelta, timezone
from typing import List, Optional, Tuple

from apis.airports_api import Airport, AirportsAPI
from apis.flights_api import FlightsAPI

from airports_agent.analytics import metrics
from airports_agent.analytics.reports import (
    CongestionReport,
    LongHaulReport,
    RankingEntry,
    UnmetDemandReport,
)
from airports_agent.settings.settings import Settings, load_settings

BASE_ASSUMPTIONS = [
    "Flight counts come from OpenSky Network ADS-B data and may undercount actual traffic due to coverage gaps.",
    "Runway capacity assumes 20 flights/runway/hour, a simplification that ignores runway configuration, weather, and ATC procedures.",
    "Hours are bucketed in UTC, so 'per day' boundaries are UTC midnight, not local midnight.",
]


class AirportNotFoundError(Exception):
    pass


class AirportAnalyzer:
    def __init__(
        self,
        airports_api: Optional[AirportsAPI] = None,
        flights_api: Optional[FlightsAPI] = None,
        settings: Optional[Settings] = None,
    ):
        #CR: this class should be relevant only to one airport. it doesn't need to have a airport_api.
        # also, should not get flightsAPI (only initiate it)
        # this class should get an airport or airport code in the constructor and then have self.airport + self.airport_code (self.airport.code)
        self._airports_api = airports_api or AirportsAPI()
        self._flights_api = flights_api or FlightsAPI()
        self._settings = settings or load_settings()

    #CR: why do we have this function? is it used only in tests. If so, consider moving it to be inline.
    def search_airports(self, query: str) -> List[Airport]:
        return self._airports_api.search_airports(query)

    def get_congestion(self, code: str) -> CongestionReport:
        airport = self._get_airport_or_raise(code)
        #CR: window_start and window_end should be initiated in the constructor.
        window_start, window_end = self._analysis_window()
        flights_times = self._get_airport_flights_times(code, window_start, window_end)
        flights_by_hour = metrics.count_flights_by_hour(flights_times)
        #CR: windows_days should be a @property of the class, we use it a couple of times in the class
        window_days = self._settings.analysis.window_days

        average_per_hour = metrics.average_per_hour(len(flights_times), window_days)
        peak_average = metrics.peak_hour_average(
            flights_by_hour, window_days, self._settings.analysis.peak_hours_per_day
        )
        capacity = metrics.capacity_per_hour(
            airport.num_of_runways, self._settings.capacity.flights_per_runway_per_hour
        )
        utilization = metrics.utilization_percent(peak_average, capacity)
        level = metrics.congestion_level(
            utilization,
            self._settings.congestion_levels.low_below,
            self._settings.congestion_levels.moderate_below,
            self._settings.congestion_levels.high_up_to,
        )

        return CongestionReport(
            airport=airport,
            window_start=window_start,
            window_end=window_end,
            total_flights=len(flights_times),
            average_flights_per_hour=average_per_hour,
            peak_hour_average_flights_per_hour=peak_average,
            capacity_per_hour=capacity,
            utilization_pct=utilization,
            congestion_level=level,
            assumptions=self._create_assumptions(airport),
        )

    #CR: should delete this function. the ranking should be done by the agent by using the other tools - get airports by region, get congestion by airport, and then calculate the most congested.
    def rank_expansion_candidates(
        self, region_codes: List[str], limit: Optional[int] = None
    ) -> List[RankingEntry]:
        airports: List[Airport] = []
        for region in region_codes:
            airports.extend(self._airports_api.get_airports_per_region(region))

        entries = [self._to_ranking_entry(airport) for airport in airports]
        entries.sort(
            key=lambda e: (
                e.utilization_pct is None,
                -(e.utilization_pct or 0),
                -e.average_daily_flights,
            )
        )

        return entries[:limit] if limit is not None else entries

    #CR: should not be a specific report for long haul out of all flights.
    # split into 2 different reports - one for counting fllights per airport, and one for counting long haul flights per airport.
    # the agent will use these 2 reports to calculate the long haul share.
    # apply those comments in reports.py as well.
    def get_long_haul_share(self, code: str) -> LongHaulReport:
        airport = self._get_airport_or_raise(code)
        window_start, window_end = self._analysis_window()
        departures = self._flights_api.get_departures(code, window_start, window_end)

        long_haul_count, total, pct = metrics.long_haul_share(
            departures, self._settings.long_haul.min_duration_hours
        )

        return LongHaulReport(
            airport=airport,
            window_start=window_start,
            window_end=window_end,
            long_haul_flights=long_haul_count,
            total_departures=total,
            long_haul_pct=pct,
            min_duration_hours=self._settings.long_haul.min_duration_hours,
            assumptions=self._create_assumptions(airport)
            + [
                "Long-haul duration is measured from OpenSky's departure to arrival timestamps,"
                "which may not reflect actual flight time due to taxiing, holding, or other delays."
                f"A long haul flight is defined as one with a duration exceeding {self._settings.long_haul.min_duration_hours} hours.",
            ],
        )

    def get_unmet_demand(self, code: str) -> UnmetDemandReport:
        airport = self._get_airport_or_raise(code)
        window_start, window_end = self._analysis_window()
        movement_times = self._get_airport_flights_times(code, window_start, window_end)
        hourly = metrics.count_flights_by_hour(movement_times)

        capacity = metrics.capacity_per_hour(
            airport.num_of_runways, self._settings.capacity.flights_per_runway_per_hour
        )
        practical_pct = self._settings.unmet_demand.practical_capacity_pct
        hours_above, pct_active, excess = metrics.unmet_demand(hourly, capacity, practical_pct)
        practical_capacity = capacity * (practical_pct / 100) if capacity > 0 else None

        return UnmetDemandReport(
            airport=airport,
            window_start=window_start,
            window_end=window_end,
            capacity_per_hour=capacity,
            practical_capacity_per_hour=practical_capacity,
            hours_at_or_above_practical_capacity=hours_above,
            pct_of_active_hours_over_capacity=pct_active,
            excess_flights=excess,
            assumptions=self._create_assumptions(airport)
            + [
                "Unmet demand is a proxy for time spent at/near capacity, not observed rejected demand "
                "(e.g. denied slot requests), which isn't available in public data.",
            ],
        )

    #CR: no need this function. the AirportAnalyzer should not have a ranking function.
    def _to_ranking_entry(self, airport: Airport) -> RankingEntry:
        report = self.get_congestion(airport.code)
        return RankingEntry(
            airport=airport,
            utilization_pct=report.utilization_pct,
            congestion_level=report.congestion_level,
            average_daily_flights=report.average_flights_per_hour * 24,
        )

    def _get_airport_flights_times(self, code: str, window_start: datetime, window_end: datetime) -> List[datetime]:
        """Departure timestamps for flights leaving `code`, plus arrival timestamps for flights
        landing at `code`.
        """
        departures = self._flights_api.get_departures(code, window_start, window_end)
        arrivals = self._flights_api.get_arrivals(code, window_start, window_end)
        return [f.departure_time for f in departures] + [f.arrival_time for f in arrivals]

    #CR: don't need this function. the error should be raised in the API itself. functions in this file should just call self._airports_api.get_airport_by_code and
    def _get_airport_or_raise(self, code: str) -> Airport:
        airport = self._airports_api.get_airport_by_code(code)
        if airport is None:
            raise AirportNotFoundError(f"No airport found for code '{code}'")
        return airport

    #CR: change this function to be @property of the class
    def _analysis_window(self) -> Tuple[datetime, datetime]:
        window_days = self._settings.analysis.window_days
        today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        window_start = today_start - timedelta(days=window_days)
        return window_start, today_start

    def _create_assumptions(self, airport: Airport) -> List[str]:
        assumptions = list(BASE_ASSUMPTIONS)
        if airport.num_of_runways == 0:
            assumptions.append(
                "This airport has 0 open runways in our data, so capacity/utilization cannot be computed."
            )
        return assumptions
