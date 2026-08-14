"""
Headless TUI tests — drive the REAL prompt_toolkit Application through its REAL key
processor, with no terminal.

The rest of the suite tests helper functions in isolation. That is why a whole class of
interaction bugs survived it: a shortcut can be bound to the wrong key, be shadowed by
another binding, throw and kill the app, or leave focus somewhere the user can't type, and
every unit test still passes. These tests feed genuine KeyPress objects into
`Application.key_processor` and assert on what the user would actually see.

The pattern: patch `Application.run` (so construction doesn't block on a terminal) and
`Thread` (so the background serial reader never races the assertions), then drive keys
synchronously.
"""
import os
import sys
from contextlib import ExitStack
from unittest import mock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from prompt_toolkit.application import create_app_session
from prompt_toolkit.application.current import set_app
from prompt_toolkit.input import create_pipe_input
from prompt_toolkit.key_binding.key_processor import KeyPress, _Flush
from prompt_toolkit.keys import Keys
from prompt_toolkit.output import DummyOutput

import SoftCOM.gui_controller as gc


class _NoThread:
    """Stand-in for threading.Thread: the reader loop must not run during these tests."""

    def __init__(self, *_a, **_k):
        pass

    def start(self):
        pass

    def is_alive(self):
        return False

    def join(self, timeout=None):
        pass


@pytest.fixture(name="ctrl")
def _ctrl(tmp_path, monkeypatch):
    """A real GuiController in simulator mode, with module globals reset.

    Built inside an app session backed by a pipe input and a DummyOutput: under pytest stdin
    is captured, so prompt_toolkit's default vt100 input raises "Stdin is not a terminal".
    """
    for name, val in [("SEARCH_ACTIVE", False), ("SEARCH_STRING", ""), ("PAUSE_LOGGING", False),
                      ("TIMESTAMPS", False), ("CAPTURE", False), ("CAPTURE_LOG", ""),
                      ("TAB_PRESSED", False), ("UPDATE_LOG_FLAG", False),
                      ("LINE_ENDING", "LF"), ("LOCAL_ECHO", False)]:
        monkeypatch.setattr(gc, name, val, raising=False)
    # keep the real ~/.softcom_history out of the test run
    monkeypatch.setattr(gc, "_HISTORY_FILE", str(tmp_path / "history"), raising=False)

    with ExitStack() as stack:
        pipe_input = stack.enter_context(create_pipe_input())
        stack.enter_context(create_app_session(input=pipe_input, output=DummyOutput()))
        stack.enter_context(mock.patch.object(gc, "Thread", _NoThread))
        stack.enter_context(mock.patch.object(gc.Application, "run", lambda self: None))
        stack.enter_context(mock.patch.object(gc.GuiController, "_load_history",
                                              staticmethod(lambda: [])))
        controller = gc.GuiController("simulator", "", True)
        # prompt_toolkit holds a lone Escape back as a possible Alt- prefix and resolves it
        # from a background timer task, which needs a running event loop. Tests are
        # synchronous and have none, so disable the timer (`_start_timeout` returns early
        # when timeoutlen is None) and let `press()` flush explicitly instead. That makes
        # escape handling deterministic rather than a race against a 1 s sleep.
        controller.application.timeoutlen = None
        yield controller


def press(ctrl, *keys):
    """Feed real KeyPress objects through the real key processor."""
    app = ctrl.application
    with set_app(app):
        for key in keys:
            data = key if isinstance(key, str) and len(key) == 1 else ""
            app.key_processor.feed(KeyPress(key, data))
        app.key_processor.process_keys()
        # A trailing Escape is still buffered as a possible Alt- prefix. `_Flush` is
        # prompt_toolkit's own sentinel (identity-compared in process_keys) for "no more
        # input is coming" — the same thing its timeout task feeds. Flushing here is what
        # makes a bare Escape actually reach its binding.
        app.key_processor.feed(_Flush)
        app.key_processor.process_keys()


def paste(ctrl, text):
    app = ctrl.application
    with set_app(app):
        app.key_processor.feed(KeyPress(Keys.BracketedPaste, text))
        app.key_processor.process_keys()


def focused(ctrl):
    window = ctrl.application.layout.current_window
    return {id(ctrl.input_window): "input",
            id(ctrl.search_window): "search",
            id(ctrl.output_window): "output"}.get(id(window), "other")


# ── Typing and editing ────────────────────────────────────────────────────────

def test_typing_reaches_the_input_bar(ctrl):
    press(ctrl, 'l', 's')
    assert ctrl.input_buffer.text == "ls"


def test_backspace_is_not_swallowed_by_a_ctrl_h_binding(ctrl):
    """Keys.Backspace IS 'c-h' in prompt_toolkit: binding Ctrl+H for help would make it
    impossible to delete a character. Help is on F1 precisely so this keeps working."""
    press(ctrl, 'l', 's', Keys.Backspace)
    assert ctrl.input_buffer.text == "l"


