#!/usr/bin/env python3
"""
    Message Dialog
    mainly used to show message from user.
"""
from prompt_toolkit.shortcuts import message_dialog
from prompt_toolkit.styles import Style
# from prompt_toolkit.completion import Completer, Completion, FuzzyCompleter
# from prompt_toolkit.completion import WordCompleter

example_style = Style.from_dict({
    'dialog': 'bg:#2596be',
    'dialog frame.label': 'bg:#ffffff #000000',
})


class MessageDialog:
    """
        MessageDialog
    """
    def __init__(self, title, text):
        """
            __init__
                Initial method this function will run when you define any object of this type.
        :param title:
            Title message displayed on top
        :param text:
            Message for user input
        """
        self.result = message_dialog(title, text=text, style=example_style).run()
