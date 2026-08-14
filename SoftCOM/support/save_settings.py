#!/usr/bin/env python3
"""
    Save Settings
"""
import json
import os
import tempfile

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
        # What to append to a line when you press Enter: 'NONE' | 'LF' | 'CR' | 'CRLF'. Many serial
        # devices only act on CR (or CR+LF), so a fixed '\n' meant commands silently never ran.
        self.line_ending = 'LF'
        # Echo sent commands into the log (for a device that doesn't echo them back). Off by default.
        self.local_echo = False
        self.file = file
        self.settings_data = {'settings': []}
        if os.path.isfile(self.file):
            loaded = None
            try:
                with open(self.file, encoding='UTF-8') as json_file:
                    loaded = json.load(json_file)
            except (OSError, ValueError) as err:   # ValueError covers json.JSONDecodeError (a subclass)
                print(f'Could not load the setting file: {err}')
            # Read DEFENSIVELY. A hand-edited or half-written settings.json can have the top level not be
            # an object, 'settings' be a non-list, or its items be non-dicts — the old code iterated and
            # `.get()`-ed those blindly, raising TypeError/AttributeError (NOT caught above) and crashing the
            # app at startup. Validate every level; ignore anything malformed and fall back to defaults, which
            # the next save_file() rewrites into a clean file.
            if isinstance(loaded, dict):
                self.settings_data = loaded
                entries = loaded.get('settings')
                if isinstance(entries, list):
                    for setting in entries:
                        if not isinstance(setting, dict):
                            continue
                        self.device_path = setting.get('device_path')
                        self.rate = setting.get('rate')
                        self.bits = setting.get('bits')
                        self.parity = setting.get('parity', _PARITY_NONE)
                        self.stopbits = setting.get('stopbits', _STOPBITS_ONE)
                        self.line_ending = setting.get('line_ending', 'LF')
                        self.local_echo = setting.get('local_echo', False)
        else:
            self.settings_data['settings'] = [self._build_entry()]
            self._atomic_write(self.settings_data)

    def _build_entry(self):
        return {
            'device_path': self.device_path,
            'rate': self.rate,
            'bits': self.bits,
            'parity': self.parity,
            'stopbits': self.stopbits,
            'line_ending': self.line_ending,
            'local_echo': self.local_echo,
        }

    def save_file(self):
        """
        Save settings to disk, replacing any existing entry.

        Never let a save failure crash the app. This runs from the first-run config (set_settings), from the
        runtime toggles (Ctrl+N line-ending / Ctrl+O local-echo), and once more on clean exit — and a read-only
        settings.json, a full disk, or a non-writable app directory would otherwise raise an UNCAUGHT OSError
        from any of those (an ugly traceback on exit, or a crash mid-config). Degrade to a warning and keep the
        in-memory settings, exactly like the file-CREATE path in __init__ already does.
        """
        self.settings_data['settings'] = [self._build_entry()]
        self._atomic_write(self.settings_data)

    def _atomic_write(self, data):
        """Write the settings file so it is never observed half-written.

        `open(path, 'w')` TRUNCATES the target first, so a crash, a power cut, or a full disk
        between the truncate and the flush leaves a 0-byte or partial settings.json — and the
        next launch finds invalid JSON and silently falls back to defaults, i.e. the user's
        configured port, baud and framing are gone. save_file() runs on every Ctrl+N/Ctrl+O
        toggle and again on exit, so that window is hit often enough to matter.

        Write to a temp file in the SAME directory (so it lands on the same filesystem and
        os.replace is a true atomic rename) and swap it in. A reader then sees either the whole
        old file or the whole new one, never a torn one.
        """
        target_dir = os.path.dirname(os.path.abspath(self.file)) or '.'
        tmp_name = None
        try:
            with tempfile.NamedTemporaryFile(
                    'w', encoding='UTF-8', dir=target_dir,
                    prefix='.settings-', suffix='.tmp', delete=False) as tmp:
                tmp_name = tmp.name
                json.dump(data, tmp)
                tmp.flush()
                os.fsync(tmp.fileno())      # the rename is only atomic if the bytes are down
            os.replace(tmp_name, self.file)
            tmp_name = None
        except (OSError, TypeError, ValueError) as err:
            print(f'Could not save the setting file: {err}')
        finally:
            if tmp_name and os.path.exists(tmp_name):
                try:
                    os.unlink(tmp_name)      # never leave .settings-*.tmp litter behind
                except OSError:
                    pass

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
