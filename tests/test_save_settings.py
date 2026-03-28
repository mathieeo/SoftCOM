"""
Tests for SoftCOM.support.save_settings
"""
import json
import os
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'SoftCOM'))

from support.save_settings import SaveSettings


@pytest.fixture
def tmp_settings(tmp_path):
    """Return a path inside a temp directory for the settings file."""
    return str(tmp_path / "settings.json")


class TestSaveSettingsCreation:
    def test_creates_file_when_missing(self, tmp_settings):
        SaveSettings(tmp_settings)
        assert os.path.isfile(tmp_settings)

    def test_default_values_when_new(self, tmp_settings):
        s = SaveSettings(tmp_settings)
        path, rate, bits, parity, stopbits = s.get_settings()
        assert path is None
        assert rate is None
        assert bits is None
        assert parity is None
        assert stopbits is None

    def test_created_file_is_valid_json(self, tmp_settings):
        SaveSettings(tmp_settings)
        with open(tmp_settings) as f:
            data = json.load(f)
        assert "settings" in data


class TestSaveSettingsLoad:
    def test_loads_saved_values(self, tmp_settings):
        s = SaveSettings(tmp_settings)
        s.set_settings("/dev/ttyUSB0", "115200", 8, "N", 1)

        s2 = SaveSettings(tmp_settings)
        path, rate, bits, parity, stopbits = s2.get_settings()
        assert path == "/dev/ttyUSB0"
        assert rate == "115200"
        assert bits == 8
        assert parity == "N"
        assert stopbits == 1

    def test_parity_default_on_missing_key(self, tmp_settings):
        # Write a settings file that has no parity key
        data = {"settings": [{"device_path": "/dev/tty0", "rate": "9600", "bits": 8}]}
        with open(tmp_settings, "w") as f:
            json.dump(data, f)
        s = SaveSettings(tmp_settings)
        _, _, _, parity, stopbits = s.get_settings()
        assert parity == "N"
        assert stopbits == 1

    def test_handles_corrupted_json_gracefully(self, tmp_settings):
        with open(tmp_settings, "w") as f:
            f.write("NOT VALID JSON {{{{")
        s = SaveSettings(tmp_settings)
        path, rate, bits, parity, stopbits = s.get_settings()
        assert path is None

    def test_handles_empty_file_gracefully(self, tmp_settings):
        open(tmp_settings, "w").close()
        s = SaveSettings(tmp_settings)
        path, _, _, _, _ = s.get_settings()
        assert path is None


class TestSaveSettingsPersistence:
    def test_set_settings_persists_to_disk(self, tmp_settings):
        s = SaveSettings(tmp_settings)
        s.set_settings("/dev/ttyUSB1", "57600", 7, "E", 2)

        with open(tmp_settings) as f:
            data = json.load(f)
        entry = data["settings"][0]
        assert entry["device_path"] == "/dev/ttyUSB1"
        assert entry["rate"] == "57600"
        assert entry["bits"] == 7
        assert entry["parity"] == "E"
        assert entry["stopbits"] == 2

    def test_save_file_replaces_not_appends(self, tmp_settings):
        s = SaveSettings(tmp_settings)
        s.set_settings("/dev/a", "9600", 8, "N", 1)
        s.set_settings("/dev/b", "115200", 8, "N", 1)
        s.save_file()

        with open(tmp_settings) as f:
            data = json.load(f)
        assert len(data["settings"]) == 1
        assert data["settings"][0]["device_path"] == "/dev/b"

    def test_multiple_instances_share_state(self, tmp_settings):
        s1 = SaveSettings(tmp_settings)
        s1.set_settings("/dev/ttyUSB0", "115200", 8, "N", 1)

        s2 = SaveSettings(tmp_settings)
        path, _, _, _, _ = s2.get_settings()
        assert path == "/dev/ttyUSB0"
