#!/usr/bin/env python3
"""
    Serial Simulator
    mainly used for testing without hardware.
"""
import random

lines = open('/Users/mathyossarkiss/Personal/SoftCOM/SoftCOM/support/test_log.txt',
             encoding='UTF-8').read().splitlines()  # pylint: disable=R1732


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
