#!/usr/bin/env python3
"""
    Placeholder
"""
import sys
import time
from os.path import exists
from threading import Thread

import pyperclip
from prompt_toolkit.application import Application
from prompt_toolkit.buffer import Buffer
from prompt_toolkit.cursor_shapes import CursorShape
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout.containers import (HSplit, VSplit, Window,
                                              WindowAlign)
from prompt_toolkit.layout.controls import BufferControl, FormattedTextControl
from prompt_toolkit.layout.layout import Layout
from prompt_toolkit.lexers import PygmentsLexer
from pygments.lexers.console import PyPyLogLexer
# from pygments.lexers.teal import TealLexer
from pygments.lexers.templates import Angular2Lexer
from pygments.lexers.textedit import VimLexer

from support.exceptions import SerialDeviceOpenError  # pylint: disable=E0401
from support.message_dialog import MessageDialog  # pylint: disable=E0401
from support.progress_bar import CustomProgressBar  # pylint: disable=E0401
from support.serial_manage import SerialManager  # pylint: disable=E0401
from support.serial_simulator import \
    random_text_generator  # pylint: disable=E0401
from support.version import __version__  # pylint: disable=E0401

FIND_UNIQUE_KEY = '/*'
FIND_STOP_UNIQUE_KEY = '/@'

UPDATE_LOG_FLAG = False
CLEAR_LOG = False
OUTPUT_LOG = ""
LOG_FILE_COUNTER = 0
CAPTURE_LOG_FILE_COUNTER = 0
# highlight
HIGHLIGHT = False
HIGHLIGHT_STRING = ""
# highlight stop
HIGHLIGHT_STOP = False
HIGHLIGHT_STOP_STRING = ""
# capture
CAPTURE = False
CAPTURE_LOG = ""
CAPTURE_MSG_FLAG = False
# license
LICENSE = False
# command
SEND_COMMAND = False


def get_titlebar_text(custom_msg):
    """

    :param custom_msg:
    :return:
    """
    return [
        ("class:title bg:darkred", f" Serial App v{__version__} - "),
        ("class:title bg:darkred", custom_msg + " "),
    ]


def get_options_text():
    """

    :return:
    """
    return [
        ("class:title fg:darkred", " [Control+Q]     - Quit \n"),
        ("class:title fg:yellow", " [Control+X]     - Clear Log \n"),
        ("class:title fg:yellow", " [Control+S]     - Export to file \n"),
        ("class:title fg:yellow", " [Control+W]     - Start/Stop capture \n"),
        ("class:title fg:yellow", " [Control+C]     - Copy All in clipboard \n"),
        ("class:title fg:cyan", " [" + FIND_UNIQUE_KEY + "search_str]  - Highlight Pattern \n"),
        ("class:title fg:cyan", " [" + FIND_STOP_UNIQUE_KEY + "search_str]  - Find and Stop \n"),
        ("class:title fg:green", " [Control+L]     - Show License \n"),
        ("class:title fg:green", " [Control+H]     - Help \n"),
    ]


# Adding key bindings
kb = KeyBindings()


