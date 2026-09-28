from unittest.mock import MagicMock

import pytest

from airports_agent.apis import airports_api as airports_api_module
from airports_agent.apis.airports_api import Airport, AirportNotFoundError, AirportsAPI

AIRPORTS_CSV = (
    "id,ident,type,name,iso_country,iso_region,iata_code,municipality\n"
    "1,KBOS,large_airport,Boston Logan,US,US-MA,BOS,Boston\n"
    "2,KJFK,large_airport,JFK,US,US-NY,JFK,New York\n"
    "3,EGLL,large_airport,Heathrow,GB,GB-ENG,LHR,London\n"
    "4,KXYZ,small_airport,Tiny Airport,US,US-MA,XYZ,Nowhere\n"
)

RUNWAYS_CSV = (
    "id,airport_ref,airport_ident,closed,le_ident\n"
    "1,100,KBOS,0,04L\n"
    "2,100,KBOS,0,22R\n"
    "3,100,KBOS,0,H1\n"
    "4,101,KJFK,1,04\n"
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
    assert airport == Airport(
        code="KBOS",
        name="Boston Logan",
        region="US-MA",
        num_of_runways=2,
        iata_code="BOS",
        municipality="Boston",
    )


def test_get_airport_by_code_excludes_helipads(api, mock_get):
    mock_get()
    airport = api.get_airport_by_code("KBOS")
    assert airport.num_of_runways == 2  # 3 open runway rows for KBOS, one (H1) is a helipad


def test_get_airport_by_code_counts_only_open_runways(api, mock_get):
    mock_get()
    airport = api.get_airport_by_code("KJFK")
    assert airport.num_of_runways == 0


def test_get_airport_by_code_not_found(api, mock_get):
    mock_get()
    with pytest.raises(AirportNotFoundError):
        api.get_airport_by_code("ZZZZ")


def test_get_airport_by_code_excludes_filtered_airports(api, mock_get):
    mock_get()
    with pytest.raises(AirportNotFoundError):
        api.get_airport_by_code("KXYZ")
    with pytest.raises(AirportNotFoundError):
        api.get_airport_by_code("EGLL")


def test_get_airport_by_name_found(api, mock_get):
    mock_get()
    airport = api.get_airport_by_name("Boston Logan")
    assert airport.code == "KBOS"


def test_get_airport_by_name_not_found(api, mock_get):
    mock_get()
    with pytest.raises(AirportNotFoundError):
        api.get_airport_by_name("Nonexistent")


def test_get_airports_per_region_filters_type_and_country(api, mock_get):
    mock_get()
    airports = api.get_airports_per_region("US-MA")
    assert [a.code for a in airports] == ["KBOS"]


def test_get_airports_per_region_no_match(api, mock_get):
    mock_get()
    assert api.get_airports_per_region("GB-ENG") == []


def test_get_airports_per_region_accepts_list_of_regions(api, mock_get):
    mock_get()
    airports = api.get_airports_per_region(["US-MA", "US-NY"])
    assert {a.code for a in airports} == {"KBOS", "KJFK"}


def test_caches_response_and_does_not_refetch(api, mock_get):
    mocked = mock_get()
    api.get_airport_by_code("KBOS")
    api.get_airport_by_code("KJFK")
    assert mocked.call_count == 2


def test_search_airports_exact_ident_match(api, mock_get):
    mock_get()
    airports = api.search_airports("KBOS")
    assert [a.code for a in airports] == ["KBOS"]


def test_search_airports_exact_iata_match_case_insensitive(api, mock_get):
    mock_get()
    airports = api.search_airports("bos")
    assert [a.code for a in airports] == ["KBOS"]


def test_search_airports_falls_back_to_name_substring(api, mock_get):
    mock_get()
    airports = api.search_airports("logan")
    assert [a.code for a in airports] == ["KBOS"]


def test_search_airports_falls_back_to_municipality_substring(api, mock_get):
    mock_get()
    airports = api.search_airports("new york")
    assert [a.code for a in airports] == ["KJFK"]


def test_search_airports_no_match(api, mock_get):
    mock_get()
    assert api.search_airports("nonexistent") == []


def test_search_airports_blank_query(api, mock_get):
    mock_get()
    assert api.search_airports("   ") == []


def test_non_200_response_returns_no_airports(api, monkeypatch):
    monkeypatch.setattr(
        airports_api_module.requests, "get", MagicMock(return_value=make_response(status_code=500))
    )

    assert api.search_airports("KBOS") == []
    assert api.get_airports_per_region("US-MA") == []


def test_network_error_returns_no_airports(api, monkeypatch):
    offline = MagicMock(side_effect=airports_api_module.requests.ConnectionError("offline"))
    monkeypatch.setattr(airports_api_module.requests, "get", offline)

    assert api.search_airports("KBOS") == []
