import io
from datetime import date
from typing import List, Optional, Union

import pandas as pd
import requests
from pydantic import BaseModel

from airports_agent.settings.settings import load_settings

BASE_URL = "https://davidmegginson.github.io/ourairports-data"
UNITED_STATES_COUNTRY_CODE = "US"
REQUIRED_AIRPORT_TYPES = ("large_airport", "medium_airport")
HELIPAD_RUNWAY_PREFIX = "H"
AIRPORTS_COLUMNS = ["id", "ident", "type", "name", "iso_region", "iata_code", "municipality"]
RUNWAYS_COLUMNS = ["id", "airport_ref", "airport_ident", "closed", "le_ident"]
DATA_DIR = load_settings().data_dir_path
DATA_DIR.mkdir(parents=True, exist_ok=True)
AIRPORTS_FILE = DATA_DIR / "airports.csv"
RUNWAYS_FILE = DATA_DIR / "runways.csv"


class AirportNotFoundError(Exception):
    pass


class Airport(BaseModel):
    code: str
    name: str
    region: str
    num_of_runways: int
    iata_code: Optional[str] = None
    municipality: Optional[str] = None


class AirportsAPI:
    def __init__(self, base_url:str =BASE_URL):
        self.base_url = base_url

    def get_airports_per_region(self, region: Union[str, List[str]]) -> List[Airport]:
        airports = self._get_airports()
        runways = self._get_runways()
        regions = [region] if isinstance(region, str) else region
        matches = airports[airports["iso_region"].isin(regions)]
        return [self._to_airport(row, runways) for _, row in matches.iterrows()]

    def get_airport_by_code(self, code: str) -> Airport:
        airports = self._get_airports()
        matches = airports[airports["ident"] == code]
        if matches.empty:
            raise AirportNotFoundError(f"No airport found for code '{code}'")
        return self._to_airport(matches.iloc[0], self._get_runways())

    def get_airport_by_name(self, name: str) -> Airport:
        airports = self._get_airports()
        matches = airports[airports["name"] == name]
        if matches.empty:
            raise AirportNotFoundError(f"No airport found for name '{name}'")
        return self._to_airport(matches.iloc[0], self._get_runways())

    def search_airports(self, query: str) -> List[Airport]:
        query = query.strip()
        if not query:
            return []

        airports = self._get_airports()
        runways = self._get_runways()

        exact = self._exact_matches(airports, query)
        matches = exact if not exact.empty else self._fuzzy_matches(airports, query)
        return [self._to_airport(row, runways) for _, row in matches.iterrows()]

    def _exact_matches(self, airports: pd.DataFrame, query: str) -> pd.DataFrame:
        query_upper = query.upper()
        return airports[
            (airports["ident"].str.upper() == query_upper)
            | (airports["iata_code"].astype(str).str.upper() == query_upper)
        ]

    def _fuzzy_matches(self, airports: pd.DataFrame, query: str) -> pd.DataFrame:
        return airports[
            airports["name"].str.contains(query, case=False, regex=False, na=False)
            | airports["municipality"].astype(str).str.contains(query, case=False, regex=False, na=False)
        ]

    def _get_airports(self) -> Optional[pd.DataFrame]:
        if self._is_up_to_date(AIRPORTS_FILE):
            return pd.read_csv(AIRPORTS_FILE)

        response = requests.get(f"{self.base_url}/{AIRPORTS_FILE.name}")
        if response.status_code == 200:
            airports = pd.read_csv(io.StringIO(response.text))
            airports = airports[
                airports["type"].isin(REQUIRED_AIRPORT_TYPES)
                & (airports["iso_country"] == UNITED_STATES_COUNTRY_CODE)
            ][AIRPORTS_COLUMNS]
            airports.to_csv(AIRPORTS_FILE, index=False)
            return airports
        else:
            print(f"UNSUCCESSFUL CALL FOR AIRPORTS API, status_code: {response.status_code}")

    def _get_runways(self) -> Optional[pd.DataFrame]:
        if self._is_up_to_date(RUNWAYS_FILE):
            return pd.read_csv(RUNWAYS_FILE)

        response = requests.get(f"{self.base_url}/{RUNWAYS_FILE.name}")
        if response.status_code == 200:
            runways = pd.read_csv(io.StringIO(response.text))[RUNWAYS_COLUMNS]
            runways.to_csv(RUNWAYS_FILE, index=False)
            return runways
        else:
            print(f"UNSUCCESSFUL CALL FOR RUNWAYS API, status_code: {response.status_code}")

    def _is_up_to_date(self, path):
        if not path.exists():
            return False
        last_modified = date.fromtimestamp(path.stat().st_mtime)
        return last_modified == date.today()

    def _count_runways(self, airport_code: str, runways: pd.DataFrame) -> int:
        airport_runways = runways[
            (runways["airport_ident"] == airport_code) & (runways["closed"] == 0)
        ]
        is_helipad = (
            airport_runways["le_ident"].astype(str).str.upper().str.startswith(HELIPAD_RUNWAY_PREFIX)
        )
        return len(airport_runways[~is_helipad])

    def _to_airport(self, row: pd.Series, runways: pd.DataFrame) -> Airport:
        return Airport(
            code=row["ident"],
            name=row["name"],
            region=row["iso_region"],
            num_of_runways=self._count_runways(row["ident"], runways),
            iata_code=None if pd.isna(row["iata_code"]) else str(row["iata_code"]),
            municipality=None if pd.isna(row["municipality"]) else str(row["municipality"]),
        )



if __name__ == "__main__":
    api = AirportsAPI()
    us_airports = api.get_airports_per_region("US-CA")
    print(us_airports)
