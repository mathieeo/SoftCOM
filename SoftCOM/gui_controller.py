#!/usr/bin/env python3
"""
    GUI Controller — manages the CLI GUI components and the serial device I/O interface.
"""
import os
import sys
import time
from os.path import exists
from threading import Thread

_HISTORY_FILE = os.path.join(os.path.expanduser("~"), ".softcom_history")
_MAX_HISTORY = 500

import pyperclip
from prompt_toolkit.application import Application, get_app
from prompt_toolkit.buffer import Buffer
from prompt_toolkit.cursor_shapes import CursorShape
from prompt_toolkit.filters import Condition
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout.containers import (ConditionalContainer, HSplit,
                                              VSplit, Window, WindowAlign)
from prompt_toolkit.layout.controls import BufferControl, FormattedTextControl
from prompt_toolkit.layout.layout import Layout
from prompt_toolkit.lexers import PygmentsLexer
from pygments.lexers.automation import AutoItLexer
from pygments.lexers.textedit import VimLexer
from support.exceptions import SerialDeviceOpenError  # pylint: disable=E0401
from support.message_dialog import MessageDialog  # pylint: disable=E0401
from support.progress_bar import CustomProgressBar  # pylint: disable=E0401
from support.serial_manage import SerialManager  # pylint: disable=E0401
from support.serial_simulator import \
    random_text_generator  # pylint: disable=E0401
from version import __version__

# ── Global state flags ────────────────────────────────────────────────────────
UPDATE_LOG_FLAG = False
CLEAR_LOG = False
OUTPUT_LOG = ""
LOG_FILE_COUNTER = 0
SEARCH_ACTIVE = False       # Ctrl+F — toggle search bar
SEARCH_STRING = ""          # current search pattern (from search_buffer)
CAPTURE = False
CAPTURE_LOG = ""
CAPTURE_MSG_FLAG = False
CAPTURE_LOG_FILE_COUNTER = 0
LICENSE = False
SEND_COMMAND = False
TAB_PRESSED = False
SHOW_HELP = False
PAUSE_LOGGING = False
HISTORY_UP = False
HISTORY_DOWN = False
TIMESTAMPS = False          # Ctrl+T — prefix each incoming line with HH:MM:SS
CLEAR_INPUT = False         # Ctrl+K — clear the input bar

# Module-level reference to the running GuiController instance (used by key bindings)
_gui_instance = None


def get_titlebar_text(custom_msg):
    """Return formatted header text for the title bar."""
    return [("class:title bg:darkgreen", f"  SoftCOM  ·  {custom_msg}  ")]


def get_options_text():
    """Return formatted key-bindings reference panel."""
    return [
        ("class:title fg:red",    " [Ctrl+Q] Quit\n"),
        ("class:title fg:yellow", " [Ctrl+X] Clear Log\n"),
        ("class:title fg:yellow", " [Ctrl+P] Pause / Resume\n"),
        ("class:title fg:yellow", " [Ctrl+S] Export Log\n"),
        ("class:title fg:yellow", " [Ctrl+W] Start/Stop Capture\n"),
        ("class:title fg:yellow", " [Ctrl+C] Copy to Clipboard\n"),
        ("class:title fg:yellow", " [Ctrl+K] Clear Input\n"),
        ("class:title fg:cyan",   " [Ctrl+F] Search  [Esc] Close\n"),
        ("class:title fg:green",  " [Ctrl+T] Timestamps\n"),
        ("class:title fg:green",  " [Ctrl+L] License\n"),
        ("class:title fg:green",  " [Ctrl+H] Help\n"),
        ("class:title fg:green",  " [Tab]    Autocomplete\n"),
        ("class:title fg:green",  " [\u2191 / \u2193]   History\n"),
    ]


kb = KeyBindings()


# ── Condition filter for ConditionalContainer ─────────────────────────────────
@Condition
def _is_search_active():
    return SEARCH_ACTIVE


