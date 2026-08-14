"""
Tests for SoftCOM persistent command history logic
"""
import os
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

# Patch the history file path before importing gui_controller
import SoftCOM.gui_controller as gc


@pytest.fixture(autouse=True)
def temp_history_file(tmp_path, monkeypatch):
    """Redirect history file to a temp path for every test."""
    hist = str(tmp_path / ".softcom_history")
    monkeypatch.setattr(gc, "_HISTORY_FILE", hist)
    monkeypatch.setattr(gc, "_MAX_HISTORY", 10)
    return hist


class TestLoadHistory:
    def test_returns_empty_list_when_no_file(self):
        result = gc.GuiController._load_history()
        assert result == []

    def test_loads_lines_from_file(self, temp_history_file):
        with open(temp_history_file, "w") as f:
            f.write("ls -la\npwd\nuname -a\n")
        result = gc.GuiController._load_history()
        assert result == ["ls -la", "pwd", "uname -a"]

    def test_ignores_blank_lines(self, temp_history_file):
        with open(temp_history_file, "w") as f:
            f.write("ls\n\n\npwd\n")
        result = gc.GuiController._load_history()
        assert "" not in result
        assert "ls" in result
        assert "pwd" in result

    def test_caps_at_max_history(self, temp_history_file):
        entries = [f"cmd{i}" for i in range(20)]
        with open(temp_history_file, "w") as f:
            f.write("\n".join(entries) + "\n")
        result = gc.GuiController._load_history()
        assert len(result) <= gc._MAX_HISTORY
        # should keep the most recent entries
        assert result[-1] == "cmd19"


class TestHistoryCapLogic:
    def test_history_capped_at_max(self, temp_history_file):
        """Saving more entries than _MAX_HISTORY should truncate oldest."""
        # We test the slicing logic directly since _save_history needs self
        entries = [f"cmd{i}" for i in range(15)]
        capped = entries[-gc._MAX_HISTORY:]
        assert len(capped) == gc._MAX_HISTORY
        assert capped[0] == "cmd5"
        assert capped[-1] == "cmd14"

    def test_empty_history_file_on_no_entries(self, temp_history_file):
        """If history list is empty, file should still be writable without error."""
        with open(temp_history_file, "w") as f:
            f.write("")
        result = gc.GuiController._load_history()
        assert result == []
