#!/usr/bin/env python3
"""
    Progress Bar
"""
import time
from prompt_toolkit.shortcuts import ProgressBar
from prompt_toolkit.styles import Style
from prompt_toolkit.shortcuts.progress_bar import formatters

style = Style.from_dict({
    'label': 'bg:#ffff00 #000000',
    'percentage': 'bg:#ffff00 #000000',
    'current': '#448844',
    'bar': '',
})

custom_formatters = [
    formatters.Label(),
    formatters.Text(': [', style='class:percentage'),
    formatters.Percentage(),
    formatters.Text(']', style='class:percentage'),
    formatters.Text(' '),
    formatters.Bar(sym_a='#', sym_b='#', sym_c='.'),
    formatters.Text('  '),
]


class CustomProgressBar:
    """
        CustomProgressBar
    """
    def __init__(self, msg, itr):
        """
            __init__
        """
        with ProgressBar(style=style, formatters=custom_formatters) as progress_bar:
            for _ in progress_bar(range(itr), label=msg):
                time.sleep(.01)
