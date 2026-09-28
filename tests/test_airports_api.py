from unittest.mock import MagicMock

import pytest

from apis import airports_api as airports_api_module
from apis.airports_api import Airport, AirportsAPI

AIRPORTS_CSV = (
    "id,ident,type,name,iso_country,iso_region\n"
    "1,KBOS,large_airport,Boston Logan,US,US-MA\n"
    "2,KJFK,large_airport,JFK,US,US-NY\n"
    "3,EGLL,large_airport,Heathrow,GB,GB-ENG\n"
    "4,KXYZ,small_airport,Tiny Airport,US,US-MA\n"
)

RUNWAYS_CSV = (
    "id,airport_ref,airport_ident,closed\n"
    "1,100,KBOS,0\n"
    "2,100,KBOS,0\n"
    "3,101,KJFK,1\n"
)


def make_response(status_code=200, text=""):
    response = MagicMock()
    response.status_code = status_code
    response.text = text
    return response


@pytest.fixture
def api(tmp_path, monkeypatch):
    monkeypatch.setattr(airports_api_module, "AIRPORTS_FILE", tmp_path / "airports.csv")
    monkeypatch.setattr(airports_api_module, "RUNWAYS_FILE", tmp_path / "runways.csv")
    return AirportsAPI()


@pytest.fixture
def mock_get(monkeypatch):
    def _install(airports_text=AIRPORTS_CSV, runways_text=RUNWAYS_CSV):
        def side_effect(url, *args, **kwargs):
            if url.endswith("airports.csv"):
                return make_response(text=airports_text)
            if url.endswith("runways.csv"):
                return make_response(text=runways_text)
            raise AssertionError(f"unexpected url: {url}")

        mocked = MagicMock(side_effect=side_effect)
        monkeypatch.setattr(airports_api_module.requests, "get", mocked)
        return mocked

    return _install


def test_get_airport_by_code_found(api, mock_get):
    mock_get()
    airport = api.get_airport_by_code("KBOS")
    assert airport == Airport(code="KBOS", name="Boston Logan", region="US-MA", num_of_runways=2)


def test_get_airport_by_code_counts_only_open_runways(api, mock_get):
    mock_get()
    airport = api.get_airport_by_code("KJFK")
    assert airport.num_of_runways == 0


def test_get_airport_by_code_not_found(api, mock_get):
    mock_get()
    assert api.get_airport_by_code("ZZZZ") is None


def test_get_airport_by_code_excludes_filtered_airports(api, mock_get):
    mock_get()
    assert api.get_airport_by_code("KXYZ") is None
    assert api.get_airport_by_code("EGLL") is None


def test_get_airport_by_name_found(api, mock_get):
    mock_get()
    airport = api.get_airport_by_name("Boston Logan")
    assert airport.code == "KBOS"


def test_get_airport_by_name_not_found(api, mock_get):
    mock_get()
    assert api.get_airport_by_name("Nonexistent") is None


def test_get_airports_per_region_filters_type_and_country(api, mock_get):
    mock_get()
    airports = api.get_airports_per_region("US-MA")
    assert [a.code for a in airports] == ["KBOS"]


def test_get_airports_per_region_no_match(api, mock_get):
    mock_get()
    assert api.get_airports_per_region("GB-ENG") == []


def test_caches_response_and_does_not_refetch(api, mock_get):
    mocked = mock_get()
    api.get_airport_by_code("KBOS")
    api.get_airport_by_code("KJFK")
    assert mocked.call_count == 2


def test_raises_on_non_200_response(api, monkeypatch):
    error_response = make_response(status_code=500)
    error_response.raise_for_status.side_effect = Exception("boom")
    monkeypatch.setattr(airports_api_module.requests, "get", MagicMock(return_value=error_response))

    with pytest.raises(Exception):
        api.get_airport_by_code("KBOS")
