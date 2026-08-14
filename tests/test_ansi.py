"""ANSI escape sequences arriving FROM THE DEVICE.

SoftCOM's log is a plain prompt_toolkit Buffer, which does not interpret escape codes, so
everything a device sent landed in the log as literal caret notation. A default coloured
shell prompt rendered as

    ^[[1;32mroot@target^[[0m:^[[1;34m/mnt^[[0m# ls --color

and that is the DEFAULT prompt on most Linux targets — plus `ls`, `grep`, `systemctl` and
`dmesg` all colourise when they think they are on a TTY. For a large share of the devices
this terminal exists to talk to, every line was unreadable.

The display now strips escapes; the CAPTURE file keeps the raw bytes, because a capture is
evidence of what the device actually sent.
"""
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import pytest

import SoftCOM.gui_controller as gc
from SoftCOM.gui_controller import strip_ansi

# ── The pure stripper ─────────────────────────────────────────────────────────

def test_a_coloured_shell_prompt_becomes_readable():
    raw = "\x1b[1;32mroot@target\x1b[0m:\x1b[1;34m/mnt\x1b[0m# "
    out, carry = strip_ansi(raw)
    assert out == "root@target:/mnt# "
    assert carry == ""


@pytest.mark.parametrize("raw,expected", [
    ("\x1b[0m\x1b[01;34mbin\x1b[0m", "bin"),          # ls --color
    ("loading\x1b[K done", "loading done"),           # erase-to-end-of-line
    ("\x1b[2J\x1b[Hcleared", "cleared"),              # clear screen + home
    ("\x1b]0;my title\x07shell$ ", "shell$ "),        # OSC window title, BEL-terminated
    ("\x1b]0;t\x1b\\shell$ ", "shell$ "),             # OSC, ST-terminated
    ("\x1bMreverse-index", "reverse-index"),          # two-character escape
    ("alarm\x07!", "alarm!"),                         # bare BEL is a bell, not text
])
def test_escape_forms_are_removed(raw, expected):
    out, carry = strip_ansi(raw)
    assert out == expected
    assert carry == ""


def test_plain_text_is_untouched():
    """Including the literal two-char '^M' the CR pass deliberately preserves."""
    for text in ("hello world\n", "vim shows ^M here\n", "100%\n", ""):
        assert strip_ansi(text) == (text, "")


# ── The carry: a serial read splits sequences mid-way ─────────────────────────

def test_a_sequence_split_across_two_reads_does_not_leak_its_tail():
    """THE reason this needs a carry. A serial read returns whatever bytes have arrived, so
    "\\x1b[1;32m" routinely arrives as "\\x1b[1;" + "32mroot". Stripping each chunk on its own
    would emit "32mroot" as visible junk."""
    out1, carry = strip_ansi("ok \x1b[1;")
    assert out1 == "ok "
    assert carry == "\x1b[1;"                 # held, not printed

    out2, carry = strip_ansi("32mroot@target", carry)
    assert out2 == "root@target"              # the tail never reached the log
    assert carry == ""


def test_carry_survives_several_starved_reads():
    carry = ""
    for chunk in ("\x1b", "[", "3", "1"):
        out, carry = strip_ansi(chunk, carry)
        assert out == ""                      # nothing printed while incomplete
    out, carry = strip_ansi("mRED", carry)
    assert out == "RED" and carry == ""


def test_a_stray_lone_escape_cannot_black_hole_the_log():
    """The safety valve. A device echoing a bare ESC (a keypress, line noise) must not make
    every subsequent byte vanish while the stripper waits for a terminator that never comes."""
    out, carry = strip_ansi("\x1b")
    assert carry == "\x1b" and out == ""
    # Keep feeding ordinary text; once the held tail exceeds the cap it is released, not lost.
    text = "x" * (gc._MAX_ESC_CARRY + 10)
    out, carry = strip_ansi(text, carry)
    assert carry == ""
    assert out.endswith("x" * 10)
    assert "x" * 10 in out


# ── Wired into the read path ──────────────────────────────────────────────────

def _make_controller():
    from prompt_toolkit.application import Application, create_app_session
    from prompt_toolkit.input import DummyInput
    from prompt_toolkit.output import DummyOutput
    Application.run = lambda self, *a, **k: None
    with create_app_session(input=DummyInput(), output=DummyOutput()):
        g = gc.GuiController("simulator", "", simulator_mode=True)
    gc.UPDATE_LOG_FLAG = False
    time.sleep(0.03)
    return g


