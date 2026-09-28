import io
from datetime import date
from typing import List, Optional

import pandas as pd
import requests
from pydantic import BaseModel

from airports_agent.settings.settings import load_settings

BASE_URL = "https://davidmegginson.github.io/ourairports-data"
UNITED_STATES_COUNTRY_CODE = "US"
REQUIRED_AIRPORT_TYPES = ("large_airport", "medium_airport")
AIRPORTS_COLUMNS = ["id", "ident", "type", "name", "iso_region"]
RUNWAYS_COLUMNS = ["id", "airport_ref", "airport_ident", "closed"]
DATA_DIR = load_settings().data_dir_path
DATA_DIR.mkdir(parents=True, exist_ok=True)
AIRPORTS_FILE = DATA_DIR / "airports.csv"
RUNWAYS_FILE = DATA_DIR / "runways.csv"


class Airport(BaseModel):
    code: str
    name: str
    region: str
    num_of_runways: int


class AirportsAPI:
    def __init__(self, base_url:str =BASE_URL):
        self.base_url = base_url

    def get_airports_per_region(self, region: str) -> List[Airport]:
        airports = self._get_airports()
        runways = self._get_runways()
        matches = airports[airports["iso_region"] == region]
        return [self._to_airport(row, runways) for _, row in matches.iterrows()]
    
    def get_airport_by_code(self, code: str) -> Optional[Airport]:
        airports = self._get_airports()
        matches = airports[airports["ident"] == code]
        if matches.empty:
            return None
        return self._to_airport(matches.iloc[0], self._get_runways())

    def get_airport_by_name(self, name: str) -> Optional[Airport]:
        airports = self._get_airports()
        matches = airports[airports["name"] == name]
        if matches.empty:
            return None
        return self._to_airport(matches.iloc[0], self._get_runways())
    
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
            response.raise_for_status()
    
    def _get_runways(self) -> Optional[pd.DataFrame]:
        if self._is_up_to_date(RUNWAYS_FILE):
            return pd.read_csv(RUNWAYS_FILE)

        response = requests.get(f"{self.base_url}/{RUNWAYS_FILE.name}")
        if response.status_code == 200:
            runways = pd.read_csv(io.StringIO(response.text))[RUNWAYS_COLUMNS]
            runways.to_csv(RUNWAYS_FILE, index=False)
            return runways
        else:
            response.raise_for_status()
    
    def _is_up_to_date(self, path):
        if not path.exists():
            return False
        last_modified = date.fromtimestamp(path.stat().st_mtime)
        return last_modified == date.today()

    def _count_runways(self, airport_code: str, runways: pd.DataFrame) -> int:
        return len(
            runways[
                (runways["airport_ident"] == airport_code) & (runways["closed"] == 0)
            ]
        )

    def _to_airport(self, row: pd.Series, runways: pd.DataFrame) -> Airport:
        return Airport(
            code=row["ident"],
            name=row["name"],
            region=row["iso_region"],
            num_of_runways=self._count_runways(row["ident"], runways),
        )

    

if __name__ == "__main__":
    api = AirportsAPI()
    us_airports = api.get_airports_per_region("US-CA")
    print(us_airports)
