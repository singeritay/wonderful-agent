from datetime import datetime, timedelta, timezone
import os
from typing import List, Optional

from dotenv import load_dotenv
from opensky_api import FlightData, OpenSkyApi
from pydantic import BaseModel

load_dotenv()

MAX_WINDOW = timedelta(days=1)


class Flight(BaseModel):
    id: str
    call_sign: Optional[str] = None
    departure_airport_code: Optional[str] = None
    arrival_airport_code: Optional[str] = None
    departure_time: datetime
    arrival_time: datetime


class FlightsAPI:
    def __init__(self, client_id: Optional[str] = None, client_secret: Optional[str] = None):
        self.client_id = client_id or os.getenv("OPEN_SKY_CLIENT_ID")
        self.client_secret = client_secret or os.getenv("OPEN_SKY_CLIENT_SECRET")
        self._api = OpenSkyApi(client_id=self.client_id, client_secret=self.client_secret)

    def get_departures(self, airport_icao: str, begin: datetime, end: datetime) -> list[Flight]:
        records = self._get_departures(airport_icao, begin, end)
        return [self._to_flight(record) for record in records]
    
    def get_recent_departures(self, airport_icao: str, days: int = 7) -> List[Flight]:
        end = datetime.now(timezone.utc)
        begin = end - timedelta(days=days)
        return self.get_departures(airport_icao, begin, end)

    def _get_departures(self, airport_icao: str, begin: datetime, end: datetime) -> List[FlightData]:
        flights = []
        for window_start, window_end in self._get_iter_windows(begin, end):
            flights.extend(self._fetch_departures_window(airport_icao, window_start, window_end))
        return flights

    def _fetch_departures_window(self, airport_icao: str, window_start: datetime, window_end: datetime) -> list[FlightData]:
        records = self._api.get_departures_by_airport(
            airport_icao,
            int(window_start.timestamp()),
            int(window_end.timestamp()),
        )
        return records or []
    
    def _get_iter_windows(self, begin: datetime, end: datetime):
        window_start = begin
        while window_start < end:
            window_end = min(window_start + MAX_WINDOW, end)
            yield window_start, window_end
            window_start = window_end

    def _to_flight(self, record: FlightData) -> Flight:
        return Flight(
            id=record.icao24,
            call_sign=(record.callsign or "").strip() or None,
            departure_airport_code=record.estDepartureAirport,
            arrival_airport_code=record.estArrivalAirport,
            departure_time=datetime.fromtimestamp(record.firstSeen, tz=timezone.utc),
            arrival_time=datetime.fromtimestamp(record.lastSeen, tz=timezone.utc),
        )

    

if __name__ == "__main__":
    api = FlightsAPI()
    departures = api.get_recent_departures("KBOS")
    print(f"Retrieved {len(departures)} departures from KBOS in the last week.")