class GuiController:
    # pylint: disable=global-statement,global-variable-not-assigned,R0902,R0912
    """
    GuiController manages the CLI-GUI components and the serial device interface.

    Layout (top → bottom):
        Title bar
        ─────────────────────────────────────────────────────
        Left panel (options + history) │ Output log
        ─────────────────────────────────────────────────────
        [Search bar — visible only when search is active]
        ─────────────────────────────────────────────────────
        > Input bar  (always focused — this is where you type)
        ─────────────────────────────────────────────────────
        Status bar                         SoftCOM vX.Y.Z
    """

    def __init__(self, serial_device_path, serial_device_baudrate, simulator_mode: bool,
                 parity='N', stopbits=1):
        global UPDATE_LOG_FLAG, _gui_instance

        self.simulator_mode = simulator_mode
        self.serial_dev_path = serial_device_path
        self.command_history: list = self._load_history()
        self.history_index: int = -1
        self.session_cwd: str = os.getcwd()

        if not simulator_mode:
            self.ser_dev = SerialManager(serial_device_path, serial_device_baudrate,
                                         parity=parity, stopbits=stopbits)
            try:
                self.ser_dev.open_dev()
            except SerialDeviceOpenError:
                MessageDialog("Failed", f"Failed to open the {serial_device_path} device.")
                sys.exit(1)

        # ── Buffers ───────────────────────────────────────────────────────────
        self.output_buffer = Buffer()     # device output (read-only to user)
        self.input_buffer = Buffer()      # command input (user types here)
        self.history_buffer = Buffer()    # left panel command history list
        self.search_buffer = Buffer()     # search pattern field
        self.status_buffer = Buffer()     # status bar

        # ── Windows ───────────────────────────────────────────────────────────
        self.output_window = Window(
            BufferControl(buffer=self.output_buffer,
                          lexer=PygmentsLexer(AutoItLexer),
                          focus_on_click=True),
            wrap_lines=True,
            style='class:border',
        )
        self.input_window = Window(
            BufferControl(buffer=self.input_buffer),
            height=1,
        )
        self.history_window = Window(
            BufferControl(buffer=self.history_buffer, lexer=PygmentsLexer(VimLexer)),
        )
        self.search_window = Window(
            BufferControl(buffer=self.search_buffer),
            height=1,
        )
        self.status_window = Window(
            BufferControl(buffer=self.status_buffer),
            height=1,
        )

        # ── Search bar row (shown only when Ctrl+F is active) ─────────────────
        search_bar = ConditionalContainer(
            content=HSplit([
                Window(height=1, char="─", style="class:line"),
                VSplit([
                    Window(width=10,
                           content=FormattedTextControl(
                               [("class:title fg:cyan", " Search: ")]),
                           height=1),
                    self.search_window,
                    Window(width=14,
                           content=FormattedTextControl(
                               [("class:title fg:darkgray", "  [Esc] to close")]),
                           height=1),
                ]),
            ]),
            filter=_is_search_active,
        )

        # ── Left panel: options + command history ─────────────────────────────
        left_panel = HSplit([
            Window(height=1,
                   content=FormattedTextControl([("class:line", " Options")]),
                   style="class:title", align=WindowAlign.LEFT),
            Window(height=1, char="─", style="class:line"),
            Window(content=FormattedTextControl(get_options_text()),
                   height=len(get_options_text()), align=WindowAlign.LEFT),
            Window(height=1, char="─", style="class:line"),
            Window(height=1,
                   content=FormattedTextControl(
                       [("class:line bg:black fg:green", " Recent Commands")]),
                   style="class:title", align=WindowAlign.LEFT),
            Window(height=1, char="─", style="class:line"),
            self.history_window,
            Window(height=1, char="─", style="class:line"),
            Window(height=1,
                   content=FormattedTextControl(
                       [("class:title bg:darkred", " IST Inc.")]),
                   style="class:title", align=WindowAlign.CENTER),
        ], width=32)

        # ── Full layout ───────────────────────────────────────────────────────
        self.root_container = HSplit([
            # Title bar
            Window(
                height=1,
                content=FormattedTextControl(
                    get_titlebar_text(f"{serial_device_path}  {serial_device_baudrate}")),
                align=WindowAlign.CENTER,
            ),
            Window(height=1, char="─", style="class:line"),
            # Main body: left panel + output log
            VSplit([
                left_panel,
                Window(width=1, char="│", style="class:line"),
                HSplit([
                    Window(height=1,
                           content=FormattedTextControl([("class:line", " Output Log")]),
                           style="class:title", align=WindowAlign.LEFT),
                    Window(height=1, char="─", style="class:line"),
                    self.output_window,
                ]),
            ]),
            # Search bar (conditional)
            search_bar,
            # Input bar
            Window(height=1, char="─", style="class:line"),
            VSplit([
                Window(width=3, height=1,
                       content=FormattedTextControl([("class:title fg:green", " > ")])),
                self.input_window,
            ]),
            # Status bar
            Window(height=1, char="─", style="class:line"),
            VSplit([
                self.status_window,
                Window(height=1,
                       content=FormattedTextControl(
                           [("class:line bg:darkblue", f"  SoftCOM v{__version__}  ")]),
                       style="class:title", align=WindowAlign.RIGHT),
            ]),
        ])

        self.search_buffer.on_text_changed += self._on_search_changed

        self.application = Application(
            layout=Layout(self.root_container, focused_element=self.input_window),
            key_bindings=kb,
            mouse_support=True,
            full_screen=True,
            cursor=CursorShape.BLINKING_BEAM,
            enable_page_navigation_bindings=True,
        )

        _gui_instance = self
        self.read_thread = Thread(target=self.periodic_update, daemon=True)
        UPDATE_LOG_FLAG = True
        self.read_thread.start()
        self.application.run()

    def __del__(self):
        if not self.simulator_mode and hasattr(self, 'ser_dev'):
            self.ser_dev.close_dev()

    # ── History persistence ───────────────────────────────────────────────────

    @staticmethod
    def _load_history() -> list:
        """Load command history from ~/.softcom_history."""
        try:
            if os.path.isfile(_HISTORY_FILE):
                with open(_HISTORY_FILE, encoding='utf-8') as f:
                    lines = [line.rstrip('\n') for line in f.readlines() if line.strip()]
                return lines[-_MAX_HISTORY:]
        except OSError:
            pass
        return []

    def _save_history(self):
        """Persist command history to ~/.softcom_history."""
        try:
            entries = self.command_history[-_MAX_HISTORY:]
            with open(_HISTORY_FILE, 'w', encoding='utf-8') as f:
                f.write('\n'.join(entries) + '\n')
        except OSError:
            pass

    # ── Callbacks ─────────────────────────────────────────────────────────────

    def _on_search_changed(self, _):
        """Keep SEARCH_STRING in sync with search_buffer."""
        global SEARCH_STRING
        SEARCH_STRING = self.search_buffer.text

    # ── Status bar ────────────────────────────────────────────────────────────

    def get_status_text(self) -> str:
        if self.simulator_mode:
            status = "| Device: OPEN (SIM) |"
        else:
            status = "| Device: OPEN |" if self.ser_dev.is_dev_open() else "| Device: CLOSED |"
        if SEARCH_ACTIVE and SEARCH_STRING:
            status += f" Search: [{SEARCH_STRING}] |"
        if CAPTURE:
            status += " Capture: ON |"
        if PAUSE_LOGGING:
            status += " Paused |"
        if TIMESTAMPS:
            status += " Timestamps |"
        return status

    # ── Serial I/O ────────────────────────────────────────────────────────────

    def send_command(self, command: str):
        """Send a command to the device and record it in the history panel."""
        if not self.simulator_mode:
            self.ser_dev.exe_command(command)
        display = command.rstrip('\n')
        if display:
            self.history_buffer.text += display + '\n'

    def _append_to_output(self, text: str):
        """Append text to the output log and scroll to bottom."""
        if not text:
            return
        if TIMESTAMPS:
            ts = time.strftime("[%H:%M:%S] ")
            lines_out = text.splitlines(keepends=True)
            text = "".join(ts + line for line in lines_out)
        self.output_buffer.text += text
        # Scroll to bottom by moving cursor to end
        self.output_buffer.cursor_position = len(self.output_buffer.text)

    def _process_incoming(self, incoming: str):
        """Clean, optionally highlight, and append incoming device data."""
        global CAPTURE, CAPTURE_LOG, CAPTURE_MSG_FLAG, CAPTURE_LOG_FILE_COUNTER

        clean = (incoming
                 .replace('\r', '')
                 .replace('^M', '')
                 .replace('\b', ''))

        # ── Capture ───────────────────────────────────────────────────────
        if CAPTURE:
            CAPTURE_LOG += clean
            if not CAPTURE_MSG_FLAG:
                self._append_to_output("\n─── Capture started ───\n")
                CAPTURE_MSG_FLAG = True

        if not CAPTURE and CAPTURE_MSG_FLAG:
            filename = f'Capture_log{CAPTURE_LOG_FILE_COUNTER}.txt'
            capture_path = os.path.join(self.session_cwd, filename)
            try:
                with open(capture_path, 'w', encoding='UTF-8') as f:
                    f.write(CAPTURE_LOG)
                CAPTURE_LOG_FILE_COUNTER += 1
                self._append_to_output(f"\n─── Capture saved → {filename} ───\n")
            except OSError as err:
                self._append_to_output(f"\n─── Capture save failed: {err} ───\n")
            CAPTURE_LOG = ""
            CAPTURE_MSG_FLAG = False

        # ── Search highlight (bold yellow, no banners) ────────────────────
        if SEARCH_ACTIVE and SEARCH_STRING and SEARCH_STRING in clean:
            highlighted = clean.replace(
                SEARCH_STRING,
                '\x1b[1;33m' + SEARCH_STRING + '\x1b[0m',
            )
            self._append_to_output(highlighted)
        else:
            self._append_to_output(clean)

    # ── Background update loop ────────────────────────────────────────────────

    def periodic_update(self):  # pylint: disable=R0912
        """
        Background thread: polls the device, processes state flags, updates UI buffers.
        """
        global CLEAR_LOG, OUTPUT_LOG, UPDATE_LOG_FLAG
        global LICENSE, SEND_COMMAND, TAB_PRESSED, SHOW_HELP
        global HISTORY_UP, HISTORY_DOWN, TIMESTAMPS, CLEAR_INPUT  # noqa: F841

        while UPDATE_LOG_FLAG:
            # ── Device disconnect check ───────────────────────────────────
            if not exists(self.serial_dev_path) and not self.simulator_mode:
                UPDATE_LOG_FLAG = False
                self.output_buffer.text += (
                    f"\n─── ERROR: {self.serial_dev_path} disconnected ───\n"
                )
                self.output_buffer.cursor_position = len(self.output_buffer.text)
                try:
                    get_app().exit()
                except Exception:  # pylint: disable=broad-except
                    pass
                return

            # ── Status bar ───────────────────────────────────────────────
            self.status_buffer.reset()
            self.status_buffer.text = self.get_status_text()

            # ── License display ──────────────────────────────────────────
            if LICENSE:
                LICENSE = False
                try:
                    lic_path = os.path.join(
                        os.path.dirname(os.path.realpath(__file__)), 'LICENSE')
                    with open(lic_path, encoding='UTF-8') as f:
                        self._append_to_output("\n" + f.read() + "\n")
                except FileNotFoundError:
                    self._append_to_output("\n[LICENSE file not found]\n")

            # ── Help display ─────────────────────────────────────────────
            if SHOW_HELP:
                SHOW_HELP = False
                try:
                    help_path = os.path.join(
                        os.path.dirname(os.path.realpath(__file__)), 'HELP')
                    with open(help_path, encoding='UTF-8') as f:
                        self._append_to_output("\n" + f.read() + "\n")
                except FileNotFoundError:
                    self._append_to_output("\n[HELP file not found]\n")

            # ── Clear input bar ──────────────────────────────────────────
            if CLEAR_INPUT:
                CLEAR_INPUT = False
                self.input_buffer.text = ""
                self.input_buffer.cursor_position = 0
                self.history_index = -1

            # ── Tab autocomplete: send \t, wait, read back completion ─────
            if TAB_PRESSED:
                TAB_PRESSED = False
                current = self.input_buffer.text
                if not self.simulator_mode:
                    self.ser_dev.exe_command(current + "\t")
                    time.sleep(0.45)
                    response = self.ser_dev.read()
                    if response:
                        # Try to extract the completed command from the device echo.
                        # The device typically echoes the suffix of the completion.
                        # Heuristic: last non-empty line that doesn't look like a prompt.
                        resp_lines = [ln.strip() for ln in response.splitlines() if ln.strip()]
                        if resp_lines:
                            candidate = resp_lines[-1]
                            # Accept as completion if it starts with the current input prefix
                            prefix = current.lstrip()
                            if prefix and candidate.startswith(prefix):
                                self.input_buffer.text = candidate
                                self.input_buffer.cursor_position = len(candidate)
                        clean_resp = response.replace('\r', '').replace('^M', '')
                        self._append_to_output(clean_resp)

            # ── History navigation ────────────────────────────────────────
            if HISTORY_UP:
                HISTORY_UP = False
                if self.command_history:
                    self.history_index = min(
                        self.history_index + 1, len(self.command_history) - 1)
                    cmd = self.command_history[-(self.history_index + 1)]
                    self.input_buffer.text = cmd
                    self.input_buffer.cursor_position = len(cmd)

            if HISTORY_DOWN:
                HISTORY_DOWN = False
                if self.history_index > 0:
                    self.history_index -= 1
                    cmd = self.command_history[-(self.history_index + 1)]
                    self.input_buffer.text = cmd
                    self.input_buffer.cursor_position = len(cmd)
                elif self.history_index == 0:
                    self.history_index = -1
                    self.input_buffer.text = ""
                    self.input_buffer.cursor_position = 0

            # ── Send command ─────────────────────────────────────────────
            if SEND_COMMAND:
                SEND_COMMAND = False
                cmd = self.input_buffer.text
                self.send_command(cmd + "\n")
                if cmd.strip():
                    self.command_history.append(cmd.strip())
                    self._save_history()
                self.history_index = -1
                self.input_buffer.text = ""
                self.input_buffer.cursor_position = 0

            # ── Clear log ────────────────────────────────────────────────
            if CLEAR_LOG:
                CLEAR_LOG = False
                self.output_buffer.text = ""
                self.output_buffer.cursor_position = 0
                OUTPUT_LOG = ""

            # ── Incoming serial / simulator data ─────────────────────────
            if not PAUSE_LOGGING:
                if self.simulator_mode:
                    incoming = random_text_generator()
                    time.sleep(0.2)
                else:
                    incoming = self.ser_dev.read() or ""
                if incoming:
                    self._process_incoming(incoming)
                OUTPUT_LOG = self.output_buffer.text


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
    """Ctrl+X — clear output log"""
    global CLEAR_LOG  # pylint: disable=global-statement
    CLEAR_LOG = True


