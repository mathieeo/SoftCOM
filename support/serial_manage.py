#!/usr/bin/env python3
"""
    placeholder
"""
import os

import serial

from support.exceptions import SerialDeviceOpenError  # pylint: disable=E0401

# import time




class SerialManager:
    # pylint: disable=E1101
    # todo why^^?
    """
        placeholder
    """

    def __init__(self, serial_device_path, serial_device_rate):
        """
            placeholder
        """
        self.ser = serial.Serial(baudrate=serial_device_rate)
        self.device_path = serial_device_path
        self.rate = serial_device_rate
        self.is_open = False

    def is_dev_open(self):
        """
             is_open
        """
        return self.is_open

    def open_dev(self):
        """
        placeholder
        :return:
        """
        try:
            self.ser = serial.Serial(self.device_path, self.rate, timeout=0.1)
            if self.ser.isOpen():
                self.is_open = True
            else:
                self.is_open = False
                raise SerialDeviceOpenError()
        except SerialDeviceOpenError as err:
            raise err

    def close_dev(self):
        """
        placeholder
        """
        self.ser.close()

    def read(self):
        """
            read
        """
        if self.ser.inWaiting():
            char = self.ser.read_until()
            if char:
                try:
                    return char.decode('utf8')
                except:  # todo
                    return "[Unable to read]"
        return ""

    def exe_command(self, command):
        """
            execute a serial commands
        """
        self.ser.write(command.encode())
        self.ser.flush()
