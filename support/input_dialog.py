#!/usr/bin/env python3
"""
    Input Dialog
    mainly used to get an input from user.
"""
from prompt_toolkit.shortcuts import input_dialog
from prompt_toolkit.styles import Style
# from prompt_toolkit.completion import Completer, Completion, FuzzyCompleter
# from prompt_toolkit.completion import WordCompleter

example_style = Style.from_dict({
    'dialog': 'bg:#2596be',
    'dialog frame.label': 'bg:#ffffff #000000',
})


class InputDialog:
    """
        InputDialog
    """
    def __init__(self, title, text, completer=None):
        """
            __init__
                Initial method this function will run when you define any object of this type.
        :param title:
            Title message displayed on top
        :param text:
            Message for user input
        """
        #todo completer not working
        self.result = input_dialog(title, text=text, style=example_style,
                                   completer=completer).run()

    def get_result(self):
        """
            Get the message input from the user
        :return:
        """
        return self.result
