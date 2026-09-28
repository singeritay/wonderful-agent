from functools import lru_cache
from pathlib import Path
from typing import Optional

import yaml
from pydantic import BaseModel, Field, field_validator

SETTINGS_FILE = Path(__file__).parent / "settings.yaml"
PROJECT_ROOT = Path(__file__).resolve().parents[3]


class CapacitySettings(BaseModel):
    flights_per_runway_per_hour: int = Field(gt=0)
    practical_capacity_pct: float = Field(gt=0, le=100)


class AnalysisSettings(BaseModel):
    window_days: int = Field(gt=0)
    peak_hours_per_day: int = Field(gt=0)


class CongestionLevelSettings(BaseModel):
    low_below: float = Field(gt=0, lt=100)
    moderate_below: float = Field(gt=0, lt=100)
    high_up_to: float = Field(gt=0, le=100)

    @field_validator("moderate_below")
    @classmethod
    def _moderate_above_low(cls, value: float, info) -> float:
        low_below = info.data.get("low_below")
        if low_below is not None and value <= low_below:
            raise ValueError("moderate_below must be greater than low_below")
        return value

    @field_validator("high_up_to")
    @classmethod
    def _high_above_moderate(cls, value: float, info) -> float:
        moderate_below = info.data.get("moderate_below")
        if moderate_below is not None and value <= moderate_below:
            raise ValueError("high_up_to must be greater than moderate_below")
        return value


class LongHaulSettings(BaseModel):
    min_duration_hours: float = Field(gt=0)


class LlmSettings(BaseModel):
    model: str


class Settings(BaseModel):
    data_dir: str
    capacity: CapacitySettings
    analysis: AnalysisSettings
    congestion_levels: CongestionLevelSettings
    long_haul: LongHaulSettings
    llm: LlmSettings

    @property
    def data_dir_path(self) -> Path:
        return PROJECT_ROOT / self.data_dir


@lru_cache(maxsize=None)
def load_settings(path: Optional[Path] = None) -> Settings:
    path = path or SETTINGS_FILE
    with open(path) as f:
        raw = yaml.safe_load(f)
    return Settings(**raw)
