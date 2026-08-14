"""The status bar and log header as state indicators.

The old status bar was one run of pipe-separated monochrome text:

    | Device: OPEN | Capture: ON | Paused | EOL: LF | Echo |

Every fact had identical weight, so "the port is closed" looked exactly like "line
endings are LF" and you had to read the whole line to learn anything from it. The
complaint that started this was "I can't tell what state it's in", which that line
technically answered and practically did not.

Two things are being pinned here:

  1. **One source of truth.** `get_status_text()` is derived from `status_segments()`,
     so the plain text the older tests assert on cannot drift from what is drawn.
  2. **One job per bar.** REC / PAUSED / SCROLLBACK belong to the log header, which
     sits directly above the output where the eye already is. They are deliberately
     absent from the status bar — rendering both showed them twice, identically.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import SoftCOM.gui_controller as gc  # noqa: E402


class _FakeDev:
    def __init__(self, is_open): self._open = is_open
    def is_dev_open(self): return self._open


class _Stub:
    """The two methods under test, bound to a stand-in with no serial port and no UI.

    They only read state, so they can be exercised without building a real
    GuiController — which keeps this file fast and free of app-session scaffolding.
    """
    _OK, _BAD, _WARN = gc.GuiController._OK, gc.GuiController._BAD, gc.GuiController._WARN
    _MODE, _DIM, _HINT = gc.GuiController._MODE, gc.GuiController._DIM, gc.GuiController._HINT
    status_segments = gc.GuiController.status_segments
    get_status_text = gc.GuiController.get_status_text
    log_header_segments = gc.GuiController.log_header_segments

    def __init__(self, *, is_open=True, sim=False, follow=True):
        self.simulator_mode = sim
        self.ser_dev = _FakeDev(is_open)
        self.follow_tail = follow


def _reset():
    gc.CAPTURE = False
    gc.PAUSE_LOGGING = False
    gc.SEARCH_ACTIVE = False
    gc.SEARCH_STRING = ""
    gc.TIMESTAMPS = False
    gc.LOCAL_ECHO = False
    gc.LINE_ENDING = "LF"


def _text(segments):
    return "".join(t for _s, t in segments)


class TestSingleSourceOfTruth:
    def test_status_text_is_exactly_the_joined_segments(self):
        _reset()
        s = _Stub()
        assert s.get_status_text() == _text(s.status_segments())

    def test_closed_is_still_reported_in_the_plain_text(self):
        # Pinned by an older regression test in test_interaction.py — the read thread
        # calls this and must be able to say CLOSED without crashing.
        _reset()
        assert "CLOSED" in _Stub(is_open=False).get_status_text()


class TestConnectionIsAlwaysVisible:
    def test_open(self):
        _reset()
        assert "OPEN" in _text(_Stub().status_segments())

    def test_closed_uses_the_alarm_style(self):
        _reset()
        style, text = _Stub(is_open=False).status_segments()[0]
        assert "CLOSED" in text and style == gc.GuiController._BAD

    def test_simulator_is_distinct_from_a_real_open_port(self):
        _reset()
        s = _Stub(sim=True)
        assert "SIM" in _text(s.status_segments())
        assert s.status_segments()[0][1] != " ● OPEN "


class TestBarsDoNotDuplicateEachOther:
    """Each transient state appears in exactly one of the two bars."""

    def test_capture_is_in_the_header_not_the_status_bar(self):
        _reset()
        gc.CAPTURE = True
        s = _Stub()
        assert "REC" in _text(s.log_header_segments())
        assert "REC" not in _text(s.status_segments())
        _reset()

    def test_paused_is_in_the_header_not_the_status_bar(self):
        _reset()
        gc.PAUSE_LOGGING = True
        s = _Stub()
        assert "PAUSED" in _text(s.log_header_segments())
        assert "PAUSED" not in _text(s.status_segments())
        _reset()

    def test_scrollback_is_in_the_header_and_says_how_to_leave(self):
        _reset()
        s = _Stub(follow=False)
        head = _text(s.log_header_segments())
        assert "SCROLLBACK" in head
        # A state the user did not choose deliberately must say how to get out of it.
        assert "Ctrl+E" in head
        assert "SCROLLBACK" not in _text(s.status_segments())
        _reset()

    def test_header_never_repeats_the_device_path(self):
        # The title bar one row above already shows it; printing it twice was the
        # first thing that looked wrong when this was rendered.
        _reset()
        s = _Stub()
        assert "/dev/" not in _text(s.log_header_segments())


class TestOnlyTrueThingsAreDrawn:
    def test_nothing_transient_shows_when_nothing_is_happening(self):
        _reset()
        s = _Stub()
        head = _text(s.log_header_segments())
        for absent in ("REC", "PAUSED", "SCROLLBACK"):
            assert absent not in head

    def test_persistent_config_is_present_but_dimmed(self):
        _reset()
        gc.LOCAL_ECHO = True
        gc.TIMESTAMPS = True
        s = _Stub()
        style, text = s.status_segments()[-1]
        assert "EOL LF" in text and "echo" in text and "stamps" in text
        assert style == gc.GuiController._DIM
        _reset()
