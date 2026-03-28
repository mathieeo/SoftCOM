#!/usr/bin/env python3
"""
    GUI Controller — manages the CLI GUI components and the serial device I/O interface.
"""
import os
import sys
import time
from os.path import exists
from threading import Thread

# History file stored in the user's home directory
_HISTORY_FILE = os.path.join(os.path.expanduser("~"), ".softcom_history")
_MAX_HISTORY = 500  # max lines kept in the history file

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
from pygments.lexers.automation import AutoItLexer
from pygments.lexers.templates import Angular2Lexer
from pygments.lexers.textedit import VimLexer
from support.exceptions import SerialDeviceOpenError  # pylint: disable=E0401
from support.message_dialog import MessageDialog  # pylint: disable=E0401
from support.progress_bar import CustomProgressBar  # pylint: disable=E0401
from support.serial_manage import SerialManager  # pylint: disable=E0401
from support.serial_simulator import \
    random_text_generator  # pylint: disable=E0401
from version import __version__

# ── Global state flags ────────────────────────────────────────────────────────
# UPDATE_LOG_FLAG: controls the periodic_update loop
UPDATE_LOG_FLAG = False
# CLEAR_LOG: signals the loop to wipe the output buffer
CLEAR_LOG = False
# OUTPUT_LOG: current full text of the output log (for export)
OUTPUT_LOG = ""
# LOG_FILE_COUNTER: increments each time the log is exported to file
LOG_FILE_COUNTER = 0
# HIGHLIGHT / HIGHLIGHT_STOP / HIGHLIGHT_STRING: search feature
HIGHLIGHT = False
HIGHLIGHT_STOP = False
HIGHLIGHT_STRING = ""
# CAPTURE / CAPTURE_LOG: log-capture feature
CAPTURE = False
CAPTURE_LOG = ""
CAPTURE_MSG_FLAG = False
CAPTURE_LOG_FILE_COUNTER = 0
# LICENSE: user requested the license view
LICENSE = False
# SEND_COMMAND: user pressed Enter — command ready to send
SEND_COMMAND = False
# DEBUG_MODE: Shift+Tab debug overlay
DEBUG_MODE = False
DEBUG_MODE_TEXT = False
# TAB_PRESSED: send a TAB to the device (autocomplete attempt)
TAB_PRESSED = False
# SHOW_HELP: user requested the help text
SHOW_HELP = False
# PAUSE_LOGGING: freeze the incoming output log
PAUSE_LOGGING = False
# BACKSPACE_PRESSED: user pressed Backspace — remove last char from inserted_command
BACKSPACE_PRESSED = False
# HISTORY_UP / HISTORY_DOWN: navigate command history with arrow keys
HISTORY_UP = False
HISTORY_DOWN = False
# CLEAR_SEARCH: Ctrl+R wipes the search field and disables search modes
CLEAR_SEARCH = False


def get_titlebar_text(custom_msg):
    """
    Returns the formatted header text for the CLI-GUI.
    """
    return [
        ("class:title bg:darkgreen", " [" + custom_msg + "] "),
    ]


def get_options_text():
    """
    Returns the formatted options/key-bindings panel text.
    """
    return [
        ("class:title fg:red",    " [Control+Q] - Quit \n"),
        ("class:title fg:yellow", " [Control+X] - Clear Log \n"),
        ("class:title fg:yellow", " [Control+P] - Pause/Resume Logging \n"),
        ("class:title fg:yellow", " [Control+S] - Export to file \n"),
        ("class:title fg:yellow", " [Control+W] - Start/Stop Capture \n"),
        ("class:title fg:yellow", " [Control+C] - Copy All to Clipboard \n"),
        ("class:title fg:cyan",   " [Control+F] - Highlight Pattern \n"),
        ("class:title fg:cyan",   " [Control+G] - Find and Stop \n"),
        ("class:title fg:cyan",   " [Control+R] - Clear Search \n"),
        ("class:title fg:green",  " [Control+L] - Show License \n"),
        ("class:title fg:green",  " [Control+H] - Help \n"),
        ("class:title fg:green",  " [↑ / ↓]     - Command History \n"),
        ("class:title bg:darkblue fg:white", " [Shift+Tab] - Debug \n"),
    ]


# Adding key bindings
kb = KeyBindings()


