#!/usr/bin/env python3
"""
    Serial Manager provides a communication interface with the serial device.
"""
import serial

from .exceptions import SerialDeviceOpenError  # pylint: disable=E0401


class SerialManager:
    """
        SerialManager provides a communication interface with the serial device.
    """

    def __init__(self, serial_device_path, serial_device_rate,
                 parity='N', stopbits=1):
        """
            Initial call is used to configure the default parameters
        """
        self.ser = None
        self.device_path = serial_device_path
        self.rate = serial_device_rate
        self.parity = parity
        self.stopbits = stopbits
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
            self.ser = serial.Serial(
                self.device_path,
                baudrate=int(self.rate),
                parity=self.parity,
                stopbits=self.stopbits,
                timeout=0.1,
            )
            if self.ser.is_open:
                self.is_open = True
            else:
                self.is_open = False
                raise SerialDeviceOpenError()
        except serial.SerialException as err:
            raise SerialDeviceOpenError() from err
        except SerialDeviceOpenError as err:
            raise err

    def close_dev(self):
        """
            close_dev is used to close the serial device
        """
        if self.ser is not None:
            self.ser.close()

    def read(self):
        """
        Read one line of available data (up to 4096 bytes).
        Returns an empty string if nothing is waiting or the port is closed.
        """
        if self.ser is None or not self.is_open:
            return ""
        try:
            if self.ser.in_waiting:
                data = self.ser.read_until(size=4096)
                if data:
                    return data.decode('utf-8', errors='replace')
        except serial.SerialException:
            self.is_open = False
        return ""

    def exe_command(self, command):
        """
            execute a serial command
        """
        self.ser.write(command.encode())
        self.ser.flush()
