#!/usr/bin/env python3
"""
    Save Settings
"""
import json
import os


class SaveSettings:
    """
        SaveSettings
    """

    def __init__(self, file):
        """
            __init__
        :param file:
        """
        # ....
        # Create or Load Settings
        self.device_path = None
        self.rate = None
        self.bits = None
        self.file = file
        self.settings_data = {'settings': []}
        if os.path.isfile(self.file):
            try:
                # print('Found the setting file.')
                with open(self.file, encoding='UTF-8') as json_file:
                    self.settings_data = json.load(json_file)
                    for setting in self.settings_data['settings']:
                        self.device_path = setting['device_path']
                        self.rate = setting['rate']
                        self.bits = setting['bits']
            except EnvironmentError:
                print('Could not load the setting file.')
        else:
            try:
                self.settings_data['settings'].append({'device_path': self.device_path,
                                                       'rate': self.rate, 'bits': self.bits})
                with open(self.file, 'w', encoding='UTF-8') as outfile:
                    json.dump(self.settings_data, outfile)
                # print('Setting file generated.')
            except EnvironmentError:
                print('Could not generate the setting file.')

    def save_file(self):
        """

        :return:
        """
        self.settings_data['settings'].append({'device_path': self.device_path,
                                               'rate': self.rate, 'bits': self.bits})
        with open(self.file, 'w', encoding='UTF-8') as outfile:
            json.dump(self.settings_data, outfile)
        # print('Setting file generated.')

    def get_settings(self):
        """

        :param self:
        :return:
        """
        return self.device_path, self.rate, self.bits

    def set_settings(self, dev_path, rate, bits):
        """

        :param bits:
        :param rate:
        :param dev_path:
        :param self:
        :return:
        """
        self.device_path = dev_path
        self.rate = rate
        self.bits = bits
        self.save_file()
