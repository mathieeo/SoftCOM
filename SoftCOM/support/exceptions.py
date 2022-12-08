"""
    Exceptions: this file is mainly used to define the exceptions for the app to raise/handle cases properly
"""


class SerialDeviceOpenError(Exception):
    """Raised serial device failed to open"""

    def __init__(self):
        super().__init__('Checksum error.')