class GuiController:
    # pylint: disable=global-statement,global-variable-not-assigned,R0902
    """
        GuiController
    """

    def __init__(self, serial_device_path, serial_device_baudrate, simulator_mode: bool):
        """
            __Init__
        """
        global UPDATE_LOG_FLAG
        global HIGHLIGHT
        global HIGHLIGHT_STOP

        # prams
        self.simulator_mode = simulator_mode
        self.serial_dev_path = serial_device_path
        self.inserted_command: str = ""

        if not simulator_mode:
            # Serial device
            self.ser_dev = SerialManager(serial_device_path, serial_device_baudrate)
            try:
                self.ser_dev.open_dev()
            except SerialDeviceOpenError:
                MessageDialog("Failed", f"Failed to open the {serial_device_path} device.")
                sys.exit(1)

        #  Create the buffers
        self.left_buffer = Buffer()
        self.right_buffer = Buffer()
        self.status_buffer = Buffer()
        self.left_window = Window(BufferControl(buffer=self.left_buffer,
                                                lexer=PygmentsLexer(VimLexer)), width=10)
        self.status_window = Window(BufferControl(buffer=self.status_buffer,
                                                  lexer=PygmentsLexer(PyPyLogLexer)), height=1)
        self.right_window = Window(BufferControl(buffer=self.right_buffer, lexer=PygmentsLexer(Angular2Lexer),
                                                 focus_on_click=True),  wrap_lines=True, )
        self.body = \
            HSplit(
                [
                    VSplit(
                        [
                            HSplit(
                                [
                                    Window(height=1, content=FormattedTextControl([("class:line", "Input Options")]),
                                           style="class:title",
                                           align=WindowAlign.CENTER),
                                    # Horizontal separator.
                                    Window(height=1, char="-", style="class:line"),
                                    # The titlebar.
                                    Window(height=len(get_options_text()),
                                           content=FormattedTextControl(get_options_text()),
                                           align=WindowAlign.LEFT),
                                    # Horizontal separator.
                                    Window(height=1, char="-", style="class:line"),
                                    Window(height=1, content=FormattedTextControl([("class:line",
                                                                                    "Commands History")]),
                                           style="class:title",
                                           align=WindowAlign.CENTER),
                                    Window(height=1, char="-", style="class:line"),
                                    self.left_window,
                                    Window(height=1, char="-", style="class:line"),
                                    Window(height=1, content=FormattedTextControl(
                                        [("class:title bg:black fg:red", "Integrated Software Technologies Inc.")]),
                                           style="class:title",
                                           align=WindowAlign.CENTER),
                                    Window(height=1, content=FormattedTextControl(
                                        [("class:title bg:black fg:red", "http://integratedsw.tech")]),
                                           style="class:title",
                                           align=WindowAlign.CENTER),
                                ]),
                            # A vertical line in the middle. We explicitly specify the width, to make
                            # sure that the layout engine will not try to divide the whole width by
                            # three for all these windows.
                            Window(width=1, char="|", style="class:line"),
                            # Display the Result buffer on the right.
                            HSplit(
                                [
                                    Window(height=1, content=FormattedTextControl([("class:line", "Output Log")]),
                                           style="class:title",
                                           align=WindowAlign.CENTER),
                                    Window(height=1, char="-", style="class:line"),
                                    self.right_window,
                                ]),
                        ]
                    ),
                    Window(height=1, char="-", style="class:line"),
                    Window(height=1, content=FormattedTextControl([("class:line", "Status")]),
                           style="class:title",
                           align=WindowAlign.CENTER),
                    Window(height=1, char="-", style="class:line"),
                    self.status_window
                ])

        self.root_container = HSplit(
            [
                # The titlebar.
                Window(
                    height=1,
                    content=FormattedTextControl(get_titlebar_text(f"{serial_device_path} {serial_device_baudrate}")),
                    align=WindowAlign.CENTER,
                ),
                # Horizontal separator.
                Window(height=1, char="-", style="class:line"),
                # The 'body', like defined above.
                self.body,
            ]
        )
        self.connection_info = f"device {serial_device_path} opened successfully. {serial_device_baudrate}"
        self.right_buffer.on_text_changed += self.update_log_cursor
        self.right_buffer.on_text_insert += self.typing_command

        # Creating an `Application` instance
        # This glues everything together.
        self.application = Application(
            layout=Layout(self.root_container, focused_element=self.right_window),
            key_bindings=kb,
            # Let's add mouse support!
            mouse_support=True,
            # Using an alternate screen buffer means as much as: "run full screen".
            # It switches the terminal to an alternate screen.
            full_screen=True,
            cursor=CursorShape.BLINKING_BLOCK,
            enable_page_navigation_bindings=True
        )
        # Config read thread
        self.read_thread = Thread(target=self.periodic_update)
        #  Init globals
        UPDATE_LOG_FLAG = True
        HIGHLIGHT = False
        HIGHLIGHT_STOP = False

        self.read_thread.start()
        # Run the interface. (This runs the event loop until Ctrl-Q is pressed.)
        self.application.run()

    def __del__(self):
        """
            Del
        """
        if not self.simulator_mode:
            self.ser_dev.close_dev()

    def typing_command(self, event):
        """
            command_inserted
        """
        self.inserted_command += event.text[-1]

    def get_status_text(self):
        """
            get_status_text
        """
        global HIGHLIGHT
        global HIGHLIGHT_STRING
        global HIGHLIGHT_STOP
        global HIGHLIGHT_STOP_STRING

        if self.simulator_mode:
            return_var = "| Device:OPEN |"
        else:
            if self.ser_dev.is_dev_open():
                return_var = "| Device:OPEN |"
            else:
                return_var = "| Device:CLOSE |"
        if HIGHLIGHT:
            return_var += f" Search:ON:[{HIGHLIGHT_STRING}] |"
        # else:
        # return_var += f" Search_Stop:OFF |"

        if HIGHLIGHT_STOP_STRING:
            return_var += f" Search_Stop:ON:[{HIGHLIGHT_STOP_STRING}] |"
        # else:
        # return_var += f" Search_Stop:OFF |"

        if CAPTURE:
            return_var += " Capture:ON |"

        # else:
        # return_var += f" Capture:OFF |"

        return return_var

    def update_log_cursor(self, event):  # pylint: disable=R0201
        """
            update_log_curser
        """
        if event.text:
            col = len(event.text.splitlines()[-1])
            while col:
                event.cursor_right()
                col -= 1
            if event.text[-1] == "\n":
                event.cursor_down()

    def check_send_command(self, command):
        """
        When the buffer on the left changes, update the buffer on
        the right. We just reverse the text.
        """
        global HIGHLIGHT
        global HIGHLIGHT_STRING
        global HIGHLIGHT_STOP
        global HIGHLIGHT_STOP_STRING
        global UPDATE_LOG_FLAG

        if command == "\n":
            return

        # if command and command[-1] == '\n':
        if command[:len(FIND_UNIQUE_KEY)] == FIND_UNIQUE_KEY:
            UPDATE_LOG_FLAG = False
            HIGHLIGHT = True
            HIGHLIGHT_STRING = command[len(FIND_UNIQUE_KEY):-1]
            UPDATE_LOG_FLAG = True

        elif command[:len(FIND_STOP_UNIQUE_KEY)] == FIND_STOP_UNIQUE_KEY:
            UPDATE_LOG_FLAG = False
            HIGHLIGHT_STOP = True
            HIGHLIGHT_STOP_STRING = command[len(FIND_STOP_UNIQUE_KEY):-1]
            UPDATE_LOG_FLAG = True
        else:
            if not self.simulator_mode:
                self.ser_dev.exe_command(command)

        self.left_buffer.text += '- ' + command

    def periodic_update(self):
        """

        :param _:
        :return:
        """
        global CLEAR_LOG
        global OUTPUT_LOG
        global HIGHLIGHT
        global HIGHLIGHT_STRING
        global HIGHLIGHT_STOP
        global HIGHLIGHT_STOP_STRING
        global UPDATE_LOG_FLAG
        global LICENSE
        global SEND_COMMAND

        while UPDATE_LOG_FLAG:
            if not exists(self.serial_dev_path) and not self.simulator_mode:
                UPDATE_LOG_FLAG = False
                msg = f"ERROR: {self.serial_dev_path} is not connected."
                self.right_buffer.text += "-" * len(msg)
                self.right_buffer.text += "\n"
                self.right_buffer.text += msg
                self.right_buffer.text += "\n"
                self.right_buffer.text += "-" * len(msg)
                sys.exit(1)

            self.status_buffer.reset()
            self.status_buffer.text = self.get_status_text()

            if LICENSE:
                # open text file in read mode
                with open("LICENSE", "r", encoding='UTF-8') as file:
                    # read whole license to a string
                    UPDATE_LOG_FLAG = False
                    data = file.read()
                    # close file
                    file.close()
                    self.right_buffer.text += str(data)
                    self.right_buffer.text += "\n\nPlease close the program and re-open.\n\n"

            if SEND_COMMAND:
                # self.right_buffer.text += "\n"
                self.check_send_command(self.inserted_command + "\n")
                self.inserted_command = ""
                SEND_COMMAND = False

            if CLEAR_LOG:
                self.right_buffer.reset()
                CLEAR_LOG = False

            if self.simulator_mode:
                incoming_packet = random_text_generator()
                time.sleep(0.2)
            else:
                incoming_packet = self.ser_dev.read()
                if incoming_packet is None:
                    incoming_packet = ""
            self.check_incoming_packet(incoming_packet)

            self.right_buffer.text += incoming_packet
            OUTPUT_LOG = self.right_buffer.text
            time.sleep(0.0002)

    def check_incoming_packet(self, incoming_packet):
        """
        Check the log for any matching conditions
        """
        global HIGHLIGHT
        global HIGHLIGHT_STRING
        global HIGHLIGHT_STOP
        global HIGHLIGHT_STOP_STRING
        global UPDATE_LOG_FLAG
        global CAPTURE
        global CAPTURE_LOG
        global CAPTURE_MSG_FLAG
        global CAPTURE_LOG_FILE_COUNTER

        if HIGHLIGHT and HIGHLIGHT_STRING:
            found = incoming_packet.find(HIGHLIGHT_STRING)
            if found > 0:
                raw_log = '\n\n\n-->FOUND\n' + incoming_packet[0:found] + '\0\0' + \
                          incoming_packet[found:found + len(HIGHLIGHT_STRING)] + '\0\0' + \
                          incoming_packet[found + len(HIGHLIGHT_STRING):-1] + '\n\n\n'
                self.right_buffer.text += raw_log

        if HIGHLIGHT_STOP and HIGHLIGHT_STOP_STRING:
            found = incoming_packet.find(HIGHLIGHT_STOP_STRING)
            if found > 0:
                raw_log = '\n\n\n-->FOUND\n' + incoming_packet[0:found] + '\0\0' + \
                          incoming_packet[found:found + len(HIGHLIGHT_STOP_STRING)] + '\0\0' + \
                          incoming_packet[found + len(HIGHLIGHT_STOP_STRING):-1] + '\n\n\n'
                self.right_buffer.text += raw_log
                UPDATE_LOG_FLAG = False

        if CAPTURE:
            CAPTURE_LOG += incoming_packet
            if not CAPTURE_MSG_FLAG:
                self.right_buffer.text += "\n\n------------------------Capture-Started------------------------\n"
                CAPTURE_MSG_FLAG = True

        if not CAPTURE and CAPTURE_MSG_FLAG:
            with open(f'Capture_log{CAPTURE_LOG_FILE_COUNTER}.txt', 'w', encoding='UTF-8') as file:
                CAPTURE_LOG_FILE_COUNTER += 1
                file.write(CAPTURE_LOG)
                self.right_buffer.text += "\n\n------------------------Capture-Stopped------------------------\n"
            CAPTURE_LOG = ""
            CAPTURE_MSG_FLAG = False


