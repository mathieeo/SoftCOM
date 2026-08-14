"""What happens when the adapter goes away.

Two failures that both used to end with the user quietly losing something, and neither of which
any other suite covers:

  1. The port dies mid-session. `SerialManager.exe_command` swallows the exception and only flips
     is_dev_open() to False, so `action_send` carried on as if the write had worked — it cleared
     the input bar and appended the line to history. The command vanished AND the history claimed
     it had been sent. On a flaky USB-serial adapter that is the difference between retyping one
     line and believing you told a device to reboot.

  2. The port comes back under a different name. Replug a USB-serial adapter, or move it to
     another hub port, and /dev/tty.usbserial-A1 becomes -A2. Startup dead-ended on that with
     "… is not found." and exit 1; the only way back was knowing about -c, which nothing on
     screen mentions and which also discards baud, framing, line ending and local echo.

These are the first tests to touch softcom.py's startup path at all.
"""
import os
import sys
import time
from unittest import mock

import pytest
import serial

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import SoftCOM.gui_controller as gc
from SoftCOM.support.serial_manage import SerialManager

# ── 1. A write that failed must not look like a write that worked ─────────────

class _DeadPort:
    """A pyserial handle whose adapter has just been pulled: reads nothing, raises on write."""
    is_open = True
    in_waiting = 0

    def write(self, _data):
        raise serial.SerialException("device reports readiness to read but returned no data")

    def flush(self):
        pass

    def close(self):
        pass


def _controller():
    from prompt_toolkit.application import Application, create_app_session
    from prompt_toolkit.input import DummyInput
    from prompt_toolkit.output import DummyOutput
    Application.run = lambda self, *a, **k: None
    with create_app_session(input=DummyInput(), output=DummyOutput()):
        g = gc.GuiController("simulator", "", simulator_mode=True)
    gc.UPDATE_LOG_FLAG = False
    time.sleep(0.03)
    return g


def _with_dead_port(g):
    """Point the controller at a real SerialManager wrapping a port that will fail on write."""
    sm = SerialManager("/dev/tty.usbserial-GONE", 115200)
    sm.ser = _DeadPort()
    sm.is_open = True
    g.simulator_mode = False
    g.ser_dev = sm
    return sm


def test_a_command_the_port_refused_is_not_recorded_as_sent(tmp_path):
    g = _controller()
    _with_dead_port(g)
    with mock.patch.object(gc, "_HISTORY_FILE", str(tmp_path / "h")):
        g.command_history.clear()
        g.input_buffer.text = "reboot"
        g.action_send()

    assert "reboot" not in g.command_history, "history claimed a command was sent that never left"
    assert not os.path.exists(tmp_path / "h") or "reboot" not in (tmp_path / "h").read_text()


def test_a_command_the_port_refused_stays_in_the_input_bar():
    """So it can be retried after replugging, instead of having to be retyped from memory."""
    g = _controller()
    _with_dead_port(g)
    g.input_buffer.text = "reboot"
    g.action_send()
    assert g.input_buffer.text == "reboot"


def test_a_failed_send_says_so():
    g = _controller()
    _with_dead_port(g)
    before = len(g.output_buffer.text)
    g.input_buffer.text = "reboot"
    g.action_send()
    written = g.output_buffer.text[before:]
    assert "NOT SENT" in written and "reboot" in written


def test_a_failed_send_still_masks_a_secret():
    """The failure message must not leak what the history would have refused to keep."""
    g = _controller()
    _with_dead_port(g)
    g._process_incoming("Password: ")
    before = len(g.output_buffer.text)
    g.input_buffer.text = "hunter2"
    g.action_send()
    written = g.output_buffer.text[before:]
    assert "NOT SENT" in written
    assert "hunter2" not in written
    assert "*******" in written


def test_a_healthy_port_is_unaffected(tmp_path):
    """The guard must not fire on the normal path — a live port still records history."""
    g = _controller()
    sm = SerialManager("/dev/tty.usbserial-OK", 115200)

    class _LivePort(_DeadPort):
        def write(self, _data):
            return len(_data)

    sm.ser = _LivePort()
    sm.is_open = True
    g.simulator_mode = False
    g.ser_dev = sm
    with mock.patch.object(gc, "_HISTORY_FILE", str(tmp_path / "h")):
        g.command_history.clear()
        g.input_buffer.text = "uname -a"
        g.action_send()
    assert g.command_history == ["uname -a"]
    assert g.input_buffer.text == ""


def test_write_succeeded_is_true_with_no_port_and_in_simulator():
    """Never fail closed on a controller that has no real port — that would break simulator mode
    and every test that stubs send_command."""
    g = _controller()
    assert g._write_succeeded() is True          # simulator
    g.simulator_mode = False
    g.ser_dev = None
    assert g._write_succeeded() is True          # no port managed yet


# ── 2. The saved port moved — offer the ones that are actually there ──────────

@pytest.fixture(name="startup")
def _startup():
    """Drive softcom.main() with every dialog and the TUI itself replaced."""
    import SoftCOM.softcom as sc

    class _Settings:
        line_ending, local_echo = "LF", False

        def __init__(self, *_a):
            self.saved = None

        @staticmethod
        def get_settings():
            return ("/dev/tty.usbserial-A1", "115200", 8, 'N', 1)

        def set_settings(self, *a):
            self.saved = a

        def save_file(self):
            pass

    store = {}
    with mock.patch.object(sc, "SaveSettings", lambda *a: store.setdefault("s", _Settings())), \
         mock.patch.object(sc, "GuiController", lambda *a, **k: store.setdefault("gui", (a, k))), \
         mock.patch.object(sc, "MessageDialog", lambda *a: store.setdefault("msg", a)), \
         mock.patch.object(sc, "_port_present", lambda p: False), \
         mock.patch.object(sys, "argv", ["softcom"]):
        yield sc, store


def test_a_moved_port_offers_what_is_present_and_keeps_the_framing(startup):
    sc, store = startup
    with mock.patch.object(sc, "_detect_ports",
                           lambda: [("/dev/tty.usbserial-A2", "/dev/tty.usbserial-A2 — FT232R")]), \
         mock.patch.object(sc, "RadioListDialog",
                           lambda *a, **k: mock.Mock(get_result=lambda: "/dev/tty.usbserial-A2")):
        sc.main()

    assert "gui" in store, "startup exited instead of recovering"
    assert store["gui"][0][0] == "/dev/tty.usbserial-A2", "did not connect to the port the user picked"
    # baud and framing carried over untouched — the port moved, the device did not
    assert store["s"].saved == ("/dev/tty.usbserial-A2", "115200", 8, 'N', 1)


def test_cancelling_the_moved_port_dialog_exits_without_connecting(startup):
    sc, store = startup
    with mock.patch.object(sc, "_detect_ports", lambda: [("/dev/ttyUSB9", "/dev/ttyUSB9")]), \
         mock.patch.object(sc, "RadioListDialog",
                           lambda *a, **k: mock.Mock(get_result=lambda: None)):
        with pytest.raises(SystemExit) as exc:
            sc.main()
    assert exc.value.code == 1
    assert "gui" not in store


def test_no_ports_at_all_still_exits_but_names_the_way_back(startup):
    """The dead end is the bug; exiting is fine, exiting with no next step is not."""
    sc, store = startup
    with mock.patch.object(sc, "_detect_ports", lambda: []):
        with pytest.raises(SystemExit) as exc:
            sc.main()
    assert exc.value.code == 1
    assert "-c" in " ".join(store["msg"]), "the failure dialog must say how to reconfigure"
