#!/usr/bin/env python3
"""
    SoftCOM is a free software for accessing the serial port.
"""
# pylint: disable=W0603
import os
import sys
from os.path import exists

# Intra-package imports must be RELATIVE. They used to be a try/except pair — absolute
# `from SoftCOM import …` first, falling back to flat `from gui_controller import …` — but
# gui_controller.py itself imported `support`/`version` flat, so the absolute branch ALWAYS
# raised ImportError and the flat fallback only worked when SoftCOM/ happened to be on
# sys.path (i.e. running from a source checkout, which is exactly how the tests ran).
# Installed from a wheel, `softcom --version` died instantly with
# "ModuleNotFoundError: No module named 'support'" — the shipped console script never ran.
from .gui_controller import GuiController
from .support import InputDialog, MessageDialog, RadioListDialog, SaveSettings
from .version import __version__

# get the project path (still used to find bundled read-only data like HELP/LICENSE)
__location__ = os.path.dirname(os.path.realpath(__file__))


def _settings_path() -> str:
    """Where the user's port configuration lives.

    It used to be `<package dir>/settings.json` — i.e. INSIDE site-packages once installed.
    That is wrong three ways: site-packages is often read-only (a system/venv-wide install
    then dies on first run when it tries to save), the file is destroyed by every upgrade or
    reinstall, and two users on one machine share (and clobber) each other's port config.

    Use the per-user config directory instead, and MIGRATE an existing package-local
    settings.json on first run so nobody loses the port they already configured.
    """
    if os.name == "nt":
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
        cfg_dir = os.path.join(base, "SoftCOM")
    else:
        base = os.environ.get("XDG_CONFIG_HOME") or os.path.join(os.path.expanduser("~"), ".config")
        cfg_dir = os.path.join(base, "softcom")

    new_path = os.path.join(cfg_dir, "settings.json")
    legacy = os.path.join(__location__, "settings.json")
    try:
        os.makedirs(cfg_dir, exist_ok=True)
        if os.path.exists(legacy) and not os.path.exists(new_path):
            import shutil  # pylint: disable=import-outside-toplevel
            shutil.copy2(legacy, new_path)     # copy, not move: leave the old file for a downgrade
    except OSError:
        # An unwritable home is still no reason to refuse to start — fall back to the old
        # location and let SaveSettings surface any write error normally.
        return legacy
    return new_path


__SettingsFilePath___ = _settings_path()


def _port_present(path: str) -> bool:
    """Can we pre-check that this serial device is present before opening it?

    On POSIX a serial device is a /dev node we can stat, so a missing node means it's unplugged and
    we can warn early. On Windows a COM port is NOT a filesystem path — os.path.exists("COM4") is
    always False — so pre-checking with exists() would wrongly reject EVERY COM port and quit the
    app before it could open one (SoftCOM was unusable on Windows because of this). There we can't
    stat it, so return True and defer to open_dev(), which fails with a clean dialog if the port is
    bad.
    """
    if os.name != "posix":
        return True
    return exists(path)


def _detect_ports():
    """List the serial ports present RIGHT NOW so first-run config can OFFER them, instead of making the user
    type a device path blind — the #1 serial-terminal friction ("what is my port even called?"). Returns a
    list of (device, label) for a RadioListDialog, most-descriptive label first. Any failure (pyserial missing,
    or a platform enumeration quirk) returns [] so the caller falls back to the old type-a-path flow — this is
    a pure convenience layer that can never break config."""
    try:
        from serial.tools import \
            list_ports  # pylint: disable=import-outside-toplevel
        ports = list(list_ports.comports())
    except Exception:                          # pylint: disable=broad-except
        return []

    def label(p):
        desc = (getattr(p, "description", "") or "").strip()
        return f"{p.device} — {desc}" if desc and desc.lower() != "n/a" else p.device

    # a real USB-serial adapter has a VID/PID; float those above virtual/bluetooth ports
    ports.sort(key=lambda p: (getattr(p, "vid", None) is None, p.device))
    return [(p.device, label(p)) for p in ports if getattr(p, "device", None)]


