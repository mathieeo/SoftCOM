#!/usr/bin/env python3
"""
    Placeholder
"""
# pylint: disable=ًW0603
import os
import sys
import argparse
from os.path import exists
from prompt_toolkit.completion import WordCompleter
from support.input_dialog import InputDialog
from support.radiolist_dialog import RadioListDialog
from support.save_settings import SaveSettings
from support.message_dialog import MessageDialog
from support.gui_controller import GuiController

__location__ = os.path.dirname(os.path.realpath(__file__))
__SettingsFilePath___ = os.path.join(__location__, 'settings.json')

device_completer = WordCompleter(['/dev/', '/dev/tty', '/dev/ttyUSB'])

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('--developer', '-d', action='store_true', default=False, help='Run in developer mode.')
    parser.add_argument('--config', '-c', action='store_true', default=False, help='Run in from startup')
    parser.add_argument('--simulator', '-s', action='store_true', default=False, help='Run in simulator mode')
    parser.parse_args()
    parsed, _ = parser.parse_known_args()

    if parsed.config:
        os.remove(__SettingsFilePath___)

    settings = SaveSettings(__SettingsFilePath___)
    DEVICE_PATH, RATE, BITS = settings.get_settings()

    if parsed.simulator:
        DEVICE_PATH = "simulator"
        RATE = ""
    else:
        if DEVICE_PATH is not None and not exists(str(DEVICE_PATH)):
            MessageDialog("Failed", f"{DEVICE_PATH} is not found.")
            sys.exit(1)

        if DEVICE_PATH is None:
            DEVICE_PATH = InputDialog("Configuration", text="Please type device path [/dev/ttyUSB0].",
                                      completer=device_completer).get_result()
            if not exists(DEVICE_PATH):
                MessageDialog("Failed", f"{DEVICE_PATH} is not listed.")
                sys.exit(1)

            RATE = RadioListDialog("Configuration", text="Bit rates.", values=[("4800", "4800 bit/s"),
                                                                               ("9600", "9600 bit/s"),
                                                                               ("19200", "19200 bit/s"),
                                                                               ("38400", "38400 bit/s"),
                                                                               ("57600", "57600 bit/s"),
                                                                               ("115200", "115200 bit/s")
                                                                               ]).get_result()
            BITS = 8  # RadioListDialog("Configuration", text="Bits.", values=[("7", "7"),
            #                                                        ("8", "8"),
            #                                                   ]).get_result()
            settings.set_settings(DEVICE_PATH, RATE, BITS)
    GuiController(DEVICE_PATH, RATE, parsed.simulator)
    settings.save_file()