class GuiController:
    # pylint: disable=global-statement,global-variable-not-assigned,R0902,R0912
    """
        GuiController manages the CLI-GUI components and the serial device interface.
    """

    def __init__(self, serial_device_path, serial_device_baudrate, simulator_mode: bool,
                 parity='N', stopbits=1):
        """
        Configure default values, build the layout, and start the read thread.
        """
        global UPDATE_LOG_FLAG
        global HIGHLIGHT
        global HIGHLIGHT_STOP

        self.simulator_mode = simulator_mode
        self.serial_dev_path = serial_device_path
        self.inserted_command: str = ""
        self.search_input: str = ""
        self.command_history: list = self._load_history()
        self.history_index: int = -1
        self.session_cwd: str = os.getcwd()  # capture CWD at launch for log file output

        if not simulator_mode:
            self.ser_dev = SerialManager(serial_device_path, serial_device_baudrate,
                                         parity=parity, stopbits=stopbits)
            try:
                self.ser_dev.open_dev()
            except SerialDeviceOpenError:
                MessageDialog("Failed", f"Failed to open the {serial_device_path} device.")
                sys.exit(1)

        # ── Buffers ───────────────────────────────────────────────────────────
        self.left_buffer = Buffer()
        self.right_buffer = Buffer()
        self.status_buffer = Buffer()
        self.search_buffer = Buffer()

        # ── Windows ───────────────────────────────────────────────────────────
        self.left_window = Window(BufferControl(buffer=self.left_buffer,
                                                lexer=PygmentsLexer(VimLexer)), width=10)
        self.status_window = Window(BufferControl(buffer=self.status_buffer,
                                                  lexer=PygmentsLexer(Angular2Lexer)), height=1)
        self.right_window = Window(BufferControl(buffer=self.right_buffer,
                                                 lexer=PygmentsLexer(AutoItLexer),
                                                 focus_on_click=True),
                                   wrap_lines=True, style='class:border')
        self.search_window = Window(BufferControl(buffer=self.search_buffer,
                                                  lexer=PygmentsLexer(Angular2Lexer)),
                                    height=1, style='class:border')

        # ── Layout ────────────────────────────────────────────────────────────
        self.body = \
            HSplit([
                VSplit([
                    HSplit([
                        Window(height=1,
                               content=FormattedTextControl([("class:line", "Input Options")]),
                               style="class:title", align=WindowAlign.CENTER),
                        Window(height=1, char="-", style="class:line"),
                        Window(height=len(get_options_text()),
                               content=FormattedTextControl(get_options_text()),
                               align=WindowAlign.LEFT),
                        Window(height=1, char="-", style="class:line"),
                        Window(height=1,
                               content=FormattedTextControl([("class:line fg:yellow", "Search field")]),
                               style="class:title", align=WindowAlign.CENTER),
                        Window(height=1, char="-", style="class:line"),
                        VSplit([
                            Window(width=2, char="||", style="class:line"),
                            self.search_window,
                            Window(width=2, char="||", style="class:line"),
                        ]),
                        Window(height=1, char="-", style="class:line"),
                        Window(height=1,
                               content=FormattedTextControl([("class:line bg:black fg:green",
                                                              "Commands History")]),
                               style="class:title", align=WindowAlign.CENTER),
                        Window(height=1, char="-", style="class:line"),
                        self.left_window,
                        Window(height=1, char="-", style="class:line"),
                        Window(height=1,
                               content=FormattedTextControl(
                                   [("class:title bg:darkred", " Integrated Software Technologies Inc. ")]),
                               style="class:title", align=WindowAlign.CENTER),
                        Window(height=1,
                               content=FormattedTextControl(
                                   [("class:title bg:darkred", " http://integratedsw.tech ")]),
                               style="class:title", align=WindowAlign.CENTER),
                    ]),
                    Window(width=1, char="|", style="class:line"),
                    HSplit([
                        Window(height=1,
                               content=FormattedTextControl([("class:line", "Output Log")]),
                               style="class:title", align=WindowAlign.CENTER),
                        Window(height=1, char="-", style="class:line"),
                        self.right_window,
                    ]),
                ]),
                Window(height=1, char="-", style="class:line"),
                Window(height=1,
                       content=FormattedTextControl([("class:line", "Status")]),
                       style="class:title", align=WindowAlign.CENTER),
                Window(height=1, char="-", style="class:line"),
                VSplit([
                    self.status_window,
                    Window(height=1,
                           content=FormattedTextControl([("class:line bg:darkblue",
                                                          f'  SoftCOM v{__version__}  ')]),
                           style="class:title", align=WindowAlign.RIGHT),
                ]),
            ])

        self.root_container = HSplit([
            Window(
                height=1,
                content=FormattedTextControl(
                    get_titlebar_text(f"{serial_device_path} {serial_device_baudrate}")),
                align=WindowAlign.CENTER,
            ),
            Window(height=1, char="-", style="class:line"),
            self.body,
        ])

        self.connection_info = f"device {serial_device_path} opened successfully. {serial_device_baudrate}"

        self.right_buffer.on_text_changed += self.update_log_cursor
        self.right_buffer.on_text_insert += self.typing_command
        self.search_buffer.on_text_insert += self.typing_search

        self.application = Application(
            layout=Layout(self.root_container, focused_element=self.right_window),
            key_bindings=kb,
            mouse_support=True,
            full_screen=True,
            cursor=CursorShape.BLINKING_UNDERLINE,
            enable_page_navigation_bindings=True,
        )

        self.read_thread = Thread(target=self.periodic_update, daemon=True)
        UPDATE_LOG_FLAG = True
        self.read_thread.start()
        self.application.run()

    def __del__(self):
        """
        Cleanup on destruction.
        """
        if not self.simulator_mode and hasattr(self, 'ser_dev'):
            self.ser_dev.close_dev()

    @staticmethod
    def _load_history() -> list:
        """
        Load command history from ~/.softcom_history.
        Returns an empty list if the file does not exist or cannot be read.
        """
        try:
            if os.path.isfile(_HISTORY_FILE):
                with open(_HISTORY_FILE, encoding='utf-8') as f:
                    lines = [l.rstrip('\n') for l in f.readlines() if l.strip()]
                return lines[-_MAX_HISTORY:]
        except OSError:
            pass
        return []

    def _save_history(self):
        """
        Persist the current command history to ~/.softcom_history (capped at _MAX_HISTORY).
        """
        try:
            entries = self.command_history[-_MAX_HISTORY:]
            with open(_HISTORY_FILE, 'w', encoding='utf-8') as f:
                f.write('\n'.join(entries) + '\n')
        except OSError:
            pass

    def get_status_text(self):
        """
        Build the status bar string.
        """
        if self.simulator_mode:
            return_var = "| Device:OPEN(SIM) |"
        else:
            return_var = "| Device:OPEN |" if self.ser_dev.is_dev_open() else "| Device:CLOSE |"

        if HIGHLIGHT:
            return_var += f" Search:ON:[{HIGHLIGHT_STRING}] |"
        if HIGHLIGHT_STOP:
            return_var += f" Search_Stop:ON:[{HIGHLIGHT_STRING}] |"
        if CAPTURE:
            return_var += " Capture:ON |"
        if PAUSE_LOGGING:
            return_var += " Paused |"
        if DEBUG_MODE:
            return_var += f" DEBUG_MODE:ON:[{DEBUG_MODE_TEXT}] |"
        return return_var

    def typing_search(self, _):
        """
        Called when the user types in the search field.
        """
        global HIGHLIGHT_STRING
        self.search_input = HIGHLIGHT_STRING = self.search_buffer.text

    def typing_command(self, event):
        """
        Called when the user types in the output log field.
        """
        global DEBUG_MODE
        global DEBUG_MODE_TEXT
        self.inserted_command += event.text[-1]
        if DEBUG_MODE:
            DEBUG_MODE_TEXT += event.text[-1]

    def update_log_cursor(self, _):  # pylint: disable=R0201
        """
        Keep the cursor at the end of the output log after each update.
        """
        self.update_cursor()

    def update_cursor(self):
        """
        Move the cursor to the end of the last line in the output log.
        """
        lines = self.right_buffer.text.splitlines()
        if lines:
            self.right_buffer.auto_down()
            self.right_buffer.cursor_right(len(lines[-1]))

    def send_command(self, command):
        """
        Write a command to the serial device and record it in the history panel.
        """
        if command == "\n":
            return
        if not self.simulator_mode:
            self.ser_dev.exe_command(command)
        self.left_buffer.text += '- ' + command

    def periodic_update(self):
        """
        Background thread: polls the serial device, processes state flags,
        and updates the UI buffers.
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
        global SHOW_HELP
        global BACKSPACE_PRESSED
        global HISTORY_UP
        global HISTORY_DOWN
        global CLEAR_SEARCH

        while UPDATE_LOG_FLAG:
            # ── Device disconnect check ───────────────────────────────────
            if not exists(self.serial_dev_path) and not self.simulator_mode:
                UPDATE_LOG_FLAG = False
                msg = f"ERROR: {self.serial_dev_path} is not connected."
                separator = "-" * len(msg)
                self.right_buffer.text += f"\n{separator}\n{msg}\n{separator}\n"
                get_app().exit()
                return

            # ── Status bar ───────────────────────────────────────────────
            self.status_buffer.reset()
            self.status_buffer.text = self.get_status_text()

            # ── License display ──────────────────────────────────────────
            if LICENSE:
                UPDATE_LOG_FLAG = False
                try:
                    license_path = os.path.join(os.path.dirname(os.path.realpath(__file__)), 'LICENSE')
                    with open(license_path, "r", encoding='UTF-8') as file:
                        data = file.read()
                    self.right_buffer.text += str(data)
                    self.right_buffer.text += "\n\nPlease close the program and re-open.\n\n"
                except FileNotFoundError:
                    self.right_buffer.text += "\n[LICENSE file not found]\n"

            # ── Help display ─────────────────────────────────────────────
            if SHOW_HELP:
                SHOW_HELP = False
                try:
                    help_path = os.path.join(os.path.dirname(os.path.realpath(__file__)), 'HELP')
                    with open(help_path, "r", encoding='UTF-8') as file:
                        data = file.read()
                    self.right_buffer.text += f"\n\n{data}\n\n"
                except FileNotFoundError:
                    self.right_buffer.text += "\n[HELP file not found]\n"

            # ── Backspace: remove last char from inserted_command ────────
            if BACKSPACE_PRESSED:
                if self.application.layout.current_control == self.right_window.content:
                    self.inserted_command = self.inserted_command[:-1]
                else:
                    self.search_buffer.text = self.search_buffer.text[:-1]
                    self.search_input = self.search_input[:-1]
                    HIGHLIGHT_STRING = HIGHLIGHT_STRING[:-1]
                BACKSPACE_PRESSED = False

            # ── Clear search: reset search field and modes ───────────────
            if CLEAR_SEARCH:
                HIGHLIGHT = False
                HIGHLIGHT_STOP = False
                HIGHLIGHT_STRING = ""
                self.search_buffer.text = ""
                self.search_input = ""
                CLEAR_SEARCH = False

            # ── Tab: send a literal tab character (autocomplete) ─────────
            if TAB_PRESSED:
                self.send_command(self.inserted_command + "\t")
                TAB_PRESSED = False

            # ── History navigation ────────────────────────────────────────
            if HISTORY_UP:
                HISTORY_UP = False
                if self.command_history:
                    self.history_index = min(self.history_index + 1,
                                             len(self.command_history) - 1)
                    new_cmd = self.command_history[-(self.history_index + 1)]
                    if self.inserted_command:
                        self.right_buffer.text = self.right_buffer.text[:-len(self.inserted_command)]
                    self.inserted_command = new_cmd
                    self.right_buffer.text += new_cmd

            if HISTORY_DOWN:
                HISTORY_DOWN = False
                if self.history_index > 0:
                    self.history_index -= 1
                    new_cmd = self.command_history[-(self.history_index + 1)]
                    if self.inserted_command:
                        self.right_buffer.text = self.right_buffer.text[:-len(self.inserted_command)]
                    self.inserted_command = new_cmd
                    self.right_buffer.text += new_cmd
                elif self.history_index == 0:
                    self.history_index = -1
                    if self.inserted_command:
                        self.right_buffer.text = self.right_buffer.text[:-len(self.inserted_command)]
                    self.inserted_command = ""

            # ── Send command ─────────────────────────────────────────────
            if SEND_COMMAND:
                cmd = self.inserted_command
                self.send_command(cmd + "\n")
                if cmd.strip():
                    self.command_history.append(cmd.strip())
                    self._save_history()
                self.history_index = -1
                self.inserted_command = ""
                SEND_COMMAND = False

            # ── Clear log ────────────────────────────────────────────────
            if CLEAR_LOG:
                self.right_buffer.reset()
                OUTPUT_LOG = ""
                CLEAR_LOG = False

            # ── Incoming serial / simulator data ─────────────────────────
            if not PAUSE_LOGGING:
                if self.simulator_mode:
                    incoming_packet = random_text_generator()
                    time.sleep(0.2)
                else:
                    incoming_packet = self.ser_dev.read()
                    if incoming_packet is None:
                        incoming_packet = ""

                already_displayed = self.check_incoming_packet(incoming_packet)
                if not already_displayed:
                    self.right_buffer.text += (
                        incoming_packet
                        .replace('\r', '')
                        .replace('^M', '')
                        .replace('\b', '')
                        .replace('\t', '')
                    )
                OUTPUT_LOG = self.right_buffer.text

    def check_incoming_packet(self, incoming_packet) -> bool:
        """
        Apply search highlighting, stop-on-match, and capture logic
        to each incoming packet.

        Returns True if the packet was already written to the buffer in
        highlighted form, so the caller should skip the raw append.
        Returns False when the caller should append the raw packet itself.
        """
        global HIGHLIGHT
        global HIGHLIGHT_STRING
        global HIGHLIGHT_STOP
        global UPDATE_LOG_FLAG
        global CAPTURE
        global CAPTURE_LOG
        global CAPTURE_MSG_FLAG
        global CAPTURE_LOG_FILE_COUNTER

        if not incoming_packet:
            return False

        displayed = False

        # ── Highlight search ──────────────────────────────────────────────
        if HIGHLIGHT and HIGHLIGHT_STRING:
            found = incoming_packet.find(HIGHLIGHT_STRING)
            if found >= 0:
                highlighted = (
                    '\n\n\n-->FOUND\n'
                    + incoming_packet[:found]
                    + '\x1b[6;30;42m'
                    + incoming_packet[found:found + len(HIGHLIGHT_STRING)]
                    + '\x1b[0m'
                    + incoming_packet[found + len(HIGHLIGHT_STRING):]
                    + '\n\n\n'
                )
                self.right_buffer.text += highlighted
                displayed = True

        # ── Search and stop ───────────────────────────────────────────────
        if HIGHLIGHT_STOP and HIGHLIGHT_STRING:
            found = incoming_packet.find(HIGHLIGHT_STRING)
            if found >= 0:
                highlighted = (
                    '\n\n\n-->FOUND\n'
                    + incoming_packet[:found]
                    + '\x1b[6;30;42m'
                    + incoming_packet[found:found + len(HIGHLIGHT_STRING)]
                    + '\x1b[0m'
                    + incoming_packet[found + len(HIGHLIGHT_STRING):]
                    + '\n\n\n'
                )
                self.right_buffer.text += highlighted
                displayed = True
                UPDATE_LOG_FLAG = False

        # ── Capture ───────────────────────────────────────────────────────
        if CAPTURE:
            CAPTURE_LOG += incoming_packet
            if not CAPTURE_MSG_FLAG:
                self.right_buffer.text += \
                    "\n\n------------------------Capture-Started------------------------\n"
                CAPTURE_MSG_FLAG = True

        if not CAPTURE and CAPTURE_MSG_FLAG:
            filename = f'Capture_log{CAPTURE_LOG_FILE_COUNTER}.txt'
            capture_path = os.path.join(self.session_cwd, filename)
            try:
                with open(capture_path, 'w', encoding='UTF-8') as file:
                    file.write(CAPTURE_LOG)
                CAPTURE_LOG_FILE_COUNTER += 1
                self.right_buffer.text += (
                    f"\n\n--- Capture saved → {filename} ---\n\n"
                )
            except OSError as err:
                self.right_buffer.text += f"\n\n--- Capture save failed: {err} ---\n\n"
            CAPTURE_LOG = ""
            CAPTURE_MSG_FLAG = False

        return displayed


# ── Key bindings ──────────────────────────────────────────────────────────────

@kb.add("c-q", eager=True)
def _(event):
    """Ctrl+Q — quit"""
    global UPDATE_LOG_FLAG  # pylint: disable=global-statement
    UPDATE_LOG_FLAG = False
    CustomProgressBar("Exiting", 100)
    event.app.exit()


@kb.add("c-x", eager=True)
def _(_):
    """Ctrl+X — clear log"""
    global CLEAR_LOG  # pylint: disable=global-statement
    CLEAR_LOG = True


@kb.add("c-s", eager=True)
def _(_):
    """Ctrl+S — save log to file in the current working directory"""
    global OUTPUT_LOG        # pylint: disable=global-statement,W0602
    global LOG_FILE_COUNTER  # pylint: disable=global-statement
    filename = f'OUTPUT_LOG{LOG_FILE_COUNTER}.txt'
    out_path = os.path.join(os.getcwd(), filename)
    try:
        with open(out_path, 'w', encoding='UTF-8') as file:
            file.write(OUTPUT_LOG)
        LOG_FILE_COUNTER += 1
    except OSError:
        pass


@kb.add("c-c", eager=True)
def _(_):
    """Ctrl+C — copy log to clipboard"""
    global OUTPUT_LOG  # pylint: disable=global-statement,W0602
    pyperclip.copy(OUTPUT_LOG)


@kb.add("c-w", eager=True)
def _(_):
    """Ctrl+W — toggle capture"""
    global CAPTURE  # pylint: disable=global-statement,W0602
    CAPTURE = not CAPTURE


@kb.add("c-l", eager=True)
def _(_):
    """Ctrl+L — show license"""
    global LICENSE  # pylint: disable=global-statement,W0602
    LICENSE = True


@kb.add("c-m", eager=True)
def _(_):
    """Enter — submit command"""
    global SEND_COMMAND  # pylint: disable=global-statement,W0602
    SEND_COMMAND = True


@kb.add("s-tab", eager=True)
def _(_):
    """Shift+Tab — toggle debug mode"""
    global DEBUG_MODE       # pylint: disable=global-statement,W0602
    global DEBUG_MODE_TEXT  # pylint: disable=global-statement,W0602
    DEBUG_MODE = not DEBUG_MODE
    DEBUG_MODE_TEXT = ''


@kb.add("c-g", eager=True)
def _(_):
    """Ctrl+G — toggle search-and-stop mode"""
    global HIGHLIGHT_STOP  # pylint: disable=global-statement,W0602
    HIGHLIGHT_STOP = not HIGHLIGHT_STOP
    get_app().layout.focus_next()
    get_app().layout.focus_next()


@kb.add("c-f", eager=True)
def _(_):
    """Ctrl+F — toggle highlight search mode"""
    global HIGHLIGHT  # pylint: disable=global-statement,W0602
    HIGHLIGHT = not HIGHLIGHT
    get_app().layout.focus_next()
    get_app().layout.focus_next()


@kb.add("c-r", eager=True)
def _(_):
    """Ctrl+R — clear search string and disable search modes"""
    global CLEAR_SEARCH  # pylint: disable=global-statement,W0602
    CLEAR_SEARCH = True


@kb.add("c-i", eager=True)
def _(_):
    """Tab — send tab to device (autocomplete attempt)"""
    global TAB_PRESSED  # pylint: disable=global-statement,W0602
    TAB_PRESSED = True


@kb.add("c-h", eager=True)
def _(_):
    """Ctrl+H — show help"""
    global SHOW_HELP  # pylint: disable=global-statement,W0602
    SHOW_HELP = True


@kb.add("backspace", eager=True)
def _(_):
    """Backspace — remove last character from the active input"""
    global BACKSPACE_PRESSED  # pylint: disable=global-statement,W0602
    BACKSPACE_PRESSED = True


@kb.add("c-p", eager=True)
def _(_):
    """Ctrl+P — pause / resume incoming log"""
    global PAUSE_LOGGING  # pylint: disable=global-statement,W0602
    PAUSE_LOGGING = not PAUSE_LOGGING


@kb.add("up", eager=True)
def _(_):
    """Up arrow — scroll back through command history"""
    global HISTORY_UP  # pylint: disable=global-statement,W0602
    HISTORY_UP = True


@kb.add("down", eager=True)
def _(_):
    """Down arrow — scroll forward through command history"""
    global HISTORY_DOWN  # pylint: disable=global-statement,W0602
    HISTORY_DOWN = True
