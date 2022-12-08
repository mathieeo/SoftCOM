#!/usr/bin/env python3
"""
    Radio List Dialog
    mainly used to get a selected input from user.
"""
from prompt_toolkit.shortcuts import radiolist_dialog
from prompt_toolkit.styles import Style

example_style = Style.from_dict({
    'dialog': 'bg:#2596be',
    'dialog frame.label': 'bg:#ffffff #000000',
})


class RadioListDialog:
    """
        RadioListDialog
    """
    def __init__(self, title, text, values):
        """
            __init__
                Initial method this function will run when you define any object of this type.
        :param title:
            Title message displayed on top
        :param text:
            Message for user input
        """
        self.result = radiolist_dialog(title, text=text, values=values, style=example_style).run()

    def get_result(self):
        """
            Get the message input from the user
        :return:
        """
        return self.result
