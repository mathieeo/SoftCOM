#!/usr/bin/env python3
"""
    Serial Simulator
    mainly used for testing without hardware.
"""
import os
import random

_dir = os.path.dirname(os.path.realpath(__file__))
_log_path = os.path.join(_dir, 'test_log.txt')

# Load the sample lines defensively. This used to run bare at import time, so a missing
# test_log.txt crashed the WHOLE app on `import gui_controller` (and the test suite), and an
# empty file made random.choice() raise IndexError the moment the simulator ran.
_FALLBACK = [
    "[SIM] system boot ok",
    "[SIM] sensor 0x3C online, temp=23.4C",
    "[SIM] rx packet len=64 crc=ok",
    "[SIM] warning: buffer 82% full",
    "[SIM] heartbeat",
]
try:
    with open(_log_path, encoding='UTF-8') as _f:
        lines = [ln for ln in _f.read().splitlines() if ln.strip()]
except OSError:
    lines = []
if not lines:
    lines = _FALLBACK


def get_random_string():
    """

    :return:
    """
    line = random.choice(lines)
    return str(line)


def random_text_generator():
    """

    :return:
    """
    return get_random_string() + "\n"


def respond(command):
    """Simulated device reply to a command the user SENT (simulator mode only).

    A real serial console answers what you type; the old simulator ignored sent commands entirely, so in
    `-s` mode you could never see a reply and the send→receive round-trip was untestable. This gives the fake
    device a tiny command interpreter so sending actually produces a response.

    Control bytes (Ctrl+C = 0x03, Ctrl+D = 0x04) get their own acknowledgements; everything else is matched
    against a few canned commands, otherwise a generic ack. Returns a newline-terminated string, or '' for a
    bare Enter (nothing to answer).
    """
    if not command:
        return ""
    if command == "\x03":
        return "[SIM] ^C interrupt\n"
    if command == "\x04":
        return "[SIM] ^D end-of-input\n"
    cmd = command.strip()
    if not cmd:
        return ""
    low = cmd.lower()
    if low in ("help", "?"):
        return "[SIM] commands: help, status, version, echo <text>\n"
    if low == "status":
        return "[SIM] status: online  uptime=12345s  errors=0\n"
    if low == "version":
        return "[SIM] SoftCOM simulator v1.0\n"
    if low.startswith("echo "):
        return cmd[5:] + "\n"
    return f"[SIM] ack: {cmd}\n"
