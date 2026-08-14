"""Layout tests — the UI has to actually fit the terminal it is run in.

SoftCOM rendered nothing but prompt_toolkit's "Window too small..." on an 80x24
terminal, which is both the POSIX default and the size of most of the serial consoles
this app is pointed at. The cause was a layout built from FIXED-height windows: the
shortcut panel asked for exactly one row per shortcut, so the root container's minimum
height exceeded 24 and prompt_toolkit refused to draw any of it.

A second, quieter bug lived next to it: the sidebar was a hard-coded 32 columns while
two of its own entries were 35 and 39 characters, so they were silently truncated
mid-word ("... [Esc" / "... [Ctrl+E] Li").

Neither is visible to a unit test of a helper function, and neither shows up in the key
tests, so they get their own file.
"""
import asyncio
import os
import sys
from contextlib import ExitStack
from unittest import mock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from prompt_toolkit.application import create_app_session
from prompt_toolkit.application.current import set_app
from prompt_toolkit.data_structures import Size
from prompt_toolkit.input import create_pipe_input
from prompt_toolkit.output import DummyOutput

import SoftCOM.gui_controller as gc


class _SizedOutput(DummyOutput):
    """DummyOutput reports a fixed 40x80; we need to pretend to be other terminals."""

    def __init__(self, rows, columns):
        self._size = Size(rows=rows, columns=columns)

    def get_size(self):
        return self._size


class _NoThread:
    def __init__(self, *_a, **_k):
        pass

    def start(self):
        pass

    def is_alive(self):
        return False

    def join(self, timeout=None):
        pass


def build(rows, columns, tmp_path):
    """A real GuiController rendering into a terminal of exactly this size."""
    stack = ExitStack()
    pipe_input = stack.enter_context(create_pipe_input())
    stack.enter_context(create_app_session(input=pipe_input,
                                           output=_SizedOutput(rows, columns)))
    stack.enter_context(mock.patch.object(gc, "Thread", _NoThread))
    stack.enter_context(mock.patch.object(gc.Application, "run", lambda self: None))
    stack.enter_context(mock.patch.object(gc.GuiController, "_load_history",
                                          staticmethod(lambda: [])))
    stack.enter_context(mock.patch.object(gc, "_HISTORY_FILE", str(tmp_path / "h")))
    controller = gc.GuiController("simulator", "", True)
    # Measuring the layout touches the buffers, which spawn a history-loading
    # background task. That needs *an* event loop, though not a running one:
    # create_background_task prefers app.loop and only falls back to
    # get_running_loop(). Hand it an idle loop so the task is scheduled and never
    # runs, instead of raising "no running event loop" mid-measurement.
    loop = asyncio.new_event_loop()
    controller.application.loop = loop

    def _close():
        for task in list(getattr(controller.application, "_background_tasks", [])):
            task.cancel()
        loop.close()

    stack.callback(_close)
    return stack, controller


# ── The sidebar must not clip its own text ────────────────────────────────────

def test_no_shortcut_line_is_wider_than_the_sidebar():
    width = gc.get_options_width()
    for _style, text in gc.get_options_text():
        line = text.rstrip("\n")
        assert len(line) <= width, (
            f"{line!r} is {len(line)} cols but the sidebar is {width} — it would be "
            f"truncated mid-word")


def test_sidebar_width_tracks_its_content():
    """Adding a longer shortcut must widen the panel, not silently clip."""
    longest = max(len(t.rstrip("\n")) for _s, t in gc.get_options_text())
    assert gc.get_options_width() >= longest


# ── The layout must fit real terminals ────────────────────────────────────────

@pytest.mark.parametrize("rows,columns", [(24, 80), (24, 120), (30, 100)])
def test_layout_fits_a_small_terminal(rows, columns, tmp_path):
    """The whole point: on a terminal this size the app must still draw itself.

    prompt_toolkit replaces the entire UI with "Window too small..." when the root
    container's minimum height exceeds the terminal, so asserting on that minimum is
    asserting on exactly what the user would have seen.
    """
    stack, ctrl = build(rows, columns, tmp_path)
    with stack:
        with set_app(ctrl.application):
            dim = ctrl.root_container.preferred_height(columns, rows)
            assert dim.min <= rows, (
                f"layout needs {dim.min} rows but the terminal has {rows}; "
                f"prompt_toolkit would render 'Window too small...'")


def test_sidebar_is_dropped_on_a_small_terminal(tmp_path):
    stack, ctrl = build(24, 80, tmp_path)
    with stack:
        with set_app(ctrl.application):
            assert gc._sidebar_fits() is False


def test_sidebar_is_shown_on_a_large_terminal(tmp_path):
    stack, ctrl = build(45, 140, tmp_path)
    with stack:
        with set_app(ctrl.application):
            assert gc._sidebar_fits() is True


def test_every_shortcut_is_visible_whenever_the_sidebar_is_shown(tmp_path):
    """The threshold must be high enough to show the WHOLE shortcut list.

    An earlier fix let the sidebar appear at a height where the recent-commands list
    stole rows from it, so F1/Tab/History/PgUp scrolled off and the user never learned
    those keys existed.
    """
    rows = gc.get_sidebar_min_rows()
    stack, ctrl = build(rows, 140, tmp_path)
    with stack:
        with set_app(ctrl.application):
            assert gc._sidebar_fits() is True
            # 6 rows of app chrome + 7 of panel chrome + 1 history row is the budget
            # that get_sidebar_min_rows() promises; the rest is the shortcut list.
            assert rows - 14 >= len(gc.get_options_text())
