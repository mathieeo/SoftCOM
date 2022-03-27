#!/usr/bin/env python3
"""
    Serial Manager provides a communication interface with the serial device.
"""
import serial

from support.exceptions import SerialDeviceOpenError  # pylint: disable=E0401


class SerialManager:
    # pylint: disable=E1101
    # todo why^^?
    """
        SerialManager  provides a communication interface with the serial device.
    """

    def __init__(self, serial_device_path, serial_device_rate):
        """
            Initial call is used to configure the default parameters
        """
        self.ser = serial.Serial(baudrate=serial_device_rate)
        self.device_path = serial_device_path
        self.rate = serial_device_rate
        self.is_open = False

    def is_dev_open(self):
        """
             is_open is used to check if the serial device is open.
        """
        return self.is_open

    def open_dev(self):
        """
        open_dev is used to open the serial port
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
            close_dev is used to close the serial device
        """
        self.ser.close()

    def read(self):
        """
            Read is used to read until EOL is found. this function returns string decoded to UTF-8
        """
        if self.ser.inWaiting():
            char = self.ser.read_until()
            if char:
                return char.decode('utf8')
        return ""

    def exe_command(self, command):
        """
            execute a serial commands
        """
        self.ser.write(command.encode())
        self.ser.flush()
