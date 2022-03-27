#!/usr/bin/env python3
"""
    GUI Controller mainly used to manage the CLI GUI components and handling the serial device I/O interface.
"""
import sys
import time
from os.path import exists
from threading import Thread

import pyperclip
from prompt_toolkit.application import Application, get_app
from prompt_toolkit.buffer import Buffer
from prompt_toolkit.cursor_shapes import CursorShape
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout.containers import (HSplit, VSplit, Window,
                                              WindowAlign)
from prompt_toolkit.layout.controls import BufferControl, FormattedTextControl
from prompt_toolkit.layout.layout import Layout
from prompt_toolkit.lexers import PygmentsLexer
from pygments.lexers.console import PyPyLogLexer
from pygments.lexers.templates import Angular2Lexer
from pygments.lexers.textedit import VimLexer

from support.exceptions import SerialDeviceOpenError  # pylint: disable=E0401
from support.message_dialog import MessageDialog  # pylint: disable=E0401
from support.progress_bar import CustomProgressBar  # pylint: disable=E0401
from support.serial_manage import SerialManager  # pylint: disable=E0401
from support.serial_simulator import \
    random_text_generator  # pylint: disable=E0401
from support.version import __version__  # pylint: disable=E0401

# Global parameters mainly used for state-machine cases where the software needs to interrupt the working thread.

# UPDATE_LOG_FLAG used to determine whether the software is fetching the incoming packets
UPDATE_LOG_FLAG = False
# CLEAR_LOG is used to determine the software that a clear flag was set to clear the output log buffer.
CLEAR_LOG = False
# OUTPUT_LOG is used for exporting the output log message to a file globally.
OUTPUT_LOG = ""
# LOG_FILE_COUNTER is mainly used for counting the number of times the software exported a file also it used
# as a prefix for the exported file name.
LOG_FILE_COUNTER = 0
# HIGHLIGHT is mainly used when user is searching for a string.
HIGHLIGHT = False
# HIGHLIGHT_STOP similar to the HIGHLIGHT this variable used for the search and stop feature.
HIGHLIGHT_STOP = False
# HIGHLIGHT_STRING is used for the input search string that was entered by the user.
HIGHLIGHT_STRING = ""
# CAPTURE is used to capture a certain part of the log and the time for logging is started and stopped by the user
CAPTURE = False
# CAPTURE_LOG is the log string that holds the log buffer. it will be exported to a file.
CAPTURE_LOG = ""
# CAPTURE_MSG_FLAG is used for print and messaging purposes
CAPTURE_MSG_FLAG = False
# CAPTURE_LOG_FILE_COUNTER similar to the LOG_FILE_COUNTER but used for the capture feature.
CAPTURE_LOG_FILE_COUNTER = 0
# LICENSE is a flag that determines the user requesting the license
LICENSE = False
# SEND_COMMAND is used for signaling the software that user entered a command to serial device.
SEND_COMMAND = False
# DEBUG_MODE is used for debuting purposes
DEBUG_MODE = False
DEBUG_MODE_TEXT = False
# TAB_PRESSED is used to switch the fours from output log to the search editbox
TAB_PRESSED = False


def get_titlebar_text(custom_msg):
    """
        This global function is used to get the header message for the CLI-GUI
    :param custom_msg: if mainly used to pass the device name is baud-rate.
    :return: the formatted string
    """
    return [
        ("class:title bg:darkred", f" Serial App v{__version__} - "),
        ("class:title bg:darkred", custom_msg + " "),
    ]


def get_options_text():
    """
        This global function is used to get the list of options string for the CLI-GUI
    :return: the formatted string
    """
    return [
        ("class:title fg:darkred", " [Control+Q] - Quit \n"),
        ("class:title fg:yellow", " [Control+X] - Clear Log \n"),
        ("class:title fg:yellow", " [Control+S] - Export to file \n"),
        ("class:title fg:yellow", " [Control+W] - Start/Stop capture \n"),
        ("class:title fg:yellow", " [Control+C] - Copy All in clipboard \n"),
        ("class:title fg:cyan", " [Control+F] - Highlight Pattern \n"),
        ("class:title fg:cyan", " [Control+G] - Find and Stop \n"),
        ("class:title fg:green", " [Control+L] - Show License \n"),
        ("class:title fg:green", " [Control+H] - Help \n"),
        ("class:title fg:blue", " [Shift+Tab] - Debug \n"),
    ]


