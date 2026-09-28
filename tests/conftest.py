import sys
import types


def _install_opensky_api_stub():
    if "opensky_api" in sys.modules:
        return

    stub = types.ModuleType("opensky_api")

    class FlightData:
        def __init__(self, icao24=None, callsign=None, estDepartureAirport=None,
                     estArrivalAirport=None, firstSeen=None, lastSeen=None):
            self.icao24 = icao24
            self.callsign = callsign
            self.estDepartureAirport = estDepartureAirport
            self.estArrivalAirport = estArrivalAirport
            self.firstSeen = firstSeen
            self.lastSeen = lastSeen

    class OpenSkyApi:
        def __init__(self, client_id=None, client_secret=None):
            self.client_id = client_id
            self.client_secret = client_secret

        def get_departures_by_airport(self, *args, **kwargs):
            return []

        def get_arrivals_by_airport(self, *args, **kwargs):
            return []

    stub.FlightData = FlightData
    stub.OpenSkyApi = OpenSkyApi
    sys.modules["opensky_api"] = stub


_install_opensky_api_stub()
