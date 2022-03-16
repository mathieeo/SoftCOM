"""Exceptions"""


class SerialDeviceOpenError(Exception):
    """Raised serial device failed to open"""

    def __init__(self):
        super().__init__('Checksum error.')
