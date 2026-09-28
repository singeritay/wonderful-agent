from datetime import datetime, time, timedelta, timezone
from enum import Enum
import json
import os
from typing import List, Optional

from dotenv import load_dotenv
from opensky_api import FlightData, OpenSkyApi
from pydantic import BaseModel

from airports_agent.settings.settings import load_settings

load_dotenv()

MAX_WINDOW = timedelta(days=1)


class Direction(str, Enum):
    DEPARTURES = "departures"
    ARRIVALS = "arrivals"


class Flight(BaseModel):
    id: str
    call_sign: Optional[str] = None
    departure_airport_code: Optional[str] = None
    arrival_airport_code: Optional[str] = None
    departure_time: datetime
    arrival_time: datetime

FLIGHTS_CACHE_DIR = load_settings().data_dir_path / "flights"


class FlightsAPI:
    def __init__(self, client_id: Optional[str] = None, client_secret: Optional[str] = None):
        self.client_id = client_id or os.getenv("OPEN_SKY_CLIENT_ID")
        self.client_secret = client_secret or os.getenv("OPEN_SKY_CLIENT_SECRET")
        self._api = OpenSkyApi(client_id=self.client_id, client_secret=self.client_secret)

    def get_departures(self, airport_icao: str, begin: datetime, end: datetime) -> List[Flight]:
        return self._get_flights(Direction.DEPARTURES, airport_icao, begin, end)

    def get_arrivals(self, airport_icao: str, begin: datetime, end: datetime) -> List[Flight]:
        return self._get_flights(Direction.ARRIVALS, airport_icao, begin, end)

    def get_recent_departures(self, airport_icao: str, days: int = 7) -> List[Flight]:
        end = datetime.now(timezone.utc)
        begin = end - timedelta(days=days)
        return self.get_departures(airport_icao, begin, end)

    def get_recent_arrivals(self, airport_icao: str, days: int = 7) -> List[Flight]:
        end = datetime.now(timezone.utc)
        begin = end - timedelta(days=days)
        return self.get_arrivals(airport_icao, begin, end)

    def _get_flights(self, direction: Direction, airport_icao: str, begin: datetime, end: datetime) -> List[Flight]:
        flights = []
        for window_start, window_end in self._get_iter_windows(begin, end):
            flights.extend(self._fetch_window_flights(direction, airport_icao, window_start, window_end))
        return flights

    def _fetch_window_flights(
        self, direction: Direction, airport_icao: str, window_start: datetime, window_end: datetime
    ) -> List[Flight]:
        cache_path = self._get_cache_path_for_window(direction, airport_icao, window_start, window_end)
        if cache_path is not None and cache_path.exists():
            return [Flight.model_validate(item) for item in json.loads(cache_path.read_text())]

        records = self._fetch_records(direction, airport_icao, window_start, window_end)
        flights = [self._to_flight(record) for record in records]

        if cache_path is not None:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_text(json.dumps([f.model_dump(mode="json") for f in flights]))

        return flights

    def _fetch_records(
        self, direction: Direction, airport_icao: str, window_start: datetime, window_end: datetime
    ) -> List[FlightData]:
        if direction is Direction.DEPARTURES:
            records = self._api.get_departures_by_airport(
                airport_icao, int(window_start.timestamp()), int(window_end.timestamp())
            )
        else:
            records = self._api.get_arrivals_by_airport(
                airport_icao, int(window_start.timestamp()), int(window_end.timestamp())
            )
        return records or []

    def _get_cache_path_for_window(
        self, direction: Direction, airport_icao: str, window_start: datetime, window_end: datetime
    ):
        is_full_utc_day = window_start.time() == time.min and (window_end - window_start) == timedelta(days=1)
        if not is_full_utc_day:
            return None

        today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        if window_end > today_start:
            return None

        return FLIGHTS_CACHE_DIR / f"{airport_icao}_{window_start.date().isoformat()}_{direction.value}.json"

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
