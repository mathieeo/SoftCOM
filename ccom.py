#!/usr/bin/env python3
"""
    cCOM is a free software for accessing the serial port.
"""
import argparse
# pylint: disable=ًW0603
import os
import sys
from os.path import exists

from support.gui_controller import GuiController
from support.input_dialog import InputDialog
from support.message_dialog import MessageDialog
from support.radiolist_dialog import RadioListDialog
from support.save_settings import SaveSettings

# get the project path
__location__ = os.path.dirname(os.path.realpath(__file__))
# generate the settings file path
__SettingsFilePath___ = os.path.join(__location__, 'settings.json')

if __name__ == "__main__":
    # using argparse for managing the parameters passed to the app
    parser = argparse.ArgumentParser()
    # developer mode not used as of the moment
    parser.add_argument('--developer', '-d', action='store_true', default=False, help='Run in developer mode.')
    # config parameter is used to reset the serial port configuration page on startup.
    parser.add_argument('--config', '-c', action='store_true', default=False, help='Run in from startup')
    # simulator is used for testing the local run
    parser.add_argument('--simulator', '-s', action='store_true', default=False, help='Run in simulator mode')
    parser.parse_args()
    parsed, _ = parser.parse_known_args()

    # check if the user wants to configure then remove the old settings.
    if parsed.config:
        os.remove(__SettingsFilePath___)

    # create the settings file
    settings = SaveSettings(__SettingsFilePath___)
    # get the old configure values if there are any
    DEVICE_PATH, BAUDRATE, BITS = settings.get_settings()

    # if simulator mode then we need to change the name of the device
    if parsed.simulator:
        DEVICE_PATH = "simulator"
        BAUDRATE = ""
    else:
        # if the device is disconnected or cannot be found then we can't proceed.
        if DEVICE_PATH is not None and not exists(str(DEVICE_PATH)):
            MessageDialog("Failed", f"{DEVICE_PATH} is not found.")
            sys.exit(1)

        if DEVICE_PATH is None:
            # Configure page user is entering the device path
            DEVICE_PATH = InputDialog("Configuration", text="Please type device path [/dev/ttyUSB0, COM4].") \
                .get_result()
            # check if the device exist
            if not exists(DEVICE_PATH):
                MessageDialog("Failed", f"{DEVICE_PATH} is not listed.")
                sys.exit(1)

            # Configure page user is entering the baud-rate
            BAUDRATE = RadioListDialog("Configuration", text="Bit rates.", values=[("4800", "4800 bit/s"),
                                                                                   ("9600", "9600 bit/s"),
                                                                                   ("19200", "19200 bit/s"),
                                                                                   ("38400", "38400 bit/s"),
                                                                                   ("57600", "57600 bit/s"),
                                                                                   ("115200", "115200 bit/s")
                                                                                   ]).get_result()
            # todo do we need to set the bits and rest of the serial device options?
            BITS = 8
            # update the settings file with the new input
            settings.set_settings(DEVICE_PATH, BAUDRATE, BITS)
    # start the GUI controller
    GuiController(DEVICE_PATH, BAUDRATE, parsed.simulator)
    # save the settings file
    settings.save_file()