def _print_dev_diagnostics(device, baud, bits, parity, stopbits, simulator, settings_path):
    """Developer mode (--developer / -d): print the RESOLVED connection config to stderr before the TUI takes
    over, so a developer chasing a "why won't it connect" issue can see exactly what SoftCOM resolved (device,
    baud, framing) and where its settings live. Printed before the full-screen app, so it's visible on launch
    and again after quit. The flag was a NO-OP before this — argparse defined --developer but nothing ever read
    parsed.developer, so `softcom -d` silently did nothing despite the "Run in developer mode." help text."""
    framing = f"{bits}{parity}{stopbits}"
    print("── SoftCOM developer diagnostics ──", file=sys.stderr)
    print(f"  version : {__version__}", file=sys.stderr)
    print(f"  mode    : {'simulator' if simulator else 'serial'}", file=sys.stderr)
    print(f"  device  : {device}", file=sys.stderr)
    print(f"  baud    : {baud if baud else '(n/a)'}", file=sys.stderr)
    print(f"  framing : {framing}  (data bits / parity / stop bits)", file=sys.stderr)
    print(f"  settings: {settings_path}", file=sys.stderr)
    print("───────────────────────────────────", file=sys.stderr)


def main():
    """
     main entry
    """
    import argparse
    parser = argparse.ArgumentParser(
        description='SoftCOM — serial port terminal'
    )
    parser.add_argument('--version', '-v', action='version', version=f'SoftCOM {__version__}')
    parser.add_argument('--developer', '-d', action='store_true', default=False,
                        help='Run in developer mode.')
    parser.add_argument('--config', '-c', action='store_true', default=False,
                        help='Reset serial port configuration on startup.')
    parser.add_argument('--simulator', '-s', action='store_true', default=False,
                        help='Run in simulator mode (no hardware required)')
    parsed, _ = parser.parse_known_args()

    # check if the user wants to reconfigure — remove the old settings file
    if parsed.config:
        try:
            os.remove(__SettingsFilePath___)
        except FileNotFoundError:
            pass  # nothing to remove on first run

    # create / load the settings file
    settings = SaveSettings(__SettingsFilePath___)
    DEVICE_PATH, BAUDRATE, BITS, PARITY, STOPBITS = settings.get_settings()

    # apply defaults for fields that may be missing from old settings files
    if PARITY is None:
        PARITY = 'N'
    if STOPBITS is None:
        STOPBITS = 1
    if BITS is None:
        BITS = 8

    if parsed.simulator:
        DEVICE_PATH = "simulator"
        BAUDRATE = ""
    else:
        # ── The saved port is gone (POSIX only — see _port_present) ──────────────────
        # A USB-serial adapter does not keep the same device node. Replug it, move it to a
        # different hub port, or boot with a second adapter attached, and /dev/tty.usbserial-A1
        # comes back as -A2 — on macOS and Linux this is routine, not an edge case. The old code
        # dead-ended here ("… is not found.", exit 1) and the only way back in was knowing about
        # the -c flag, which nothing on screen mentions and which throws away the baud, framing,
        # line-ending and local-echo settings as collateral.
        #
        # Offer what IS present instead. The port moved; the device did not, so keep the saved
        # baud and framing and only swap the path.
        if DEVICE_PATH is not None and not _port_present(str(DEVICE_PATH)):
            detected = _detect_ports()
            choice = None
            if detected:
                choice = RadioListDialog(
                    "Device moved",
                    text=f"{DEVICE_PATH} is no longer present.\n"
                         f"Select the port it moved to — baud and framing are kept.",
                    values=detected
                ).get_result()
            if choice is None:
                # Nothing detected, or the user cancelled. Still exit, but say how to get back —
                # a dead end with no next step is what made this worth fixing.
                MessageDialog(
                    "Failed",
                    f"{DEVICE_PATH} is not found, and no other serial port was detected.\n"
                    f"Reconnect the adapter, or run 'softcom -c' to reconfigure."
                )
                sys.exit(1)
            DEVICE_PATH = choice
            settings.set_settings(DEVICE_PATH, BAUDRATE, BITS, PARITY, STOPBITS)

        if DEVICE_PATH is None:
            # ── Device path — OFFER the detected ports first, so nobody has to type a path blind ──
            detected = _detect_ports()
            if detected:
                choice = RadioListDialog(
                    "Configuration",
                    text="Select the serial device (or choose 'Type a path…' if yours isn't listed).",
                    values=detected + [("__manual__", "Type a path…")]
                ).get_result()
                if choice is None:
                    sys.exit(0)  # user cancelled
                # a detected port is already present — skip the manual type-and-verify step below
                DEVICE_PATH = None if choice == "__manual__" else choice

            if DEVICE_PATH is None:
                # no ports detected, or the user chose to type one
                DEVICE_PATH = InputDialog(
                    "Configuration",
                    text="Please type device path [/dev/ttyUSB0, COM4]."
                ).get_result()
                if DEVICE_PATH is None:
                    sys.exit(0)  # user cancelled
                DEVICE_PATH = DEVICE_PATH.strip()   # a pasted path often carries trailing spaces/newline,
                if not DEVICE_PATH:                 # which make exists()/open() fail with a confusing error
                    MessageDialog("Failed", "No device path entered.")
                    sys.exit(1)
                if not _port_present(DEVICE_PATH):
                    MessageDialog("Failed", f"{DEVICE_PATH} is not listed.")
                    sys.exit(1)

            # ── Baud rate ─────────────────────────────────────────────────
            BAUDRATE = RadioListDialog(
                "Configuration",
                text="Baud rate.",
                values=[
                    ("4800",   "4800 bit/s"),
                    ("9600",   "9600 bit/s"),
                    ("19200",  "19200 bit/s"),
                    ("38400",  "38400 bit/s"),
                    ("57600",  "57600 bit/s"),
                    ("115200", "115200 bit/s"),
                ]
            ).get_result()
            if BAUDRATE is None:
                sys.exit(0)

            # ── Data bits ────────────────────────────────────────────────
            BITS = RadioListDialog(
                "Configuration",
                text="Data bits.",
                values=[
                    (5, "5"),
                    (6, "6"),
                    (7, "7"),
                    (8, "8 (most common)"),
                ]
            ).get_result()
            if BITS is None:
                sys.exit(0)

            # ── Parity ───────────────────────────────────────────────────
            PARITY = RadioListDialog(
                "Configuration",
                text="Parity.",
                values=[
                    ('N', "None (most common)"),
                    ('E', "Even"),
                    ('O', "Odd"),
                ]
            ).get_result()
            if PARITY is None:
                sys.exit(0)

            # ── Stop bits ────────────────────────────────────────────────
            STOPBITS = RadioListDialog(
                "Configuration",
                text="Stop bits.",
                values=[
                    (1, "1 (most common)"),
                    (2, "2"),
                ]
            ).get_result()
            if STOPBITS is None:
                sys.exit(0)

            settings.set_settings(DEVICE_PATH, BAUDRATE, BITS, PARITY, STOPBITS)

    # developer mode: show what SoftCOM resolved before the full-screen TUI takes over
    if parsed.developer:
        _print_dev_diagnostics(DEVICE_PATH, BAUDRATE, BITS, PARITY, STOPBITS,
                               parsed.simulator, __SettingsFilePath___)

    # start the GUI controller
    GuiController(DEVICE_PATH, BAUDRATE, parsed.simulator,
                  parity=PARITY, stopbits=STOPBITS, bytesize=BITS,
                  line_ending=settings.line_ending, local_echo=settings.local_echo,
                  settings_store=settings)
    # persist any runtime state
    settings.save_file()


if __name__ == "__main__":
    main()