# Adding key bindings
kb = KeyBindings()


class GuiController:
    # pylint: disable=global-statement,global-variable-not-assigned,R0902
    """
        GuiController is the class responsible for managing the CLI-GUI components and the serial device interface.
    """

    def __init__(self, serial_device_path, serial_device_baudrate, simulator_mode: bool):
        """
            initial method responsible for starting and configuring the default values and
            the necessary configurations
        """
        global UPDATE_LOG_FLAG
        global HIGHLIGHT
        global HIGHLIGHT_STOP

        # simulator mode holds the simulator mode state
        self.simulator_mode = simulator_mode
        # hold the device path
        self.serial_dev_path = serial_device_path
        # some variables must be set to default
        self.inserted_command: str = ""
        self.search_input: str = ""

        # if not simulator mode try to open the serial device if failed raise a flag
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
        self.search_buffer = Buffer()
        # Create the windows for the buffers
        self.left_window = Window(BufferControl(buffer=self.left_buffer,
                                                lexer=PygmentsLexer(VimLexer)), width=10)
        self.status_window = Window(BufferControl(buffer=self.status_buffer,
                                                  lexer=PygmentsLexer(PyPyLogLexer)), height=1)
        self.right_window = Window(BufferControl(buffer=self.right_buffer, lexer=PygmentsLexer(Angular2Lexer),
                                                 focus_on_click=True), wrap_lines=True, style='class:border')
        self.search_window = Window(BufferControl(buffer=self.search_buffer,
                                                  lexer=PygmentsLexer(PyPyLogLexer)), height=1, style='class:border')
        # Define the layout for the GUI
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
                                                                                    "[Tab] Search feild")]),
                                           style="class:title",
                                           align=WindowAlign.CENTER),
                                    Window(height=1, char="-", style="class:line"),
                                    VSplit([
                                        Window(width=2, char="||", style="class:line"),
                                        self.search_window,
                                        Window(width=2, char="||", style="class:line"), ]),
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
        # set the needed events
        self.right_buffer.on_text_changed += self.update_log_cursor
        self.right_buffer.on_text_insert += self.typing_command
        self.search_buffer.on_text_insert += self.typing_search

        # Creating an `Application` instance
        # This glues everything together.
        self.application = Application(
            layout=Layout(self.root_container, focused_element=self.right_window),
            key_bindings=kb,
            # Let's add mouse support!
            mouse_support=False,
            # Using an alternate screen buffer means as much as: "run full screen".
            # It switches the terminal to an alternate screen.
            full_screen=True,
            cursor=CursorShape.BLINKING_UNDERLINE,
            enable_page_navigation_bindings=True
        )
        # Config read thread
        self.read_thread = Thread(target=self.periodic_update)
        #  Init globals
        UPDATE_LOG_FLAG = True

        # start the read thread
        self.read_thread.start()
        # Run the interface. (This runs the event loop until Ctrl-Q is pressed.)
        self.application.run()

    def __del__(self):
        """
            Del for destroying the object
        """
        if not self.simulator_mode:
            self.ser_dev.close_dev()

    def get_status_text(self):
        """
            get_status_text is used to define the status bar string.
        """
        global HIGHLIGHT
        global HIGHLIGHT_STRING
        global HIGHLIGHT_STOP
        global DEBUG_MODE_TEXT

        if self.simulator_mode:
            return_var = "| Device:OPEN |"
        else:
            if self.ser_dev.is_dev_open():
                return_var = "| Device:OPEN |"
            else:
                return_var = "| Device:CLOSE |"

        if HIGHLIGHT:
            return_var += f" Search:ON:[{HIGHLIGHT_STRING}] |"

        if HIGHLIGHT_STOP:
            return_var += f" Search_Stop:ON:[{HIGHLIGHT_STRING}] |"

        if CAPTURE:
            return_var += " Capture:ON |"

        if DEBUG_MODE:
            return_var += F" DEBUG_MODE:ON:[{DEBUG_MODE_TEXT}|"

        return return_var

    def typing_search(self, _):
        """
            typing_search this event is called when the user is typing in the search field
        """
        global HIGHLIGHT_STRING
        self.search_input = HIGHLIGHT_STRING = self.search_buffer.text

    def typing_command(self, event):
        """
            typing_command this event is called when the user is typing in the output log field
        """
        global DEBUG_MODE
        global DEBUG_MODE_TEXT
        # event holds the buffer and we want only thr last character
        # todo backspace support?
        self.inserted_command += event.text[-1]
        if DEBUG_MODE:
            DEBUG_MODE_TEXT += event.text[-1]

    def update_log_cursor(self, _):  # pylint: disable=R0201
        """
            update_log_curser this event is used to update the cursor when a change occur to the output log field
        """
        self.update_cursor()

    def update_cursor(self):
        """
        update_cursor this method used to check and update the cursor.
        """
        self.right_buffer.auto_down()
        char_count = len(self.right_buffer.text.splitlines()[-1])
        self.right_buffer.cursor_right(char_count)

    def send_command(self, command):
        """
        send_command is used to send the input command from output log field and perform serial write operation
        """
        global HIGHLIGHT
        global HIGHLIGHT_STRING
        global HIGHLIGHT_STOP
        global UPDATE_LOG_FLAG

        if command == "\n":
            return

        if not self.simulator_mode:
            self.ser_dev.exe_command(command)

        # save the command to the history list
        # todo maybe we need a key to browse through the history of commands
        self.left_buffer.text += '- ' + command

    def periodic_update(self):
        """
            periodic_update this method responsible for looping through the operation and what needed in next
            iteration. it's the state-machine method.
        """
        global CLEAR_LOG
        global OUTPUT_LOG
        global HIGHLIGHT
        global HIGHLIGHT_STRING
        global HIGHLIGHT_STOP
        global UPDATE_LOG_FLAG
        global LICENSE
        global SEND_COMMAND
        global TAB_PRESSED

        while UPDATE_LOG_FLAG:
            # first iteration? check if the device is still connected.
            if not exists(self.serial_dev_path) and not self.simulator_mode:
                UPDATE_LOG_FLAG = False
                msg = f"ERROR: {self.serial_dev_path} is not connected."
                self.right_buffer.text += '\n'
                self.right_buffer.text += "-" * len(msg)
                self.right_buffer.text += "\n"
                self.right_buffer.text += msg
                self.right_buffer.text += "\n"
                self.right_buffer.text += "-" * len(msg)
                # todo raise an exception
                sys.exit(1)

            # update the status
            self.status_buffer.reset()
            self.status_buffer.text = self.get_status_text()

            # if the user requested the license
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

            # if the user pressed on TAB (auto-complete?)
            if TAB_PRESSED:
                self.send_command(self.inserted_command + "\t")
                TAB_PRESSED = False

            # Command is ready to the serial device. Command will be executed.
            # todo remove the signal command with sending each char entered?
            if SEND_COMMAND:
                # self.right_buffer.text += "\n"
                self.send_command(self.inserted_command + "\n")
                self.inserted_command = ""
                SEND_COMMAND = False

            # If user want to clear the log
            if CLEAR_LOG:
                self.right_buffer.reset()
                CLEAR_LOG = False

            # if simulator mode then get the next packet from simulator object.
            if self.simulator_mode:
                incoming_packet = random_text_generator()
                time.sleep(0.2)
            else:
                # perform serial read
                incoming_packet = self.ser_dev.read()
                # if nothing came from the serial object we force the packet to be str and empty
                if incoming_packet is None:
                    incoming_packet = ""
            # check the incoming packet for a search and search stop feature.
            self.check_incoming_packet(incoming_packet)
            # append the incoming packet to the output log
            self.right_buffer.text += incoming_packet.replace('\r', '').replace('^M', '').replace('\b', '')\
                .replace('\t', '')
            # update the output_log for exporting if needed.
            OUTPUT_LOG = self.right_buffer.text

    def check_incoming_packet(self, incoming_packet):
        """
        Check the log for any matching conditions
        """
        global HIGHLIGHT
        global HIGHLIGHT_STRING
        global HIGHLIGHT_STOP
        global UPDATE_LOG_FLAG
        global CAPTURE
        global CAPTURE_LOG
        global CAPTURE_MSG_FLAG
        global CAPTURE_LOG_FILE_COUNTER

        # if search and search string is set then check if input string pattern found.
        if HIGHLIGHT and HIGHLIGHT_STRING:
            found = incoming_packet.find(HIGHLIGHT_STRING)
            if found > 0:
                # '\x1b[6;30;42m' + + '\x1b[0m'
                raw_log = '\n\n\n-->FOUND\n' + incoming_packet[0:found] + '\x1b[6;30;42m' + '\0\0' + \
                          incoming_packet[found:found + len(HIGHLIGHT_STRING)] + '\0\0' + '\x1b[0m' + \
                          incoming_packet[found + len(HIGHLIGHT_STRING):-1] + '\n\n\n'
                self.right_buffer.text += raw_log

        # if search stop and search string is set then check if input string pattern found.
        if HIGHLIGHT_STOP and HIGHLIGHT_STRING:
            found = incoming_packet.find(HIGHLIGHT_STRING)
            if found > 0:
                raw_log = '\n\n\n-->FOUND\n' + incoming_packet[0:found] + '\x1b[6;30;42m' + '\0\0' + \
                          incoming_packet[found:found + len(HIGHLIGHT_STRING)] + '\0\0' + '\x1b[0m' + \
                          incoming_packet[found + len(HIGHLIGHT_STRING):-1] + '\n\n\n'
                self.right_buffer.text += raw_log
                UPDATE_LOG_FLAG = False

        # If capture is enabled then let's start log/save any upcoming packets.
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
    Pressing Ctrl-W Start/Stop the capture feature
    """
    global CAPTURE  # pylint: disable=global-statement,W0602
    CAPTURE = not CAPTURE


@kb.add("c-l", eager=True)
def _(_):
    """
    Pressing Ctrl-L Show license
    """
    global LICENSE  # pylint: disable=global-statement,W0602
    LICENSE = True


@kb.add("c-m", eager=True)
def _(_):
    """
    Pressing [Enter] Command entered
    """
    global SEND_COMMAND  # pylint: disable=global-statement,W0602
    SEND_COMMAND = True


@kb.add("s-tab", eager=True)
def _(_):
    """
    Pressing Shift-Tab Enter Debug Mode
    """
    global DEBUG_MODE  # pylint: disable=global-statement,W0602
    global DEBUG_MODE_TEXT  # pylint: disable=global-statement,W0602
    DEBUG_MODE = not DEBUG_MODE
    DEBUG_MODE_TEXT = ''


@kb.add("c-g", eager=True)
def _(_):
    """
    Pressing Ctrl-G for search and stop
    """
    global HIGHLIGHT_STOP  # pylint: disable=global-statement,W0602
    HIGHLIGHT_STOP = not HIGHLIGHT_STOP
    get_app().layout.focus_next()
    get_app().layout.focus_next()


@kb.add("c-f", eager=True)
def _(_):
    """
    Pressing Ctrl-F for search
    """
    global HIGHLIGHT  # pylint: disable=global-statement,W0602
    HIGHLIGHT = not HIGHLIGHT
    get_app().layout.focus_next()
    get_app().layout.focus_next()


@kb.add("c-i", eager=True)
def _(_):
    """
    Pressing [Tab] to switch to search input field
    """
    global TAB_PRESSED  # pylint: disable=global-statement,W0602
    TAB_PRESSED = True
