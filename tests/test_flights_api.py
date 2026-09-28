from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch

from apis.flights_api import Flight, FlightsAPI


def make_flight_data(icao24="abc123", callsign="UAL123  ", dep="KBOS", arr="KJFK",
                      first_seen=1700000000, last_seen=1700003600):
    return SimpleNamespace(
        icao24=icao24,
        callsign=callsign,
        estDepartureAirport=dep,
        estArrivalAirport=arr,
        firstSeen=first_seen,
        lastSeen=last_seen,
    )


@patch("apis.flights_api.OpenSkyApi")
def test_get_departures_maps_flight_data_to_flight(mock_opensky_api_cls):
    mock_opensky_api_cls.return_value.get_departures_by_airport.return_value = [make_flight_data()]

    api = FlightsAPI(client_id="id", client_secret="secret")
    begin = datetime(2026, 1, 1, tzinfo=timezone.utc)
    end = datetime(2026, 1, 1, 12, tzinfo=timezone.utc)

    flights = api.get_departures("KBOS", begin, end)

    assert len(flights) == 1
    flight = flights[0]
    assert isinstance(flight, Flight)
    assert flight.id == "abc123"
    assert flight.call_sign == "UAL123"
    assert flight.departure_airport_code == "KBOS"
    assert flight.arrival_airport_code == "KJFK"
    assert flight.departure_time == datetime.fromtimestamp(1700000000, tz=timezone.utc)
    assert flight.arrival_time == datetime.fromtimestamp(1700003600, tz=timezone.utc)


@patch("apis.flights_api.OpenSkyApi")
def test_get_departures_blank_callsign_becomes_none(mock_opensky_api_cls):
    mock_opensky_api_cls.return_value.get_departures_by_airport.return_value = [
        make_flight_data(callsign="   ")
    ]

    api = FlightsAPI(client_id="id", client_secret="secret")
    flights = api.get_departures(
        "KBOS",
        datetime(2026, 1, 1, tzinfo=timezone.utc),
        datetime(2026, 1, 1, 1, tzinfo=timezone.utc),
    )

    assert flights[0].call_sign is None


@patch("apis.flights_api.OpenSkyApi")
def test_get_departures_handles_none_response(mock_opensky_api_cls):
    mock_opensky_api_cls.return_value.get_departures_by_airport.return_value = None

    api = FlightsAPI(client_id="id", client_secret="secret")
    flights = api.get_departures(
        "KBOS",
        datetime(2026, 1, 1, tzinfo=timezone.utc),
        datetime(2026, 1, 1, 1, tzinfo=timezone.utc),
    )

    assert flights == []


@patch("apis.flights_api.OpenSkyApi")
def test_get_departures_chunks_by_max_window(mock_opensky_api_cls):
    mock_opensky_api_cls.return_value.get_departures_by_airport.return_value = []

    api = FlightsAPI(client_id="id", client_secret="secret")
    begin = datetime(2026, 1, 1, tzinfo=timezone.utc)
    end = datetime(2026, 1, 3, tzinfo=timezone.utc)

    api.get_departures("KBOS", begin, end)

    assert mock_opensky_api_cls.return_value.get_departures_by_airport.call_count == 2


@patch("apis.flights_api.OpenSkyApi")
def test_get_recent_departures_uses_days_window(mock_opensky_api_cls):
    mock_opensky_api_cls.return_value.get_departures_by_airport.return_value = []

    api = FlightsAPI(client_id="id", client_secret="secret")
    api.get_recent_departures("KBOS", days=3)

    assert mock_opensky_api_cls.return_value.get_departures_by_airport.call_count == 3