# ── Search ────────────────────────────────────────────────────────────────────

def test_ctrl_f_opens_search_and_moves_focus(ctrl):
    press(ctrl, Keys.ControlF)
    assert gc.SEARCH_ACTIVE is True
    assert focused(ctrl) == "search"


def test_typing_while_searching_goes_to_the_search_field_only(ctrl):
    ctrl.input_buffer.text = "keep me"
    press(ctrl, Keys.ControlF, 'a', 'b')
    assert ctrl.search_buffer.text == "ab"
    assert gc.SEARCH_STRING == "ab"
    assert ctrl.input_buffer.text == "keep me"      # the input line is untouched


def test_escape_closes_search_and_restores_focus(ctrl):
    press(ctrl, Keys.ControlF, 'x', Keys.Escape)
    assert gc.SEARCH_ACTIVE is False
    assert ctrl.search_buffer.text == ""
    assert focused(ctrl) == "input"


def test_enter_while_searching_does_not_send_to_the_device(ctrl):
    sent = []
    ctrl.send_command = sent.append
    press(ctrl, Keys.ControlF, 'a', Keys.ControlM)
    assert sent == []            # Enter is "find next" here, not "send"


def test_tab_while_searching_does_not_request_autocomplete(ctrl):
    press(ctrl, Keys.ControlF, Keys.Tab)
    assert gc.TAB_PRESSED is False


# ── History ───────────────────────────────────────────────────────────────────

def test_history_up_down_round_trips_and_restores_the_half_typed_line(ctrl):
    ctrl.command_history = ["first", "second"]
    ctrl.history_index = -1
    ctrl.input_buffer.text = "halftyped"

    press(ctrl, Keys.Up)
    assert ctrl.input_buffer.text == "second"
    press(ctrl, Keys.Up)
    assert ctrl.input_buffer.text == "first"
    press(ctrl, Keys.Down)
    assert ctrl.input_buffer.text == "second"
    press(ctrl, Keys.Down)
    assert ctrl.input_buffer.text == "halftyped"


# ── Sending ───────────────────────────────────────────────────────────────────

def test_enter_sends_and_clears_the_input(ctrl):
    sent = []
    ctrl.send_command = sent.append
    ctrl.input_buffer.text = "uname -a"
    press(ctrl, Keys.ControlM)
    assert sent == ["uname -a\n"]
    assert ctrl.input_buffer.text == ""


def test_ctrl_c_and_ctrl_d_send_raw_control_bytes(ctrl):
    """Ctrl+C must interrupt the REMOTE command. Without it you can start `ping` on the
    device and have no way to stop it."""
    sent = []
    ctrl.send_command = sent.append
    press(ctrl, Keys.ControlC, Keys.ControlD)
    assert sent == ["\x03", "\x04"]


# ── Multi-line paste ──────────────────────────────────────────────────────────

def test_multiline_paste_sends_each_complete_line(ctrl):
    """Regression: a pasted script used to land as one blob in the one-row input bar, with
    the newlines buried inside a single command."""
    sent = []
    ctrl.send_command = sent.append
    paste(ctrl, "echo one\necho two\necho thr")
    assert sent == ["echo one\n", "echo two\n"]     # complete lines went out
    assert ctrl.input_buffer.text == "echo thr"     # the fragment waits for you to finish


def test_multiline_paste_normalises_crlf(ctrl):
    sent = []
    ctrl.send_command = sent.append
    paste(ctrl, "a\r\nb\r\n")
    assert sent == ["a\n", "b\n"]
    assert ctrl.input_buffer.text == ""


def test_single_line_paste_is_inserted_not_sent(ctrl):
    sent = []
    ctrl.send_command = sent.append
    paste(ctrl, "just text")
    assert sent == []
    assert ctrl.input_buffer.text == "just text"


def test_paste_into_search_stays_on_one_line(ctrl):
    press(ctrl, Keys.ControlF)
    paste(ctrl, "two\nlines")
    assert "\n" not in ctrl.search_buffer.text


# ── Crash safety ──────────────────────────────────────────────────────────────

def test_a_raising_action_does_not_kill_the_application(ctrl):
    """Regression: an exception inside a key binding propagates out of prompt_toolkit's key
    processor and tears the whole Application down — losing the session, the scrollback and
    any running capture because one shortcut hit a bad path."""
    with mock.patch.object(gc.GuiController, "action_show_help",
                           side_effect=RuntimeError("boom")):
        press(ctrl, Keys.F1)        # must not raise
    assert "action_show_help failed" in ctrl.output_buffer.text
    assert "boom" in ctrl.output_buffer.text