@kb.add("c-s", eager=True)
def _(_):
    """Ctrl+S — save output log to file in the current working directory"""
    global OUTPUT_LOG, LOG_FILE_COUNTER  # pylint: disable=global-statement
    filename = f'OUTPUT_LOG{LOG_FILE_COUNTER}.txt'
    try:
        with open(os.path.join(os.getcwd(), filename), 'w', encoding='UTF-8') as f:
            f.write(OUTPUT_LOG)
        LOG_FILE_COUNTER += 1
    except OSError:
        pass


@kb.add("c-c", eager=True)
def _(_):
    """Ctrl+C — copy output log to clipboard"""
    pyperclip.copy(OUTPUT_LOG)


@kb.add("c-w", eager=True)
def _(_):
    """Ctrl+W — toggle capture"""
    global CAPTURE  # pylint: disable=global-statement
    CAPTURE = not CAPTURE


@kb.add("c-l", eager=True)
def _(_):
    """Ctrl+L — show license in output log"""
    global LICENSE  # pylint: disable=global-statement
    LICENSE = True


@kb.add("c-m", eager=True)
def _(_):
    """Enter — send the current input to the device"""
    global SEND_COMMAND  # pylint: disable=global-statement
    SEND_COMMAND = True


@kb.add("tab", eager=True)
def _(_):
    """Tab — send Tab to the device for shell autocomplete"""
    global TAB_PRESSED  # pylint: disable=global-statement
    TAB_PRESSED = True


