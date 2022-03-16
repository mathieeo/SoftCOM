#!/usr/bin/env python3
"""
    Serial Simulator
    mainly used for testing without hardware.
"""
import random

lines = open('test_log.txt', encoding='UTF-8').read().splitlines()  # pylint: disable=R1732


def get_random_string():
    """

    :return:
    """
    line = random.choice(lines)
    return str(line)
    # # choose from all lowercase letter
    # letters = string.ascii_letters + string.digits + string.punctuation
    # result_str = ''.join(random.choice(letters) + (" " if i % 2 == 2 else "") for i in range(length))
    # return result_str


def random_text_generator():
    """

    :return:
    """
    return get_random_string() + "\n"
