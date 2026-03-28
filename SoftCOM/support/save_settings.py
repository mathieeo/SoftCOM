#!/usr/bin/env python3
"""
    Save Settings
"""
import json
import os

# Use literal pyserial constant values to avoid import-time dependency on the serial package
_PARITY_NONE = 'N'
_STOPBITS_ONE = 1


class SaveSettings:
    """
        SaveSettings
    """

    def __init__(self, file):
        """
            __init__
        :param file:
        """
        self.device_path = None
        self.rate = None
        self.bits = None
        self.parity = None
        self.stopbits = None
        self.file = file
        self.settings_data = {'settings': []}
        if os.path.isfile(self.file):
            try:
                with open(self.file, encoding='UTF-8') as json_file:
                    self.settings_data = json.load(json_file)
                    for setting in self.settings_data['settings']:
                        self.device_path = setting.get('device_path')
                        self.rate = setting.get('rate')
                        self.bits = setting.get('bits')
                        self.parity = setting.get('parity', _PARITY_NONE)
                        self.stopbits = setting.get('stopbits', _STOPBITS_ONE)
            except (EnvironmentError, KeyError, json.JSONDecodeError):
                print('Could not load the setting file.')
        else:
            try:
                self.settings_data['settings'] = [self._build_entry()]
                with open(self.file, 'w', encoding='UTF-8') as outfile:
                    json.dump(self.settings_data, outfile)
            except EnvironmentError:
                print('Could not generate the setting file.')

    def _build_entry(self):
        return {
            'device_path': self.device_path,
            'rate': self.rate,
            'bits': self.bits,
            'parity': self.parity,
            'stopbits': self.stopbits,
        }

    def save_file(self):
        """
        Save settings to disk, replacing any existing entry.
        """
        self.settings_data['settings'] = [self._build_entry()]
        with open(self.file, 'w', encoding='UTF-8') as outfile:
            json.dump(self.settings_data, outfile)

    def get_settings(self):
        """
        :return: (device_path, rate, bits, parity, stopbits)
        """
        return self.device_path, self.rate, self.bits, self.parity, self.stopbits

    def set_settings(self, dev_path, rate, bits, parity=_PARITY_NONE,
                     stopbits=_STOPBITS_ONE):
        """
        Update in-memory settings and persist to disk.
        """
        self.device_path = dev_path
        self.rate = rate
        self.bits = bits
        self.parity = parity
        self.stopbits = stopbits
        self.save_file()
