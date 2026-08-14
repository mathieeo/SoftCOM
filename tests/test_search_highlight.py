"""
Tests for SoftCOM's Ctrl+F live search highlight (the pure fragment transform).
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import SoftCOM.gui_controller as gc


def _text(frags):
    return ''.join(t for _, t in frags)


def _hit_text(frags):
    """The characters that carry the search-hit style."""
    return ''.join(t for s, t in frags if s == gc._SEARCH_HIT_STYLE)


class TestHighlightSearch:
    def test_empty_pattern_returns_unchanged(self):
        frags = [('', 'hello world')]
        assert gc.highlight_search(frags, '') == frags

    def test_no_match_returns_unchanged(self):
        frags = [('', 'hello world')]
        assert gc.highlight_search(frags, 'xyz') == frags

    def test_preserves_full_text(self):
        frags = [('', 'find the error here')]
        out = gc.highlight_search(frags, 'error')
        assert _text(out) == 'find the error here'

    def test_single_match_is_highlighted(self):
        out = gc.highlight_search([('', 'find the error here')], 'error')
        assert _hit_text(out) == 'error'

    def test_case_insensitive_and_multiple(self):
        out = gc.highlight_search([('', 'AB ab Ab')], 'ab')
        assert _hit_text(out) == 'ABabAb'      # all three, original case kept

    def test_match_spanning_style_boundaries(self):
        # 'err' split across two fragments must still highlight fully
        out = gc.highlight_search([('class:a', 'er'), ('class:b', 'ror')], 'error')
        assert _text(out) == 'error'
        assert _hit_text(out) == 'error'

    def test_overlapping_does_not_loop_forever(self):
        out = gc.highlight_search([('', 'aaaa')], 'aa')
        assert _text(out) == 'aaaa'
        assert _hit_text(out) == 'aaaa'
