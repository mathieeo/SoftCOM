#!/usr/bin/env python3
"""
    placeholder
"""
import sys
import time
import serial

__serial_speed__ = 115200


class SerialManager:
    # pylint: disable=E1101
    # todo why^^?
    """
        placeholder
    """

    def __init__(self):
        """
            placeholder
        """
        self.ser = serial.Serial()

    def open_dev(self, dev_path):
        """
        placeholder
        :param dev_path:
        :return:
        """
        self.ser = serial.Serial(dev_path, __serial_speed__, timeout=0.1)
        if self.ser.isOpen():
            print(F"Serial port {dev_path} opened successfully.")
            # todo  raise SerialAppOpenFailed

    def wait_for_msg(self, msg, timeout=60):
        """
            wait for a specific serial line with timeout
        :param msg:
        :param timeout:
        :return:
        """
        start_time = time.time()
        self.ser.write("\n".encode())
        while time.time() < start_time + timeout:
            if self.ser.inWaiting():
                line = self.ser.readline()
                if line:
                    print(line[:-1])
                    if msg.encode() in line:
                        return
        print("ERROR: Serial command is timed out.")
        sys.exit(1)

    def exe_command(self, command, ready_msg, timeout=60):
        """
            execute a serial commands
        :param command: what command you want to execute
        :param ready_msg: string to be seen before executing the command
        :param timeout: timeout in seconds
        :return:
        """
        print(f"\n\n\ntrying to execute [{command}]\n")
        self.ser.write("\n".encode())
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
        print("ERROR: Serial command is timed out.")
        sys.exit(1)
