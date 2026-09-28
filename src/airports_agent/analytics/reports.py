from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel

from apis.airports_api import Airport
from apis.flights_api import Direction
from airports_agent.analytics.metrics import CongestionLevel


class CongestionReport(BaseModel):
    airport: Airport
    window_start: datetime
    window_end: datetime
    total_flights: int
    average_flights_per_hour: float
    peak_hour_average_flights_per_hour: float
    capacity_per_hour: int
    utilization_percent: Optional[float]
    congestion_level: CongestionLevel
    assumptions: List[str]


class FlightCountReport(BaseModel):
    airport: Airport
    window_start: datetime
    window_end: datetime
    direction: Direction
    total: int
    long_haul_count: int
    min_duration_hours: float
    assumptions: List[str]


class CapacityReport(BaseModel):
    airport: Airport
    window_start: datetime
    window_end: datetime
    capacity_per_hour: int
    practical_capacity_per_hour: Optional[float]
    average_flights_per_hour: float
    peak_hour_average_flights_per_hour: float
    assumptions: List[str]


class FlightsCountResult(BaseModel):
    """Bundles per-direction FlightCountReports. A direction is omitted (None) when the caller
    asked for only the other direction."""

    departures: Optional[FlightCountReport] = None
    arrivals: Optional[FlightCountReport] = None