def test_the_log_is_clean_but_the_capture_stays_raw():
    """The split that matters: readable on screen, faithful on disk."""
    g = _make_controller()
    raw = "\x1b[1;32mroot@target\x1b[0m:/mnt# \n"
    gc.CAPTURE, gc.CAPTURE_LOG = True, ""
    try:
        g._process_incoming(raw)
    finally:
        gc.CAPTURE, gc.CAPTURE_LOG = False, ""
        captured = gc.CAPTURE_LOG
    assert "\x1b" not in g.output_buffer.text
    assert "root@target:/mnt# " in g.output_buffer.text


def test_capture_keeps_the_escapes():
    g = _make_controller()
    raw = "\x1b[1;32mgreen\x1b[0m\n"
    gc.CAPTURE, gc.CAPTURE_LOG = True, ""
    try:
        g._process_incoming(raw)
        captured = gc.CAPTURE_LOG
    finally:
        gc.CAPTURE, gc.CAPTURE_LOG = False, ""
    assert captured == raw, "a capture file is evidence — it must keep what the device sent"


def test_timestamps_land_on_the_text_not_the_escape():
    """A stamp must prefix the visible line. If the escape were still there the line would
    start with the escape and the stamp would sit in front of invisible bytes."""
    g = _make_controller()
    gc.TIMESTAMPS = True
    try:
        g._process_incoming("\x1b[1;32mhello\x1b[0m\n")
    finally:
        gc.TIMESTAMPS = False
    text = g.output_buffer.text
    assert "\x1b" not in text
    assert "] hello" in text, text


def test_an_escape_split_across_a_pause_does_not_leak_on_resume():
    """Ctrl+P stops the DISPLAY, not the reading. The carry has to advance while paused or
    the held tail is printed as junk the moment you resume."""
    g = _make_controller()
    g._process_incoming("\x1b[1;", display=False)     # paused, sequence starts
    g._process_incoming("32mAFTER\n", display=True)   # resumed, sequence completes
    assert "32m" not in g.output_buffer.text
    assert "AFTER" in g.output_buffer.text


def test_an_escape_only_read_appends_nothing():
    """A read that is entirely a partial escape must not append an empty string and disturb
    the line-start tracker that timestamping depends on."""
    g = _make_controller()
    g._process_incoming("first\n")
    before = g._ts_line_start
    g._process_incoming("\x1b[1;")
    assert g._ts_line_start is before


def test_an_impossible_escape_tail_is_released_immediately():
    """Line noise: an ESC followed by something that can never continue a sequence. Holding it
    would stall the next _MAX_ESC_CARRY bytes of real device output for no reason."""
    out, carry = strip_ansi("data \x1b\nmore text\n")
    assert carry == ""
    assert "more text" in out


def test_a_real_prefix_is_still_held():
    """The counterpart — don't release something that genuinely is mid-sequence."""
    for prefix in ("\x1b", "\x1b[", "\x1b[1;3", "\x1b]0;partial title"):
        out, carry = strip_ansi("x" + prefix)
        assert carry == prefix, prefix
        assert out == "x"


def test_an_unterminated_osc_does_not_leak_its_body():
    """The regex bug this file's prefix test caught: `]` (0x5D) is inside the textbook
    two-character escape range `[@-Z\\-_]`, so an OSC still waiting for its terminator was
    matched as a bare two-char escape and its body printed as junk."""
    out, carry = strip_ansi("\x1b]0;partial title")
    assert out == ""
    assert carry == "\x1b]0;partial title"
    # ...and it completes cleanly on the next read
    out, carry = strip_ansi("\x07shell$ ", carry)
    assert out == "shell$ " and carry == ""


def test_string_sequence_introducers_are_all_handled():
    """DCS/SOS/PM/APC carry bodies exactly like OSC — none may be eaten as a two-char escape."""
    for intro in ("P", "]", "X", "^", "_"):
        raw = f"\x1b{intro}payload-here\x1b\\visible"
        out, carry = strip_ansi(raw)
        assert out == "visible", (intro, out)
        assert carry == ""
