"""Secrets must not end up on disk.

SoftCOM is a serial TERMINAL. Logging into a device means typing a username at its `login:`
prompt and a password at its `Password:` prompt and pressing Enter after each — so the password
goes through the same action_send as every other command. Two things followed from that:

  1. `~/.softcom_history` was written with a plain open(), i.e. at the process umask — 0644 here,
     so every other account on the machine could read the device passwords. Shells keep their
     history 0600 for exactly this reason.
  2. The password was recorded in the history list, the on-disk file and the visible
     "Recent Commands" panel, and (with local echo on) written into the output log that Ctrl+S
     saves and Ctrl+W captures.

These tests pin both. The prompt detection is a heuristic on purpose and is asymmetric: a false
positive costs one line of history, a false negative writes a password to disk — so the tests
below check the safe direction is the one it fails toward.
"""
import os
import stat
import sys
from unittest import mock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import SoftCOM.gui_controller as gc

# ── File permissions ──────────────────────────────────────────────────────────

class _HistoryOnly:
    """Just enough object to drive _save_history without building the whole TUI."""
    _save_history = gc.GuiController._save_history

    def __init__(self, entries):
        self.command_history = list(entries)


def test_history_file_is_owner_only(tmp_path):
    hist = tmp_path / ".softcom_history"
    with mock.patch.object(gc, "_HISTORY_FILE", str(hist)):
        _HistoryOnly(["admin", "show version"])._save_history()
    mode = stat.S_IMODE(os.stat(hist).st_mode)
    assert mode == 0o600, f"history is {oct(mode)}, must be 0600 — it can hold device passwords"


def test_history_file_is_never_briefly_world_readable(tmp_path):
    """Created via os.open with the mode, not open()+chmod, so there is no window where the
    file exists at 0644. Asserted by checking no chmod is needed on a fresh create."""
    hist = tmp_path / ".softcom_history"
    with mock.patch.object(gc, "_HISTORY_FILE", str(hist)):
        with mock.patch.object(gc.os, "chmod", side_effect=AssertionError("should not need chmod")):
            _HistoryOnly(["a"])._save_history()
    assert stat.S_IMODE(os.stat(hist).st_mode) == 0o600


def test_an_existing_0644_history_is_repaired(tmp_path):
    """Users upgrading already have the file at 0644 — rewriting must tighten it, because
    O_CREAT's mode is ignored when the file already exists."""
    hist = tmp_path / ".softcom_history"
    hist.write_text("old\n")
    os.chmod(hist, 0o644)
    with mock.patch.object(gc, "_HISTORY_FILE", str(hist)):
        _HistoryOnly(["new"])._save_history()
    assert stat.S_IMODE(os.stat(hist).st_mode) == 0o600


# ── Prompt detection ──────────────────────────────────────────────────────────

@pytest.mark.parametrize("tail", [
    "Password:",
    "Password: ",
    "password:",
    "PASSWORD:",
    "root@target's password:",
    "[sudo] password for matt:",
    "Enter passphrase for key '/root/.ssh/id_ed25519':",
    "Enter PIN:",
    "login as: admin\r\nPassword:",
    "Passcode:",
])
def test_secret_prompts_are_detected(tail):
    assert gc._SECRET_PROMPT_RE.search(tail), f"missed a secret prompt: {tail!r}"


@pytest.mark.parametrize("tail", [
    "root@target:~#",
    "$ ",
    "login:",                      # the USERNAME prompt is not a secret
    "Username:",
    "Password changed successfully",   # word appears but the device is not asking
    "See 'man password' for details",
    "",
    "Last login: Mon Aug 10 09:14:22 2026",
])
def test_ordinary_prompts_are_not_treated_as_secrets(tail):
    assert not gc._SECRET_PROMPT_RE.search(tail), f"false positive on: {tail!r}"


def test_prompt_must_be_at_the_end_of_what_the_device_sent():
    """A password prompt scrolled past is history, not a live question."""
    assert not gc._SECRET_PROMPT_RE.search("Password:\r\nLogin incorrect\r\nroot@target:~# ")


# ── Wired into the real send path ─────────────────────────────────────────────

def _make_controller():
    """Build a real GuiController the same way the other suites do — no stub on the seam
    under test (action_send / _process_incoming both run for real)."""
    import time

    from prompt_toolkit.application import Application, create_app_session
    from prompt_toolkit.input import DummyInput
    from prompt_toolkit.output import DummyOutput
    Application.run = lambda self, *a, **k: None
    with create_app_session(input=DummyInput(), output=DummyOutput()):
        g = gc.GuiController("simulator", "", simulator_mode=True)
    gc.UPDATE_LOG_FLAG = False
    time.sleep(0.03)
    return g


def _send(controller, line):
    controller.input_buffer.text = line
    controller.action_send()


def test_a_password_typed_at_the_device_prompt_never_reaches_history(tmp_path):
    g = _make_controller()
    with mock.patch.object(gc, "_HISTORY_FILE", str(tmp_path / "h")):
        g.command_history.clear()
        # The device asks, exactly as a real login does — no trailing newline.
        g._process_incoming("login: ")
        _send(g, "admin")                     # username IS ordinary history
        g._process_incoming("\r\nPassword: ")
        _send(g, "hunter2")                   # the secret
        g._process_incoming("\r\nroot@target:~# ")
        _send(g, "show version")

    assert "admin" in g.command_history
    assert "show version" in g.command_history
    assert "hunter2" not in g.command_history
    assert "hunter2" not in (tmp_path / "h").read_text()
    # and it is not in the visible Recent Commands panel either
    assert "hunter2" not in g.history_buffer.text


def test_the_password_is_still_actually_sent_to_the_device():
    """Suppressing the RECORD must not suppress the TRANSMISSION."""
    g = _make_controller()
    sent = []
    g.send_command = sent.append
    g._process_incoming("Password: ")
    _send(g, "hunter2")
    assert any("hunter2" in s for s in sent), "the device must still receive the password"


def test_local_echo_of_a_secret_is_masked():
    """Local echo writes into the log that Ctrl+S saves and Ctrl+W captures."""
    g = _make_controller()
    g._process_incoming("Password: ")
    before = len(g.output_buffer.text)
    _send(g, "hunter2")
    written = g.output_buffer.text[before:]
    assert "hunter2" not in written
    assert "*******" in written


def test_an_ansi_coloured_password_prompt_is_still_detected():
    """Prompts arrive coloured; detection runs on the ANSI-stripped display text."""
    g = _make_controller()
    g._process_incoming("\x1b[1;31mPassword:\x1b[0m ")
    assert g.device_awaiting_secret()


def test_the_next_command_after_the_secret_is_recorded_normally(tmp_path):
    """The prompt is consumed on send — a stale 'Password:' must not swallow later history."""
    g = _make_controller()
    with mock.patch.object(gc, "_HISTORY_FILE", str(tmp_path / "h")):
        g.command_history.clear()
        g._process_incoming("Password: ")
        _send(g, "secret")
        _send(g, "uname -a")        # device has not replied yet; this is NOT a secret
    assert "uname -a" in g.command_history
    assert "secret" not in g.command_history


def test_a_paused_display_still_suppresses_the_secret():
    """Ctrl+P freezes the DISPLAY; the device is still asking and the secret must still be hidden."""
    g = _make_controller()
    g._process_incoming("Password: ", display=False)
    assert g.device_awaiting_secret()
