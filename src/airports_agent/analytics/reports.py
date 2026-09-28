from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel

from apis.airports_api import Airport
from airports_agent.analytics.metrics import CongestionLevel


class CongestionReport(BaseModel):
    airport: Airport
    window_start: datetime
    window_end: datetime
    total_flights: int
    average_flights_per_hour: float
    peak_hour_average_flights_per_hour: float
    capacity_per_hour: int
    utilization_pct: Optional[float]
    congestion_level: CongestionLevel
    assumptions: List[str]


class LongHaulReport(BaseModel):
    airport: Airport
    window_start: datetime
    window_end: datetime
    long_haul_flights: int
    total_departures: int
    long_haul_pct: float
    min_duration_hours: float
    assumptions: List[str]


#CR: this report shuold not answer the question directly
#CR: it should produce a report that will tell what the practical capacity is, and what is the real capacity / occupation. 
class UnmetDemandReport(BaseModel):
    airport: Airport
    window_start: datetime
    window_end: datetime
    capacity_per_hour: int
    practical_capacity_per_hour: Optional[float]
    hours_at_or_above_practical_capacity: int
    pct_of_active_hours_over_capacity: float
    excess_flights: int
    assumptions: List[str]


#CR: remove this. see explanation in airport_analyzer.py
class RankingEntry(BaseModel):
    airport: Airport
    utilization_pct: Optional[float]
    congestion_level: CongestionLevel
    average_daily_flights: float