def test_the_app_survives_every_bound_key_with_no_device(ctrl):
    """Fire every registered shortcut with no serial device attached. Any of them raising
    would kill a real session."""
    ctrl.simulator_mode = False
    ctrl.ser_dev = None
    keys = [Keys.ControlX, Keys.ControlS, Keys.ControlY, Keys.ControlW, Keys.ControlL,
            Keys.ControlT, Keys.ControlN, Keys.ControlO, Keys.ControlK, Keys.F1,
            Keys.ControlP, Keys.Up, Keys.Down, Keys.PageUp, Keys.PageDown, Keys.ControlE,
            Keys.Tab, Keys.Escape]
    for key in keys:
        press(ctrl, key)            # must not raise
    gc.CAPTURE = False


# ── Shutdown ──────────────────────────────────────────────────────────────────

def test_shutdown_closes_the_serial_port(ctrl):
    """Regression: cleanup used to hang off __del__ alone, so the port could stay held open
    after SoftCOM had visibly quit — the next run failed with 'device busy'."""
    closed = []

    class _Dev:
        def close_dev(self):
            closed.append(True)

    ctrl.simulator_mode = False
    ctrl.ser_dev = _Dev()
    ctrl.shutdown()
    assert closed == [True]
    assert gc.UPDATE_LOG_FLAG is False


def test_shutdown_is_idempotent(ctrl):
    class _Dev:
        def __init__(self):
            self.n = 0

        def close_dev(self):
            self.n += 1

    ctrl.simulator_mode = False
    ctrl.ser_dev = _Dev()
    ctrl.shutdown()
    ctrl.shutdown()
    assert ctrl.ser_dev.n == 2      # safe to call repeatedly; never raises


# ── Interaction regressions found by driving the real app ─────────────────────

def test_escape_binding_is_filtered_so_meta_keys_still_work(ctrl):
    """Regression: `@kb.add("escape", eager=True)` with no filter short-circuits every
    `escape,<key>` binding — which is how a terminal delivers Alt/Meta. Alt+B typed a literal
    'b' instead of moving back a word. The binding must only be live while search is open."""
    esc = [b for b in gc.kb.bindings
           if len(b.keys) == 1 and b.keys[0] == Keys.Escape]
    assert esc, "the Escape binding disappeared"
    for binding in esc:
        assert binding.filter is not None
        gc.SEARCH_ACTIVE = False
        assert binding.filter() is False, "Escape must be inert when search is closed"
        gc.SEARCH_ACTIVE = True
        assert binding.filter() is True
        gc.SEARCH_ACTIVE = False


def test_alt_key_sequence_is_not_swallowed_as_a_bare_escape(ctrl):
    """Alt+B arrives as Escape then 'b'. With search closed it must reach the editor, not be
    eaten by the Escape handler."""
    ctrl.input_buffer.text = "hello world"
    ctrl.input_buffer.cursor_position = len("hello world")
    press(ctrl, Keys.Escape, 'b')
    assert ctrl.input_buffer.text != "hello worldb", (
        "Alt+B typed a literal 'b' — the eager Escape binding swallowed the Meta prefix")


def test_page_scroll_uses_a_screenful_not_a_hard_coded_eight(ctrl):
    """Regression: the step was hard-coded to 8 rows, so on a normal window the first few
    PageUp presses moved the cursor but not the view — nothing visibly happened."""
    assert ctrl._page_rows() == 8          # no render_info yet: documented fallback

    class _Info:
        window_height = 40
    ctrl.output_window.render_info = _Info()
    assert ctrl._page_rows() == 39         # a screenful, less one line of context


def test_scroll_up_freezes_follow_tail(ctrl):
    ctrl._append_to_output("\n".join(f"line {i}" for i in range(200)) + "\n")
    ctrl.follow_tail = True
    ctrl.action_scroll_up()
    assert ctrl.follow_tail is False
    ctrl.action_scroll_end()
    assert ctrl.follow_tail is True


def test_output_document_is_applied_directly_on_the_main_thread(ctrl):
    """The threadsafe marshalling must not make the UI thread asynchronous: on the main
    thread the write has to land immediately, or every action_* would read stale text."""
    ctrl._clear_output()
    ctrl._append_to_output("immediate\n")
    assert "immediate" in ctrl.output_buffer.text


def test_reader_thread_writes_are_marshalled_to_the_event_loop(ctrl):
    """Regression: the reader thread called Buffer.set_document directly. text and cursor are
    set as two separate steps, and the renderer reads them as two separate reads, so it could
    see new-shorter-text with old-longer-cursor and raise
    `AssertionError: cursor_position=N, len_text=M` over the full-screen UI."""
    posted = []

    class _Loop:
        def call_soon_threadsafe(self, fn, *a):
            posted.append(fn)

    ctrl.application.loop = _Loop()
    done = []

    def from_thread():
        ctrl._append_to_output("from the reader thread\n")
        done.append(True)

    worker = __import__("threading").Thread(target=from_thread)
    worker.start()
    worker.join(2)

    assert done == [True]
    assert posted, "a non-main-thread write must be posted to the loop, not applied directly"
