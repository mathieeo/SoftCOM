"""
Tests for SoftCOM.support.save_settings
"""
import json
import os
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from SoftCOM.support.save_settings import SaveSettings


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

    def test_line_ending_default_and_persist(self, tmp_settings):
        s = SaveSettings(tmp_settings)
        assert s.line_ending == "LF"          # sensible default
        s.line_ending = "CRLF"
        s.save_file()
        assert SaveSettings(tmp_settings).line_ending == "CRLF"

    def test_line_ending_default_on_missing_key(self, tmp_settings):
        # An older settings file (pre-line-ending) must load with the LF default, not crash.
        data = {"settings": [{"device_path": "/dev/tty0", "rate": "9600", "bits": 8}]}
        with open(tmp_settings, "w") as f:
            json.dump(data, f)
        assert SaveSettings(tmp_settings).line_ending == "LF"

    def test_local_echo_default_and_persist(self, tmp_settings):
        s = SaveSettings(tmp_settings)
        assert s.local_echo is False          # off by default
        s.local_echo = True
        s.save_file()
        assert SaveSettings(tmp_settings).local_echo is True

    def test_local_echo_default_on_missing_key(self, tmp_settings):
        data = {"settings": [{"device_path": "/dev/tty0", "rate": "9600", "bits": 8}]}
        with open(tmp_settings, "w") as f:
            json.dump(data, f)
        assert SaveSettings(tmp_settings).local_echo is False

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

    @pytest.mark.parametrize("payload", [
        '{"settings": {"device_path": "/dev/x"}}',   # 'settings' is a dict, not a list → iterating its keys
        '{"settings": "oops"}',                       # 'settings' is a string → iterating chars
        '{"settings": 5}',                            # 'settings' is an int → not iterable at all
        '{"settings": [42, "nope", null]}',           # list of NON-dict items → .get() on them
        '["a", "b"]',                                 # top level is a list, not an object
        '"just a string"',                            # top level is a bare string
    ])
    def test_malformed_structure_does_not_crash(self, tmp_settings, payload):
        """Regression: a settings.json that is valid JSON but the WRONG SHAPE (settings not a list, items not
        dicts, top level not an object) used to raise TypeError/AttributeError — NOT caught by the load's
        except — and crash the app at startup. It must now degrade to defaults (device_path None) without
        raising, and a following save must rewrite a clean, reloadable file."""
        with open(tmp_settings, "w") as f:
            f.write(payload)
        s = SaveSettings(tmp_settings)                # must NOT raise
        assert s.get_settings()[0] is None            # fell back to defaults
        s.set_settings("/dev/ttyUSB0", "9600", 8, "N", 1)   # save over the junk
        reloaded = SaveSettings(tmp_settings)         # the rewritten file loads cleanly
        assert reloaded.get_settings()[0] == "/dev/ttyUSB0"


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


class TestSaveFileNeverCrashes:
    def test_save_file_to_unwritable_path_does_not_raise(self, tmp_settings, capsys):
        """A read-only settings.json / full disk / non-writable dir must NOT crash the app. save_file runs on
        first-run config, on the runtime Ctrl+N/Ctrl+O toggles, and on clean EXIT — an uncaught OSError from any
        of those meant an ugly traceback (or a mid-config crash). It must degrade to a warning instead."""
        s = SaveSettings(tmp_settings)
        # point the save at a path that cannot be opened for writing (a directory that doesn't exist)
        s.file = os.path.join(tmp_settings, "no_such_dir", "settings.json")
        s.save_file()                                   # must NOT raise
        assert "Could not save" in capsys.readouterr().out

    def test_set_settings_survives_unwritable_target(self, tmp_settings):
        """set_settings() calls save_file(); a write failure there must not propagate."""
        s = SaveSettings(tmp_settings)
        s.file = os.path.join(tmp_settings, "gone", "settings.json")
        s.set_settings("/dev/ttyUSB0", "115200", 8, "N", 1)   # must NOT raise
        assert s.device_path == "/dev/ttyUSB0"                # in-memory settings still updated
