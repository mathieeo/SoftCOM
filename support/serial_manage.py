#!/usr/bin/env python3
"""
    placeholder
"""
import time

import serial

from support.exceptions import SerialDeviceOpenError  # pylint: disable=E0401


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
            line = self.ser.readline()
            if line:
                return line[:-1]
        return ""

    def exe_command(self, command, ready_msg, timeout=60):
        """
            execute a serial commands
        :param command: what command you want to execute
        :param ready_msg: string to be seen before executing the command
        :param timeout: timeout in seconds
        :return:
        """
        print(f"\n\n\ntrying to execute [{command}]\n")
        self.ser.write(b"\n")
        start_time = time.time()
        while time.time() < start_time + timeout:
            if self.ser.inWaiting():
                line = self.ser.readline()
                if line:
                    print(line[:-1])
                    if ready_msg.encode() in line:
                        print("+")
                        print(line[:-1])
                        self.ser.write(f"{command}".encode())
                        self.ser.flushInput()
                        return
        # print("ERROR: Serial command is timed out.")
        # sys.exit(1)
