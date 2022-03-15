#!/usr/bin/env python3
"""
    Placeholder
"""
import sys
import time
from threading import Thread
import pyperclip
from pygments.lexers.textedit import VimLexer
from pygments.lexers.console import PyPyLogLexer
from prompt_toolkit.application import Application
from prompt_toolkit.buffer import Buffer
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout.containers import HSplit, VSplit, Window, WindowAlign
from prompt_toolkit.layout.controls import BufferControl, FormattedTextControl
from prompt_toolkit.layout.layout import Layout
from prompt_toolkit.lexers import PygmentsLexer
from support.serial_simulator import random_text_generator  # pylint: disable=E0401
from support.progress_bar import CustomProgressBar  # pylint: disable=E0401
from support.version import __version__  # pylint: disable=E0401

FIND_UNIQUE_KEY = '^/'
FIND_STOP_UNIQUE_KEY = '&/'

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
        ("class:title fg:cyan", " [^/search_str]  - Highlight Pattern \n"),
        ("class:title fg:cyan", " [&/search_str]  - Find and Stop \n"),
        ("class:title fg:green", " [Control+H]     - Help \n"),
    ]


# Adding key bindings
kb = KeyBindings()


class GuiController:
    # pylint: disable=global-statement,global-variable-not-assigned,R0902
    """
        GuiController
    """

    def __init__(self, connection_info=""):
        """
            __Init__
        """
        global UPDATE_LOG_FLAG
        global HIGHLIGHT
        global HIGHLIGHT_STOP
        #  Create the buffers
        self.left_buffer = Buffer()
        self.left_buffer2 = Buffer()
        self.right_buffer = Buffer()
        # First we create the layout
        self.left_window = Window(BufferControl(buffer=self.left_buffer,
                                                lexer=PygmentsLexer(VimLexer), ), width=3)
        self.left_window2 = Window(BufferControl(buffer=self.left_buffer2,
                                                 lexer=PygmentsLexer(VimLexer), ))
        self.right_window = Window(BufferControl(buffer=self.right_buffer, lexer=PygmentsLexer(PyPyLogLexer)),
                                   wrap_lines=True)
        self.body = VSplit(
            [
                HSplit(
                    [
                        Window(height=1, content=FormattedTextControl([("class:line", "Input Options")]),
                               style="class:title",
                               align=WindowAlign.CENTER),
                        # Horizontal separator.
                        Window(height=1, char="-", style="class:line"),
                        # The titlebar.
                        Window(height=len(get_options_text()), content=FormattedTextControl(get_options_text()),
                               align=WindowAlign.LEFT),
                        # Horizontal separator.
                        Window(height=1, char="-", style="class:line"),

                        Window(height=1, content=FormattedTextControl([("class:line", "Type Command >>")]),
                               style="class:title"),
                        # Horizontal separator.
                        Window(height=1, char="-", style="class:line"),
                        self.left_window,
                        Window(height=1, char="-", style="class:line"),
                        Window(height=1, content=FormattedTextControl([("class:line", "Commands History")]),
                               style="class:title",
                               align=WindowAlign.CENTER),
                        Window(height=1, char="-", style="class:line"),
                        self.left_window2,
                        Window(height=1, char="-", style="class:line"),
                        Window(height=1, content=FormattedTextControl(
                            [("class:title bg:black fg:red", "Integrated Software Technologies Inc.")]),
                               style="class:title",
                               align=WindowAlign.CENTER),
                        Window(height=1, content=FormattedTextControl(
                            [("class:title bg:black fg:red", "http://integratedsw.tech")]),
                               style="class:title",
                               align=WindowAlign.CENTER),
                        Window(height=1, char="-", style="class:line"),
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
        )
        self.root_container = HSplit(
            [
                # The titlebar.
                Window(
                    height=1,
                    content=FormattedTextControl(get_titlebar_text(connection_info)),
                    align=WindowAlign.CENTER,
                ),
                # Horizontal separator.
                Window(height=1, char="-", style="class:line"),
                # The 'body', like defined above.
                self.body,
            ]
        )
        self.connection_info = connection_info
        # self.left_buffer.insert_text(connection_info)
        self.left_buffer.on_text_changed += self.default_buffer_changed
        self.right_buffer.on_text_changed += self.update_log_cursor

        # Creating an `Application` instance
        # This glues everything together.
        self.application = Application(
            layout=Layout(self.root_container, focused_element=self.left_window),
            key_bindings=kb,
            # Let's add mouse support!
            mouse_support=True,
            # Using an alternate screen buffer means as much as: "run full screen".
            # It switches the terminal to an alternate screen.
            full_screen=True,
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

    def update_log_cursor(self, _):
        """
            update_log_curser
        """
        self.right_buffer.cursor_down(len(self.right_buffer.text))

    def default_buffer_changed(self, _):
        """
        When the buffer on the left changes, update the buffer on
        the right. We just reverse the text.
        """
        global HIGHLIGHT
        global HIGHLIGHT_STRING
        global HIGHLIGHT_STOP
        global HIGHLIGHT_STOP_STRING
        global UPDATE_LOG_FLAG
        if self.left_buffer.text and self.left_buffer.text[-1] == '\n':
            if self.left_buffer.text[:2] == FIND_UNIQUE_KEY:
                UPDATE_LOG_FLAG = False
                HIGHLIGHT = True
                HIGHLIGHT_STRING = self.left_buffer.text[2:-1]
                UPDATE_LOG_FLAG = True

            elif self.left_buffer.text[:2] == FIND_STOP_UNIQUE_KEY:
                UPDATE_LOG_FLAG = False
                HIGHLIGHT_STOP = True
                HIGHLIGHT_STOP_STRING = self.left_buffer.text[2:-1]
                UPDATE_LOG_FLAG = True
            else:
                self.right_buffer.text += self.left_buffer.text
            self.left_buffer2.text += '- ' + self.left_buffer.text
            self.left_buffer.reset()

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

        counter = 0

        while UPDATE_LOG_FLAG:
            if CLEAR_LOG:
                self.right_buffer.reset()
                CLEAR_LOG = False

            incoming_packet = random_text_generator()
            self.check_incoming_packet(incoming_packet)

            self.right_buffer.text += incoming_packet
            OUTPUT_LOG = self.right_buffer.text
            time.sleep(0.15)
            counter += 1
            if counter > 10000:
                sys.exit()

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
                incoming_packet = '\n\n\n-->FOUND\n' + incoming_packet[0:found] + '\0\0' + \
                                  incoming_packet[found:found + len(HIGHLIGHT_STRING)] + '\0\0' + \
                                  incoming_packet[found + len(HIGHLIGHT_STRING):-1] + '\n\n\n'

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