@kb.add("c-q", eager=True)
def _(event):
    """
    Pressing Ctrl-Q will exit the user interface.
    """
    global UPDATE_LOG_FLAG  # pylint: disable=global-statement
    UPDATE_LOG_FLAG = False
    CustomProgressBar("Existing", 100)
    event.app.exit()


@kb.add("c-x", eager=True)
def _(_):
    """
    Pressing Ctrl-X Clear the log
    """
    global CLEAR_LOG  # pylint: disable=global-statement
    CLEAR_LOG = True


@kb.add("c-s", eager=True)
def _(_):
    """
    Pressing Ctrl-S Save the log in file
    """
    global OUTPUT_LOG  # pylint: disable=global-statement,W0602
    global LOG_FILE_COUNTER  # pylint: disable=global-statement
    with open(f'OUTPUT_LOG{LOG_FILE_COUNTER}.txt', 'w', encoding='UTF-8') as file:
        LOG_FILE_COUNTER += 1
        file.write(OUTPUT_LOG)


@kb.add("c-c", eager=True)
def _(_):
    """
    Pressing Ctrl-C Copy log to clipboard
    """
    global OUTPUT_LOG  # pylint: disable=global-statement,W0602
    pyperclip.copy(OUTPUT_LOG)


@kb.add("c-w", eager=True)
def _(_):
    """
    Pressing Ctrl-W
    """
    global CAPTURE  # pylint: disable=global-statement,W0602
    CAPTURE = not CAPTURE


@kb.add("c-l", eager=True)
def _(_):
    """
    Pressing Ctrl-L
    """
    global LICENSE  # pylint: disable=global-statement,W0602
    LICENSE = True


@kb.add("enter", eager=True)
def _(_):
    """
    Pressing Enter
    """
    global SEND_COMMAND  # pylint: disable=global-statement,W0602
    SEND_COMMAND = True
