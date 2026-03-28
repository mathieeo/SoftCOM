"""
Tests for SoftCOM.support.serial_simulator
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'SoftCOM'))

from support.serial_simulator import (get_random_string, lines,
                                      random_text_generator)


class TestSerialSimulator:
    def test_lines_loaded(self):
        assert len(lines) > 0, "test_log.txt should contain at least one line"

    def test_get_random_string_returns_string(self):
        result = get_random_string()
        assert isinstance(result, str)

    def test_get_random_string_is_from_log(self):
        result = get_random_string()
        assert result in lines

    def test_random_text_generator_ends_with_newline(self):
        result = random_text_generator()
        assert result.endswith("\n")

    def test_random_text_generator_returns_string(self):
        result = random_text_generator()
        assert isinstance(result, str)

    def test_random_text_generator_not_empty(self):
        result = random_text_generator()
        assert len(result) > 1  # at minimum the newline + one char

    def test_multiple_calls_vary(self):
        """With a large enough log, repeated calls should not always return the same line."""
        results = {random_text_generator() for _ in range(50)}
        assert len(results) > 1, "Simulator should return varied output"
