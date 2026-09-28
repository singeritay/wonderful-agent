import pytest

from airports_agent.settings.settings import SETTINGS_FILE, Settings, load_settings


def test_load_settings_loads_defaults():
    settings = load_settings()

    assert settings.capacity.flights_per_runway_per_hour == 20
    assert settings.analysis.window_days == 3
    assert settings.long_haul.min_duration_hours == 5
    assert settings.data_dir_path.name == "data"


def test_load_settings_rejects_non_positive_capacity(tmp_path):
    bad_settings = tmp_path / "settings.yaml"
    bad_settings.write_text(
        SETTINGS_FILE.read_text().replace(
            "flights_per_runway_per_hour: 20", "flights_per_runway_per_hour: 0"
        )
    )

    with pytest.raises(Exception):
        load_settings(bad_settings)


def test_load_settings_rejects_out_of_order_congestion_levels(tmp_path):
    bad_settings = tmp_path / "settings.yaml"
    bad_settings.write_text(
        SETTINGS_FILE.read_text().replace("moderate_below: 80", "moderate_below: 40")
    )

    with pytest.raises(Exception):
        load_settings(bad_settings)
