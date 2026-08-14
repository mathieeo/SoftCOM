#!/usr/bin/env python3
"""
    Serial Manager provides a communication interface with the serial device.
"""
import codecs

import serial

from .exceptions import SerialDeviceOpenError  # pylint: disable=E0401


class SerialManager:
    """
        SerialManager provides a communication interface with the serial device.
    """

    def __init__(self, serial_device_path, serial_device_rate,
                 parity='N', stopbits=1, bytesize=8):
        """
            Initial call is used to configure the default parameters
        """
        self.ser = None
        self.device_path = serial_device_path
        self.rate = serial_device_rate
        self.parity = parity
        self.stopbits = stopbits
        self.bytesize = bytesize
        self.is_open = False
        # A serial read returns whatever bytes are waiting, which can CUT a multi-byte UTF-8
        # character in half; decoding each chunk on its own turns that char (and its continuation
        # in the next read) into � garbage. An incremental decoder buffers the incomplete trailing
        # bytes and finishes them on the next read — so box-drawing, accents and emoji survive.
        self._decoder = codecs.getincrementaldecoder('utf-8')(errors='replace')

    def is_dev_open(self):
        """
             is_open is used to check if the serial device is open.
        """
        return self.is_open

    def open_dev(self):
        """
        open_dev is used to open the serial port
        """
        self._decoder.reset()          # fresh UTF-8 state for the new session
        try:
            self.ser = serial.Serial(
                self.device_path,
                baudrate=int(self.rate),
                bytesize=int(self.bytesize),   # the user's data-bits choice was collected but never applied
                parity=self.parity,
                stopbits=self.stopbits,
                timeout=0.1,
            )
            if self.ser.is_open:
                self.is_open = True
            else:
                self.is_open = False
                raise SerialDeviceOpenError()
        except (serial.SerialException, ValueError, TypeError) as err:
            # A bad or missing baud/bytesize (e.g. a partial or hand-edited settings.json where a
            # device is saved but the rate is None) makes int() raise ValueError/TypeError while
            # building the port — surface it as a clean "failed to open" dialog instead of letting
            # an uncaught traceback crash the whole app on startup.
            raise SerialDeviceOpenError() from err
        except SerialDeviceOpenError as err:
            raise err

    def close_dev(self):
        """
            close_dev is used to close the serial device
        """
        # Clear is_open too: without it is_dev_open() keeps reporting True after a close, so the
        # status bar and the disconnect watchdog would treat a deliberately-closed port as still live.
        self.is_open = False
        if self.ser is not None:
            self.ser.close()

    def read(self):
        """
        Read everything currently waiting on the port and return it decoded.
        Returns an empty string if nothing is waiting or the port is closed.

        Reading exactly ``in_waiting`` bytes (rather than ``read_until`` a
        newline) means an interactive shell's PROMPT — which has no trailing
        newline — shows up immediately instead of being held back until the
        next line arrives.
        """
        if self.ser is None or not self.is_open:
            return ""
        try:
            waiting = self.ser.in_waiting
            if waiting:
                data = self.ser.read(waiting)
                if data:
                    # Incremental decode so a UTF-8 char split across two reads isn't mangled.
                    return self._decoder.decode(data)
        except (serial.SerialException, OSError):
            self.is_open = False
        return ""

    def exe_command(self, command):
        """
            execute a serial command
        """
        if self.ser is None or not self.is_open:
            return
        try:
            self.ser.write(command.encode())
            self.ser.flush()
        except (serial.SerialException, OSError):
            self.is_open = False
