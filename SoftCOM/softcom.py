#!/usr/bin/env python3
"""
    SoftCOM is a free software for accessing the serial port.
"""
# pylint: disable=W0603
import os
import sys
from os.path import exists

try:
    from SoftCOM import (GuiController, InputDialog, MessageDialog,
                         RadioListDialog, SaveSettings)
    from SoftCOM.version import __version__
except ImportError:
    from gui_controller import GuiController
    from support import (InputDialog, MessageDialog, RadioListDialog,
                         SaveSettings)
    from version import __version__

# get the project path
__location__ = os.path.dirname(os.path.realpath(__file__))
# generate the settings file path
__SettingsFilePath___ = os.path.join(__location__, 'settings.json')


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

    if parsed.simulator:
        DEVICE_PATH = "simulator"
        BAUDRATE = ""
    else:
        # if a saved device path is no longer present, warn and exit
        if DEVICE_PATH is not None and not exists(str(DEVICE_PATH)):
            MessageDialog("Failed", f"{DEVICE_PATH} is not found.")
            sys.exit(1)

        if DEVICE_PATH is None:
            # ── Device path ──────────────────────────────────────────────
            DEVICE_PATH = InputDialog(
                "Configuration",
                text="Please type device path [/dev/ttyUSB0, COM4]."
            ).get_result()
            if DEVICE_PATH is None:
                sys.exit(0)  # user cancelled
            if not exists(DEVICE_PATH):
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

    # start the GUI controller
    GuiController(DEVICE_PATH, BAUDRATE, parsed.simulator,
                  parity=PARITY, stopbits=STOPBITS)
    # persist any runtime state
    settings.save_file()


if __name__ == "__main__":
    main()
