#!/usr/bin/env python3
"""
    Serial Simulator
    mainly used for testing without hardware.
"""
import os
import random

_dir = os.path.dirname(os.path.realpath(__file__))
_log_path = os.path.join(_dir, 'test_log.txt')

with open(_log_path, encoding='UTF-8') as _f:
    lines = _f.read().splitlines()


def get_random_string():
    """

    :return:
    """
    line = random.choice(lines)
    return str(line)


def random_text_generator():
    """

    :return:
    """
    return get_random_string() + "\n"
