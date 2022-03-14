#!/usr/bin/env python3
"""
    Placeholder
"""
# pylint: disable=ًW0603
import os
import argparse
from prompt_toolkit.completion import WordCompleter
from support.input_dialog import InputDialog
from support.radiolist_dialog import RadioListDialog
from support.save_settings import SaveSettings
from support.gui_controller import GuiController

__location__ = os.path.dirname(os.path.realpath(__file__))
__SettingsFilePath___ = os.path.join(__location__, 'settings.json')

device_completer = WordCompleter(['/dev/', '/dev/tty', '/dev/ttyUSB'])

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('--developer', '-d', action='store_true', default=False, help='Run in developer mode.')
    parser.add_argument('--config', '-c', action='store_true', default=False, help='Run in from startup')
    parser.parse_args()
    parsed, _ = parser.parse_known_args()

    if parsed.config:
        os.remove(__SettingsFilePath___)

    settings = SaveSettings(__SettingsFilePath___)
    device_path, rate, bits = settings.get_settings()
    if device_path is None:
        device_path = InputDialog("Configuration", text="Please type device path [/dev/ttyUSB0].",
                                  completer=device_completer).get_result()
        rate = RadioListDialog("Configuration", text="Bit rates.", values=[("4800", "4800 bit/s"),
                                                                           ("9600", "9600 bit/s"),
                                                                           ("19200", "19200 bit/s"),
                                                                           ("38400", "38400 bit/s"),
                                                                           ("57600", "57600 bit/s"),
                                                                           ("115200", "115200 bit/s")
                                                                           ]).get_result()
        bits = 8  # RadioListDialog("Configuration", text="Bits.", values=[("7", "7"),
        #                                                        ("8", "8"),
        #                                                   ]).get_result()
        settings.set_settings(device_path, rate, bits)

    GuiController(f"{device_path} {rate} {bits}")
    settings.save_file()