@kb.add("c-f", eager=True)
def _(_):
    """Ctrl+F — open/close search bar"""
    global SEARCH_ACTIVE, SEARCH_STRING  # pylint: disable=global-statement
    SEARCH_ACTIVE = not SEARCH_ACTIVE
    if _gui_instance is not None:
        try:
            if SEARCH_ACTIVE:
                get_app().layout.focus(_gui_instance.search_window)
            else:
                SEARCH_STRING = ""
                _gui_instance.search_buffer.text = ""
                get_app().layout.focus(_gui_instance.input_window)
            get_app().invalidate()
        except Exception:  # pylint: disable=broad-except
            pass


@kb.add("escape", eager=True)
def _(_):
    """Esc — close search bar and return focus to input"""
    global SEARCH_ACTIVE, SEARCH_STRING  # pylint: disable=global-statement
    if SEARCH_ACTIVE:
        SEARCH_ACTIVE = False
        SEARCH_STRING = ""
        if _gui_instance is not None:
            try:
                _gui_instance.search_buffer.text = ""
                get_app().layout.focus(_gui_instance.input_window)
                get_app().invalidate()
            except Exception:  # pylint: disable=broad-except
                pass


@kb.add("c-t", eager=True)
def _(_):
    """Ctrl+T — toggle timestamp prefix on incoming lines"""
    global TIMESTAMPS  # pylint: disable=global-statement
    TIMESTAMPS = not TIMESTAMPS


@kb.add("c-k", eager=True)
def _(_):
    """Ctrl+K — clear the input bar"""
    global CLEAR_INPUT  # pylint: disable=global-statement
    CLEAR_INPUT = True


@kb.add("c-h", eager=True)
def _(_):
    """Ctrl+H — show help in output log"""
    global SHOW_HELP  # pylint: disable=global-statement
    SHOW_HELP = True


@kb.add("c-p", eager=True)
def _(_):
    """Ctrl+P — pause / resume incoming log"""
    global PAUSE_LOGGING  # pylint: disable=global-statement
    PAUSE_LOGGING = not PAUSE_LOGGING


@kb.add("up", eager=True)
def _(_):
    """Up arrow — scroll back through command history"""
    global HISTORY_UP  # pylint: disable=global-statement
    HISTORY_UP = True


@kb.add("down", eager=True)
def _(_):
    """Down arrow — scroll forward through command history"""
    global HISTORY_DOWN  # pylint: disable=global-statement
    HISTORY_DOWN = True
