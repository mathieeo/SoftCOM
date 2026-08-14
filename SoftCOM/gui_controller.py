#!/usr/bin/env python3
"""
    GUI Controller — manages the CLI GUI components and the serial device I/O interface.
"""
import os
import queue
import re
import stat
import sys
import threading
import time
from os.path import exists
from threading import Lock, Thread

_HISTORY_FILE = os.path.join(os.path.expanduser("~"), ".softcom_history")
_MAX_HISTORY = 500

# A device asking for a secret, e.g. "Password:", "password for root:", "Enter passphrase:",
# "PIN:". Anchored to the END of what the device has sent, because a prompt is the last thing
# on the wire while it waits for you — it has no trailing newline. Matched case-insensitively
# against the tail of the DISPLAY text (ANSI already stripped, so a coloured prompt still hits).
_SECRET_PROMPT_RE = re.compile(
    r'(?:password|passphrase|passcode|pin)\s*(?:for\b[^:\r\n]*)?\s*:[ \t]*\Z',
    re.IGNORECASE)

import pyperclip
from prompt_toolkit.application import Application, get_app
from prompt_toolkit.buffer import Buffer
from prompt_toolkit.cursor_shapes import CursorShape
from prompt_toolkit.document import Document
from prompt_toolkit.filters import Condition
from prompt_toolkit.formatted_text.utils import fragment_list_to_text
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.keys import Keys
from prompt_toolkit.layout.containers import (ConditionalContainer, HSplit,
                                              VSplit, Window, WindowAlign)
from prompt_toolkit.layout.controls import BufferControl, FormattedTextControl
from prompt_toolkit.layout.dimension import Dimension as D
from prompt_toolkit.layout.layout import Layout
from prompt_toolkit.layout.processors import Processor, Transformation
from prompt_toolkit.layout.utils import explode_text_fragments

from .support.exceptions import SerialDeviceOpenError
from .support.message_dialog import MessageDialog
from .support.serial_manage import SerialManager
from .support.serial_simulator import random_text_generator
from .support.serial_simulator import respond as simulate_response
from .version import __version__

# ── Global state ──────────────────────────────────────────────────────────────
# Only the flags the BACKGROUND thread must read live here now; every user action
# is handled synchronously in the key bindings (see the GuiController.action_* /
# _call), so the old send/clear/history/help/etc. flags are gone.
UPDATE_LOG_FLAG = False
LOG_FILE_COUNTER = 0        # names successive OUTPUT_LOG*.txt exports
SEARCH_ACTIVE = False       # Ctrl+F — toggle search bar
SEARCH_STRING = ""          # current search pattern (from search_buffer)
CAPTURE = False             # Ctrl+W — capturing to Capture_log*.txt
CAPTURE_LOG = ""
CAPTURE_LOG_FILE_COUNTER = 0
TAB_PRESSED = False         # Tab — request autocomplete (serviced in the read thread)
PAUSE_LOGGING = False       # Ctrl+P — freeze the incoming log
TIMESTAMPS = False          # Ctrl+T — prefix each incoming line with HH:MM:SS
LINE_ENDING = "LF"          # Ctrl+N — what Enter appends: NONE | LF | CR | CRLF
LOCAL_ECHO = False          # Ctrl+O — echo sent commands into the log (for devices that don't)

# How often the SIMULATOR emits a line of idle "background chatter" (seconds). It used to fire every 0.2s
# (5 lines/sec) which, now that the simulator answers sent commands, immediately BURIED the reply and made the
# log race away — you couldn't read a reply, search, or scroll while testing without hardware. A slower
# heartbeat still proves live redraw and incoming-data handling while keeping the log readable; a command reply
# still shows promptly (it jumps the queue, independent of this interval).
_SIM_IDLE_INTERVAL = 1.2

# What each line-ending choice actually sends. A serial device often only acts on CR (or CR+LF),
# so sending a bare LF meant a typed command silently never executed on those devices.
_LINE_ENDINGS = ["NONE", "LF", "CR", "CRLF"]
_LINE_ENDING_BYTES = {"NONE": "", "LF": "\n", "CR": "\r", "CRLF": "\r\n"}

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
        ("class:title fg:red",    " [Ctrl+C] Send ^C  [Ctrl+D] ^D\n"),
        ("class:title fg:yellow", " [Ctrl+Y] Copy to Clipboard\n"),
        ("class:title fg:yellow", " [Ctrl+K] Clear Input\n"),
        ("class:title fg:cyan",   " [Ctrl+F] Search  [↵] Next  [Esc]\n"),
        ("class:title fg:green",  " [Ctrl+T] Timestamps\n"),
        ("class:title fg:green",  " [Ctrl+N] Line Ending\n"),
        ("class:title fg:green",  " [Ctrl+O] Local Echo\n"),
        ("class:title fg:green",  " [Ctrl+L] License\n"),
        ("class:title fg:green",  " [F1]     Help\n"),
        ("class:title fg:green",  " [Tab]    Autocomplete\n"),
        ("class:title fg:green",  " [\u2191 / \u2193]   History\n"),
        ("class:title fg:green",  " [PgUp/PgDn] Scroll  [Ctrl+E] Live\n"),
    ]


def get_options_width():
    """Sidebar width that actually fits the longest shortcut line.

    This was hard-coded to 32, which silently truncated the two longest entries
    mid-word ("... [Esc" and "... [Ctrl+E] Li"). Deriving it from the content means
    adding a new shortcut can never quietly clip the panel again.
    """
    longest = max(len(text.rstrip("\n")) for _, text in get_options_text())
    return max(24, longest + 1)


def get_sidebar_min_rows():
    """Terminal height below which the sidebar cannot be drawn.

    The layout's fixed rows are: 6 of app chrome (title, three rules, input, status)
    + 7 of panel chrome (two headers, four rules, footer) + one row per shortcut +
    at least one row of command history. Below that total prompt_toolkit cannot
    satisfy the layout and renders nothing but "Window too small...".
    """
    return 14 + len(get_options_text())


kb = KeyBindings()


# ── Condition filter for ConditionalContainer ─────────────────────────────────
@Condition
def _is_search_active():
    return SEARCH_ACTIVE


@Condition
def _sidebar_fits():
    """True when the terminal is big enough to draw the shortcut/history sidebar.

    The sidebar is a stack of FIXED-height windows, so on a short terminal the whole
    layout became unsatisfiable and prompt_toolkit replaced the ENTIRE UI with
    "Window too small..." — SoftCOM was unusable at 80x24, the default terminal size
    (and the size of most of the serial consoles it is pointed at). Dropping the
    sidebar keeps the part that matters — log, input, status — on any terminal.
    """
    try:
        size = get_app().output.get_size()
    except Exception:                      # no app/output yet (import time, tests)
        return True
    return (size.rows >= get_sidebar_min_rows()
            and size.columns >= get_options_width() + 40)


# ── Live search highlight ──────────────────────────────────────────────────────
_SEARCH_HIT_STYLE = "bg:#ffd54a #000000 bold"

# ── ANSI escape sequences from the DEVICE ─────────────────────────────────────────────
# A plain prompt_toolkit Buffer does not interpret escape codes, so anything the device
# sends arrives in the log as literal caret notation: a coloured shell prompt renders as
#   ^[[1;32mroot@target^[[0m:^[[1;34m/mnt^[[0m#
# That is the DEFAULT prompt on most Linux targets, and `ls`, `grep`, `systemctl` and
# `dmesg` all colourise when they believe they are on a TTY — so for a large share of the
# devices this terminal exists to talk to, every single line was unreadable.
#
# We strip rather than render colour. The log is an append-only scrollback Buffer, not a
# terminal emulator: cursor-movement sequences (\x1b[K erase-line, \x1b[2J clear-screen,
# \x1b[H home) have no meaningful effect on it, so honouring only the colour subset would
# still leave the rest as garbage. Stripping is the honest whole-class fix.
# The CAPTURE file deliberately keeps the raw bytes — a capture is evidence of what the
# device actually sent, escapes included.
_CSI = r'\x1b\[[0-?]*[ -/]*[@-~]'            # colour, cursor moves, erase — the common case
# String sequences: OSC (window title), DCS, SOS, PM, APC. They carry a BODY and end with
# BEL or ST, so they must be matched as a whole — and, critically, their introducers must be
# EXCLUDED from the two-character class below. `]` is 0x5D, which sits inside the textbook
# `[@-Z\\-_]` Fe range, so an UNTERMINATED "\x1b]0;title" was being eaten as a bare two-char
# escape and its body ("0;title") printed as visible junk. Caught by the prefix test.
_STR = r'\x1b[P\]X^_][^\x1b\x07]*(?:\x07|\x1b\\)'
_2CH = r'\x1b[@A-OQ-WYZ\\]'                  # true two-character escapes (ESC M, ESC c, …)
_ANSI_RE = re.compile(f'{_STR}|{_CSI}|{_2CH}')
# A trailing ESC that has not yet terminated is HELD for the next read (serial delivers
# whatever bytes have arrived, so "\x1b[1;32m" is routinely split mid-sequence). The cap
# stops a stray lone ESC — a device echoing a keypress, line noise — from black-holing
# every subsequent byte while it waits for a terminator that never comes.
_MAX_ESC_CARRY = 32
# What a still-incomplete sequence can look like, so a trailing ESC that can NEVER complete
# (line noise on a flaky cable is routine for this tool's users) is released at once instead
# of holding back the next _MAX_ESC_CARRY bytes of real output.
_ESC_PREFIX_RE = re.compile(r'\x1b(?:\[[0-?]*[ -/]*|[P\]X^_][^\x07]*)?\Z')


def strip_ansi(text: str, carry: str = "") -> tuple:
    """Remove ANSI escape sequences for DISPLAY. Pure/stateless so it is unit-testable.

    Returns ``(clean_text, new_carry)``. `carry` is any unterminated escape sequence held
    over from the previous read; prepend it, strip what is now complete, and hold whatever
    incomplete tail remains. Mirrors the `\\r` and incremental-UTF-8 carry discipline used
    by the rest of the read path — without it, a sequence split across two reads leaks its
    tail into the log as visible junk.
    """
    text = carry + text
    text = _ANSI_RE.sub('', text)
    new_carry = ""
    esc = text.rfind('\x1b')
    if esc != -1:
        tail = text[esc:]
        if len(tail) <= _MAX_ESC_CARRY and _ESC_PREFIX_RE.match(tail):
            # Still a plausible prefix of a sequence — hold it rather than print its guts.
            text, new_carry = text[:esc], tail
    # BEL is a device bell, not text; it renders as a stray "^G" in the log. (Any BEL that
    # was an OSC terminator is already gone with the OSC above.)
    return text.replace('\x07', ''), new_carry


# ── Tab autocomplete: reading the device's answer ─────────────────────────────────────
# Reject anything carrying a control character. A completion is a filename or a word;
# cursor moves and colour changes are the device redrawing, not something to type.
_CTRL_RE = re.compile(r'[\x00-\x1f\x7f]')


def extract_completion(typed: str, response: str):
    """What the input bar should read after the device answered a Tab, or None.

    Pure/stateless so it is unit-testable without a serial port or a running app.

    Shells answer a Tab one of two ways and this copes with both:

      1. **Bare suffix.** The match was unique, so only the missing characters come
         back: you typed ``ls /ho``, the device sends ``me/``.
      2. **Line redraw.** The device reprints its prompt and the whole completed
         line, usually behind a carriage return and an erase-to-end-of-line.

    An earlier version gave up on both and left the input bar untouched, reasoning
    that "the device echoes its PROMPT before the completion so the last line rarely
    starts with the bare typed prefix". That is true, and it is why this searches for
    the typed text *inside* the last line rather than anchoring at its start — the
    prompt sits in front of it, not in the way of it.

    INVARIANT, and the reason this can be trusted with the input bar: the result
    ALWAYS starts with `typed`. A misparse may decline to complete, but it can never
    shorten, truncate or rewrite what the user has already typed. Anything that would
    comes back as None instead.
    """
    if not typed or not response:
        return None
    clean, _ = strip_ansi(response)
    if not clean:
        return None

    # 2. Line redraw — the completed line is the tail of the last line printed.
    last = clean.replace('\r\n', '\n').replace('\r', '\n').split('\n')[-1]
    if typed in last:
        candidate = last[last.rfind(typed):]
        if candidate != typed and not _CTRL_RE.search(candidate):
            return candidate
        # Prefix came back unchanged: an ambiguous match, or nothing to add. The
        # candidate list is already in the log where the user can read it.
        return None

    # 1. Bare suffix — only when the reply is a single line of plain text.
    #
    # rstrip, NOT strip. Stripping BOTH ends let a candidate list sitting on a middle
    # line ("\r\n alpha  beta \r\n") come back looking like a bare suffix, and it got
    # appended straight onto the user's command. A reply that OPENS with a newline is
    # new output, never a continuation of the typed word — leaving that leading \r\n
    # in place means _CTRL_RE sees it and the completion is refused.
    suffix = clean.rstrip('\r\n')
    if suffix and not _CTRL_RE.search(suffix):
        return typed + suffix
    return None


def highlight_search(fragments, pattern):
    """Return `fragments` with every case-insensitive occurrence of `pattern` restyled
    as a search hit. Pure/stateless so it can be unit-tested without a running app.

    The old search "highlight" injected raw ANSI escape codes (\\x1b[1;33m…) straight
    into a plain prompt_toolkit Buffer, which does NOT interpret them — so it printed
    escape garbage into the log and highlighted nothing. Restyling the render fragments
    is the way prompt_toolkit actually colours text.
    """
    if not pattern:
        return fragments
    line = fragment_list_to_text(fragments)
    low, needle = line.lower(), pattern.lower()
    if needle not in low:
        return fragments
    exploded = explode_text_fragments(fragments)   # one (style, char) tuple per character
    n = len(needle)
    start = 0
    while True:
        hit = low.find(needle, start)
        if hit < 0:
            break
        for j in range(hit, min(hit + n, len(exploded))):
            exploded[j] = (_SEARCH_HIT_STYLE, exploded[j][1])
        start = hit + n
    return exploded


class SearchHighlighter(Processor):
    """Colours the Ctrl+F pattern wherever it appears in the output log, live as you type."""
    def apply_transformation(self, transformation_input):
        if SEARCH_ACTIVE and SEARCH_STRING:
            return Transformation(
                highlight_search(transformation_input.fragments, SEARCH_STRING))
        return Transformation(transformation_input.fragments)


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
                 parity='N', stopbits=1, bytesize=8, line_ending='LF', local_echo=False,
                 settings_store=None):
        global UPDATE_LOG_FLAG, _gui_instance, LINE_ENDING, LOCAL_ECHO

        self.simulator_mode = simulator_mode
        self.serial_dev_path = serial_device_path
        self.settings_store = settings_store   # SaveSettings, so a runtime line-ending change persists
        self._out_lock = Lock()                # serialises output-buffer writes (read thread + UI thread)
        self._capture_lock = Lock()            # serialises CAPTURE_LOG (read thread appends, UI thread flushes)
        LINE_ENDING = line_ending if line_ending in _LINE_ENDING_BYTES else "LF"
        LOCAL_ECHO = bool(local_echo)
        self.command_history: list = self._load_history()
        self.history_index: int = -1
        self._pending_input: str = ""   # the half-typed line, saved when you start browsing history with Up
        self.session_cwd: str = os.getcwd()
        self.follow_tail: bool = True     # False while the user has scrolled up to read history
        self._ts_line_start: bool = True  # are we at the start of a line? (for streaming timestamps)
        self._cr_pending: str = ""         # a trailing '\r' held across reads (so a split CRLF collapses)
        self._esc_pending: str = ""        # an unterminated ANSI escape held across reads (see strip_ansi)
        self._device_tail: str = ""        # last few hundred chars the device sent (secret-prompt detection)
        self._search_count_key = None     # cache for the status-bar match count (write-seq, pattern)
        self._search_count: int = 0
        self._output_seq = 0              # monotonic counter bumped on every output-buffer change; the
                                          # cache-invalidation token for the search count. len(text) was a
                                          # FALSE proxy: once the log hits _MAX_OUTPUT the front is trimmed as
                                          # the back grows, so len stays pinned at the cap while content
                                          # scrolls — freezing (and mis-stating) the match count on a busy log.
        # Simulator-mode replies to sent commands. send_command (UI thread) enqueues a fake-device response;
        # the read thread drains it and feeds it through the normal incoming path — so `-s` mode has a real
        # send→receive round-trip. Queue is thread-safe, so no extra lock is needed.
        self._sim_queue: "queue.Queue[str]" = queue.Queue()
        self._last_sim_chatter: float = 0.0   # when the simulator last emitted an idle heartbeat line

        # Always define ser_dev so the background read thread (which checks it every ~0.1s) can never
        # hit an AttributeError before it's assigned or while the object is being torn down — it stays
        # None in simulator mode and until a real port is actually opened below.
        self.ser_dev = None
        if not simulator_mode:
            self.ser_dev = SerialManager(serial_device_path, serial_device_baudrate,
                                         parity=parity, stopbits=stopbits, bytesize=bytesize)
            try:
                self.ser_dev.open_dev()
            except SerialDeviceOpenError:
                MessageDialog("Failed", f"Failed to open the {serial_device_path} device.")
                sys.exit(1)

        # ── Buffers ───────────────────────────────────────────────────────────
        # device output — read-only to the user (click-to-focus + typing used to
        # let you edit the captured log; a read-only buffer blocks that)
        self.output_buffer = Buffer(read_only=Condition(lambda: True))
        self.input_buffer = Buffer()      # command input (user types here)
        self.history_buffer = Buffer()    # left panel command history list
        self.search_buffer = Buffer()     # search pattern field

        # ── Windows ───────────────────────────────────────────────────────────
        # No lexer: the AutoIt lexer was arbitrarily syntax-colouring random words in the
        # serial stream (an "if"/"error"/number would get keyword colours), which is
        # misleading for raw device output. And no focus_on_click: the output is read-only,
        # so a click used to steal keyboard focus off the input bar and typing then went
        # nowhere. It keeps a live Ctrl+F highlight instead.
        self.output_window = Window(
            BufferControl(buffer=self.output_buffer,
                          input_processors=[SearchHighlighter()]),
            wrap_lines=True,
            style='class:border',
        )
        self.input_window = Window(
            BufferControl(buffer=self.input_buffer),
            height=1,
        )
        self.history_window = Window(
            BufferControl(buffer=self.history_buffer),
            # preferred=1 so the shortcut panel above gets its full height FIRST and
            # the recent-commands list only takes what is genuinely left over. With a
            # larger preference this list held its size and silently pushed the last
            # shortcuts (F1 Help, Tab, History, PgUp) off the panel on a 31-34 row
            # terminal — the user never learned those keys existed. It still expands
            # to fill a tall terminal because max is unbounded.
            height=D(min=1, preferred=1),
        )
        self.search_window = Window(
            BufferControl(buffer=self.search_buffer),
            height=1,
        )
        # FormattedTextControl over a callable, not a Buffer: it re-evaluates on every
        # render, so the badges follow the real state with nothing to keep in sync.
        self.status_window = Window(
            FormattedTextControl(self.status_segments),
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
            # Shrinkable, not fixed: a hard height here made the whole layout
            # unsatisfiable on a short terminal instead of just showing fewer rows.
            Window(content=FormattedTextControl(get_options_text()),
                   height=D(min=1,
                            preferred=len(get_options_text()),
                            max=len(get_options_text())),
                   align=WindowAlign.LEFT),
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
        ], width=get_options_width())

        # ── Full layout ───────────────────────────────────────────────────────
        self.root_container = HSplit([
            # Title bar
            Window(
                height=1,
                content=FormattedTextControl(
                    get_titlebar_text(self._title_text(serial_device_path, serial_device_baudrate,
                                                       bytesize, parity, stopbits))),
                align=WindowAlign.CENTER,
            ),
            Window(height=1, char="─", style="class:line"),
            # Main body: left panel + output log
            VSplit([
                ConditionalContainer(left_panel, filter=_sidebar_fits),
                ConditionalContainer(
                    Window(width=1, char="│", style="class:line"),
                    filter=_sidebar_fits),
                HSplit([
                    Window(height=1,
                           content=FormattedTextControl(self.log_header_segments),
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
        self._refresh_history_panel()     # show prior-session history in the panel at startup

        self.application = Application(
            layout=Layout(self.root_container, focused_element=self.input_window),
            key_bindings=kb,
            # Mouse support OFF on purpose: capturing the mouse disables the terminal emulator's own
            # click-drag text SELECTION, which is how you'd normally highlight and copy a snippet out of
            # the log. The app has no clickable widgets and keeps the input bar focused (no click-to-focus),
            # so it gained nothing from mouse capture and only cost you selection. Everything is keyboard-
            # driven (PageUp/PageDown/Ctrl+E to scroll, Ctrl+Y to copy the whole log).
            mouse_support=False,
            full_screen=True,
            cursor=CursorShape.BLINKING_BEAM,
            enable_page_navigation_bindings=True,
            # The background read thread mutates the buffers; without a refresh
            # interval prompt_toolkit only redraws on a keypress, so incoming
            # serial data (and the status bar) would sit invisible until you
            # touched the keyboard. Redraw ~10×/s so the log is actually live.
            refresh_interval=0.1,
        )
        # How long prompt_toolkit waits after a bare Esc to see whether it is really the start
        # of an escape SEQUENCE (an arrow key, a Meta combo). The default is 0.5 s, which made
        # Esc feel broken: after Ctrl+F, pressing Esc left the search bar open and focused for
        # half a second, and anything typed in that window landed in the search field. 50 ms is
        # far longer than the microseconds a real terminal takes to deliver the rest of a
        # sequence, and short enough to feel instant.
        self.application.ttimeoutlen = 0.05

        _gui_instance = self
        self.read_thread = Thread(target=self.periodic_update, daemon=True)
        UPDATE_LOG_FLAG = True
        self.read_thread.start()
        try:
            self.application.run()
        finally:
            # EVERY exit path lands here — Ctrl+Q, a device disconnect, Ctrl+C, or an
            # unhandled error inside prompt_toolkit. Cleanup used to hang off __del__ alone,
            # which CPython is free to run late (or, at interpreter shutdown, not at all), so
            # the serial port could stay held open after SoftCOM had visibly quit and the next
            # run — or another program — failed with "device busy". A running capture could
            # likewise be lost. Do it deterministically here instead.
            self.shutdown()

    def shutdown(self):
        """Stop the reader thread, flush a running capture, and release the serial port.

        Safe to call more than once (__del__ still calls it as a backstop)."""
        global UPDATE_LOG_FLAG          # pylint: disable=global-statement
        UPDATE_LOG_FLAG = False
        thread = getattr(self, 'read_thread', None)
        if thread is not None and thread.is_alive():
            # The loop naps ≤50 ms between polls, so it observes the flag almost at once;
            # cap the wait so a wedged read can never stop SoftCOM from exiting.
            thread.join(timeout=1.0)
        if CAPTURE and CAPTURE_LOG:
            try:
                self._flush_capture()
            except Exception:            # pylint: disable=broad-except
                pass
        dev = getattr(self, 'ser_dev', None)
        if not getattr(self, 'simulator_mode', False) and dev is not None:
            try:
                dev.close_dev()
            except Exception:            # pylint: disable=broad-except
                pass

    def __del__(self):
        try:
            self.shutdown()
        except Exception:                # pylint: disable=broad-except
            pass                         # interpreter shutdown: globals may already be gone

    def _port_summary(self) -> str:
        """Device + framing, e.g. "/dev/ttyUSB0  115200 8N1".

        Stashed by `_title_text` at construction rather than recomputed, because the
        framing arguments are only in scope there and the log header needs the same
        string. Falls back to the raw path if the title was never built (tests that
        construct pieces in isolation)."""
        return getattr(self, "_port_desc", "") or ""

    def _title_text(self, path, baud, bytesize, parity, stopbits):
        """Header text. The old title showed only device + baud; add the FRAMING (data-bits/parity/
        stop-bits as the standard 8N1 shorthand) so the whole port config is visible at a glance."""
        if self.simulator_mode:
            self._port_desc = f"{path} (simulator)"
            return self._port_desc
        framing = f"{bytesize}{parity}{stopbits}"     # e.g. 8N1 = 8 data bits, No parity, 1 stop bit
        self._port_desc = f"{path}  {baud} {framing}"
        return self._port_desc

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
        """Persist command history to ~/.softcom_history, readable by the OWNER ONLY (0600).

        This is a serial TERMINAL: logging into a device means typing a username at its `login:`
        prompt and a password at its `Password:` prompt, pressing Enter after each — so both go
        through action_send and both land in this file. Written with a plain open() it was created
        at the default umask (0644 here), i.e. every other account on the machine could read the
        device passwords. Every shell keeps its history 0600 for exactly this reason.

        os.open with mode 0o600 sets the permissions ATOMICALLY at creation, so the file is never
        briefly world-readable the way open()+chmod would leave it. An existing file keeps its old
        mode on rewrite, so repair that too — this file already existed at 0644 for current users.
        """
        try:
            entries = self.command_history[-_MAX_HISTORY:]
            fd = os.open(_HISTORY_FILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, 'w', encoding='utf-8') as f:
                f.write('\n'.join(entries) + '\n')
            try:
                if stat.S_IMODE(os.stat(_HISTORY_FILE).st_mode) != 0o600:
                    os.chmod(_HISTORY_FILE, 0o600)   # tighten a file created by an older version
            except OSError:
                pass
        except OSError:
            pass

    # ── Callbacks ─────────────────────────────────────────────────────────────

    def _on_search_changed(self, _):
        """Keep SEARCH_STRING in sync with search_buffer."""
        global SEARCH_STRING
        SEARCH_STRING = self.search_buffer.text

    # ── Status bar ────────────────────────────────────────────────────────────

    # Badge palette. Inline fg:/bg: rather than a Style dict, matching the rest of
    # this file. Meaning is carried by COLOUR FAMILY, consistently: green = healthy,
    # red = recording or disconnected, amber = something is being held back from you
    # (paused, scrolled away from live), blue = a transient mode you are inside.
    _OK    = "bg:#0d4a2b fg:#7ef0a8 bold"
    _BAD   = "bg:#5a1111 fg:#ff9a9a bold"
    _WARN  = "bg:#5a4a00 fg:#ffd866 bold"
    _MODE  = "bg:#0d3a5a fg:#8ed6ff bold"
    _DIM   = "fg:#6b7280"
    _HINT  = "fg:#9aa0b0"

    def _search_hits(self) -> int:
        """Live match count, cached against the output write-seq.

        This is rebuilt on every background loop (~50 Hz) and lower()+count() over a
        400 KB log each time made searching a big buffer sluggish. Recompute only when
        the OUTPUT actually changed or the pattern did — correct even at the buffer cap,
        where len(text) would sit frozen while the content keeps scrolling.
        """
        key = (self._output_seq, SEARCH_STRING)
        if key != self._search_count_key:
            self._search_count_key = key
            self._search_count = self.output_buffer.text.lower().count(SEARCH_STRING.lower())
        return self._search_count

    def status_segments(self) -> list:
        """The status bar as (style, text) fragments.

        The bar used to be one run of pipe-separated monochrome text:

            | Device: OPEN | Capture: ON | Paused | EOL: LF | Echo |

        Everything had equal weight, so "the port is closed" and "line endings are LF"
        looked exactly alike and you had to READ the line to learn anything from it.
        These are badges instead: colour carries the meaning, and a state that is not
        active is not drawn at all, so anything visible is something true right now.

        SINGLE SOURCE OF TRUTH. `get_status_text()` joins these, so the plain text the
        tests assert on cannot drift from what is actually painted on screen.
        """
        seg = []
        if self.simulator_mode:
            seg.append((self._WARN, " ● SIM "))
        else:
            is_open = self.ser_dev is not None and self.ser_dev.is_dev_open()
            seg.append((self._OK, " ● OPEN ") if is_open else (self._BAD, " ● CLOSED "))

        # REC / PAUSED / SCROLLBACK deliberately do NOT appear here. They live in the
        # log header instead, one row above the output, because that is where you are
        # looking when they matter. Rendering both bars showed them twice, identically,
        # which is noise rather than emphasis — each bar gets one job.
        if SEARCH_ACTIVE and SEARCH_STRING:
            hits = self._search_hits()
            seg += [("", " "), (self._MODE, f' Find "{SEARCH_STRING}" '),
                    (self._HINT, f" ({hits} match{'' if hits == 1 else 'es'})")]

        # Persistent port config last and dimmed: it is reference, not news.
        tail = f"  EOL {LINE_ENDING}"
        if LOCAL_ECHO:
            tail += " · echo"
        if TIMESTAMPS:
            tail += " · stamps"
        seg.append((self._DIM, tail))
        return seg

    def get_status_text(self) -> str:
        """Plain-text status. Derived from `status_segments()` so the two can never
        disagree — the tests read this, the screen draws those."""
        return "".join(t for _style, t in self.status_segments())

    def log_header_segments(self) -> list:
        """The header row above the log.

        It used to read " Output Log" — a label for the one thing on screen that needs
        no label, costing a row on a 24-line terminal.

        It carries live state instead, and deliberately NOT the device path: the title
        bar one row above already shows that, and printing it twice was the first thing
        that looked wrong when this was rendered. Connection state plus whatever is
        currently being held back from you (recording, paused, scrolled away) sits
        directly above the log, which is where the eyes already are — the status bar at
        the far bottom keeps the full detail.
        """
        if self.simulator_mode:
            head = [(self._WARN, " ● SIMULATOR ")]
        else:
            is_open = self.ser_dev is not None and self.ser_dev.is_dev_open()
            head = [(self._OK, " ● OPEN ") if is_open else (self._BAD, " ● CLOSED ")]
        if CAPTURE:
            head += [("", " "), (self._BAD, " ● REC ")]
        if PAUSE_LOGGING:
            head += [("", " "), (self._WARN, " ⏸ PAUSED ")]
        if not self.follow_tail:
            head += [("", " "), (self._WARN, " ↑ SCROLLBACK "),
                     (self._HINT, " Ctrl+E → live")]
        return head

    # ── Serial I/O ────────────────────────────────────────────────────────────

    _HISTORY_PANEL_MAX = 200      # lines kept in the left "Recent Commands" panel

    def send_command(self, command: str):
        """Send a command to the device (or, in simulator mode, queue a fake-device reply to it)."""
        if not self.simulator_mode:
            self.ser_dev.exe_command(command)
            return
        # Simulator: answer the command so `-s` mode has a real round-trip (the read thread emits it).
        reply = simulate_response(command)
        if reply:
            self._sim_queue.put(reply)

    def _refresh_history_panel(self):
        """Rebuild the left 'Recent Commands' panel from command_history (newest at the bottom).
        The panel used to start EMPTY (ignoring the loaded ~/.softcom_history) and grow without
        bound as every sent line was appended; now it mirrors the same bounded list the Up-arrow
        recalls, so it shows prior-session history at startup and never grows unbounded."""
        entries = self.command_history[-self._HISTORY_PANEL_MAX:]
        text = ('\n'.join(entries) + '\n') if entries else ''
        # cursor at the end so the view scrolls to keep the most-recent commands visible
        self.history_buffer.set_document(Document(text, len(text)))

    # ── User actions ──────────────────────────────────────────────────────────
    # These run SYNCHRONOUSLY in the UI thread straight from the key bindings.
    # They used to be deferred through module-level flags and only serviced once
    # per iteration of the background read loop — which sits behind a blocking
    # serial read — so every keystroke felt laggy. Acting on them here makes the
    # UI respond instantly; only the serial *read* still lives in the thread.

    def device_awaiting_secret(self) -> bool:
        """True when the last thing the device sent was a password/passphrase prompt.

        Used to keep the reply OUT of the command history, the on-disk history file and the
        'Recent Commands' panel. Getting this wrong is not symmetric, which is why it is a
        heuristic and that is fine: a false POSITIVE loses one line of history (an annoyance),
        a false NEGATIVE writes a device password to disk. It fails toward the safe side.
        """
        return bool(_SECRET_PROMPT_RE.search(self._device_tail))

    def _write_succeeded(self) -> bool:
        """Did the bytes just handed to send_command actually reach the port?

        The serial layer swallows a failed write and only flips is_dev_open() to False (that flag is
        what the disconnect watchdog polls), so the ONLY way to tell whether a send worked is to ask
        the port whether it is still alive immediately afterwards. Deliberately not a return value
        from send_command: several tests replace send_command with a plain recorder, and a contract
        change there would fail open — the unsafe direction for something that gates history.

        Simulator mode always succeeds; so does a controller with no port yet (nothing to lose)."""
        if self.simulator_mode or self.ser_dev is None:
            return True
        return bool(self.ser_dev.is_dev_open())

    def action_send(self):
        """Enter — send the input line to the device and record it in history.

        A line typed at a device's password prompt is sent but NEVER recorded — see
        device_awaiting_secret. A line the port refused is not recorded either — see
        _write_succeeded."""
        self.follow_tail = True     # snap back to live so you see the reply
        cmd = self.input_buffer.text
        secret = self.device_awaiting_secret()
        # Append the configured line ending (Ctrl+N cycles it). A device that expects CR would
        # ignore a command terminated with a bare LF, so this is a per-device choice, not a constant.
        self.send_command(cmd + _LINE_ENDING_BYTES.get(LINE_ENDING, "\n"))
        if not self._write_succeeded():
            # The write raised — the adapter was unplugged between the last read and this Enter.
            # The old code carried on regardless: it cleared the input bar and appended the line to
            # history, so the command VANISHED while the history claimed it had been sent. On a
            # flaky USB-serial adapter that is the difference between retyping one line and
            # believing a device was told to reboot when it never heard anything.
            #
            # Keep the text so it can be retried, keep it OUT of history, and say so. Mask it if the
            # device was asking for a password — a failed send must not leak what the record would
            # not have kept anyway.
            self._append_to_output(
                f"\n─── NOT SENT (port closed): {'*' * len(cmd) if secret else cmd} ───\n")
            return
        # Show what you sent when the device won't. A real device usually echoes what it received,
        # so echoing locally would double it up — hence local echo is OFF by default and a per-device
        # toggle (Ctrl+O). The simulator never echoes, so it always shows the sent line.
        if (self.simulator_mode or LOCAL_ECHO) and cmd.strip():
            # Echo the secret as asterisks, never in clear: local echo is a per-device setting that
            # somebody leaves ON, and the log it writes to gets saved (Ctrl+S) and captured (Ctrl+W).
            self._append_to_output("> " + ("*" * len(cmd) if secret else cmd) + "\n")
        stripped = "" if secret else cmd.strip()
        # Record it, but skip a consecutive duplicate so re-running the same command (very common
        # over Up-arrow) doesn't fill the history with repeats.
        if stripped and (not self.command_history or self.command_history[-1] != stripped):
            self.command_history.append(stripped)
            self._save_history()
            self._refresh_history_panel()
        self.history_index = -1
        self._pending_input = ""
        self.input_buffer.text = ""
        self.input_buffer.cursor_position = 0
        # The prompt has been answered, so it is no longer what the device is "currently asking".
        # Without this the tail still ends in "Password:" until the device replies, and a second
        # Enter pressed in that window would be suppressed too.
        self._device_tail = ""

    def action_clear_log(self):
        """Ctrl+X — clear the output log."""
        self.follow_tail = True
        self._clear_output()

    @staticmethod
    def _next_free_filename(directory: str, prefix: str, ext: str, start: int = 0):
        """Return (filename, index) for the first prefix{n}{ext} that does NOT already exist on disk.

        The old code named files off a module counter that resets to 0 every launch, so the first
        save/capture of a new session silently OVERWROTE OUTPUT_LOG0.txt / Capture_log0.txt from a
        previous session. Skipping existing files means a save never clobbers an earlier one.
        """
        n = max(0, start)
        while os.path.exists(os.path.join(directory, f'{prefix}{n}{ext}')):
            n += 1
        return f'{prefix}{n}{ext}', n

    def action_save_log(self):
        """Ctrl+S — write the output log to the working directory."""
        global LOG_FILE_COUNTER  # pylint: disable=global-statement
        filename, idx = self._next_free_filename(self.session_cwd, 'OUTPUT_LOG', '.txt', LOG_FILE_COUNTER)
        try:
            with open(os.path.join(self.session_cwd, filename), 'w', encoding='UTF-8') as f:
                f.write(self.output_buffer.text)
            LOG_FILE_COUNTER = idx + 1
            self._append_to_output(f"\n─── Log saved → {filename} ───\n")
        except OSError as err:
            self._append_to_output(f"\n─── Log save failed: {err} ───\n")

    def action_copy_log(self):
        """Ctrl+Y — copy the output log to the clipboard."""
        try:
            pyperclip.copy(self.output_buffer.text)
        except pyperclip.PyperclipException:
            self._append_to_output("\n─── Clipboard unavailable on this system ───\n")

    def _send_ctrl(self, code: int, label: str):
        """Send a raw control byte to the device (no line ending), and — like a sent command — only
        echo the marker locally when local echo is on, since the device normally echoes it back."""
        self.follow_tail = True
        self.send_command(chr(code))
        if self.simulator_mode or LOCAL_ECHO:
            self._append_to_output(label + "\n")

    def action_send_interrupt(self):
        """Ctrl+C — send an interrupt (^C, 0x03) to the device to STOP a running remote command.
        For a serial terminal this matters far more than copy-to-clipboard (which moved to Ctrl+Y):
        without it you could start `ping` on the device and have no way to stop it."""
        self._send_ctrl(3, "^C")

    def action_send_eof(self):
        """Ctrl+D — send an end-of-file (^D, 0x04) to the device (log out / end input)."""
        self._send_ctrl(4, "^D")

    def action_clear_input(self):
        """Ctrl+K — clear the input bar."""
        self.input_buffer.text = ""
        self.input_buffer.cursor_position = 0
        self.history_index = -1

    def action_cycle_line_ending(self):
        """Ctrl+N — cycle what Enter appends (None → LF → CR → CRLF) and persist the choice, so a
        device that only responds to CR/CRLF can be driven without editing settings by hand."""
        global LINE_ENDING  # pylint: disable=global-statement
        idx = _LINE_ENDINGS.index(LINE_ENDING) if LINE_ENDING in _LINE_ENDINGS else 1
        LINE_ENDING = _LINE_ENDINGS[(idx + 1) % len(_LINE_ENDINGS)]
        if self.settings_store is not None:
            try:
                self.settings_store.line_ending = LINE_ENDING
                self.settings_store.save_file()
            except OSError:
                pass
        self._append_to_output(f"\n─── Line ending → {LINE_ENDING} ───\n")

    def action_toggle_local_echo(self):
        """Ctrl+O — echo the commands you SEND into the log, for a device that doesn't echo them
        back itself (otherwise a sent line just vanishes). Off by default so an echoing device
        doesn't show every command twice. Persisted per device."""
        global LOCAL_ECHO  # pylint: disable=global-statement
        LOCAL_ECHO = not LOCAL_ECHO
        if self.settings_store is not None:
            try:
                self.settings_store.local_echo = LOCAL_ECHO
                self.settings_store.save_file()
            except OSError:
                pass
        self._append_to_output(f"\n─── Local echo {'ON' if LOCAL_ECHO else 'OFF'} ───\n")

    def action_show_license(self):
        """Ctrl+L — print the LICENSE into the log."""
        self._show_bundled_file('LICENSE')

    def action_show_help(self):
        """F1 — print the HELP file into the log."""
        self._show_bundled_file('HELP')

    def _show_bundled_file(self, name: str):
        # HELP and LICENSE live at the project root, one level ABOVE this package
        # directory — the old code only looked next to gui_controller.py, so F1 and
        # Ctrl+L always reported "not found". Search both.
        here = os.path.dirname(os.path.realpath(__file__))
        for candidate in (os.path.join(here, name),
                          os.path.join(os.path.dirname(here), name)):
            try:
                with open(candidate, encoding='UTF-8') as f:
                    self._append_to_output("\n" + f.read() + "\n")
                    return
            except FileNotFoundError:
                continue
        self._append_to_output(f"\n[{name} file not found]\n")

    def action_history_up(self):
        """Up — recall an older command into the input bar."""
        if self.command_history:
            # Starting to browse (index == -1) — stash the half-typed line so Down can bring it back,
            # instead of losing it the way the old code did (like a real shell's history).
            if self.history_index == -1:
                self._pending_input = self.input_buffer.text
            self.history_index = min(self.history_index + 1, len(self.command_history) - 1)
            cmd = self.command_history[-(self.history_index + 1)]
            self.input_buffer.text = cmd
            self.input_buffer.cursor_position = len(cmd)

    def action_history_down(self):
        """Down — walk back toward the newest command / the line you were typing."""
        if self.history_index > 0:
            self.history_index -= 1
            cmd = self.command_history[-(self.history_index + 1)]
            self.input_buffer.text = cmd
            self.input_buffer.cursor_position = len(cmd)
        elif self.history_index == 0:
            # Back below the newest entry — restore the half-typed line you had before browsing.
            self.history_index = -1
            self.input_buffer.text = self._pending_input
            self.input_buffer.cursor_position = len(self._pending_input)

    _MAX_OUTPUT = 400_000    # keep the log bounded; an unbounded buffer slows the whole UI

    def _write_output(self, new_text: str):
        """Replace the read-only output buffer, capped. Pin the cursor to the end so the view
        follows new data — UNLESS the user has scrolled up (follow_tail False), in which case
        keep their position so incoming data doesn't yank them back to the bottom."""
        self._output_seq += 1                  # mark the buffer changed (search-count cache token)
        trimmed = 0                            # chars dropped from the FRONT by the cap
        if len(new_text) > self._MAX_OUTPUT:
            over = len(new_text) - self._MAX_OUTPUT
            new_text = new_text[over:]
            trimmed = over
            nl = new_text.find("\n")           # trim to a clean line boundary if one is near
            if 0 <= nl < 4000:
                new_text = new_text[nl + 1:]
                trimmed += nl + 1
        if self.follow_tail:
            cursor = len(new_text)
        else:
            # Keep the scrolled-up reader on the SAME text: dropping `trimmed` chars off the
            # front shifts every position left by that much, so shift their cursor too (the old
            # code left it at a stale absolute index, jumping the view whenever the cap kicked in).
            cursor = max(0, min(self.output_buffer.cursor_position - trimmed, len(new_text)))
        self._apply_document(Document(new_text, cursor))

    def _apply_document(self, doc: Document):
        """Install a new output Document, on the UI thread.

        `Buffer.set_document` writes text and cursor as two SEPARATE steps, and the renderer
        (on the UI thread) reads them as two separate reads to rebuild a Document — which
        asserts cursor_position <= len(text). With the reader thread writing directly, the
        renderer could observe the NEW shorter text next to the OLD longer cursor and blow up
        with `AssertionError: cursor_position=172, len_text=157`, splattering a traceback over
        the full-screen UI. The window is wide open once the 400 000-char cap starts trimming
        from the front, because then the buffer keeps SHRINKING under the renderer.

        And an exception raised out of a prompt_toolkit callback does not merely crash: the key
        processor's coroutine dies, so every later keypress — Ctrl+Q included — is ignored and
        the app hangs until it is killed from another terminal.

        So: hand the mutation to the event loop when we're on the reader thread. When there is
        no loop yet (startup) or we're already on the main thread (the UI thread, and the
        tests), apply it directly so behaviour stays synchronous and observable.
        """
        loop = getattr(self.application, 'loop', None) if getattr(
            self, 'application', None) is not None else None
        if loop is None or threading.current_thread() is threading.main_thread():
            self.output_buffer.set_document(doc, bypass_readonly=True)
            return
        try:
            loop.call_soon_threadsafe(
                lambda: self.output_buffer.set_document(doc, bypass_readonly=True))
        except RuntimeError:
            pass            # loop already closed (we're quitting) — dropping a repaint is fine

    def _set_input_text(self, text: str) -> None:
        """Replace the input bar contents from ANY thread.

        The Tab handler runs on the reader thread (it has to — it waits on the serial
        port, and blocking the UI thread for that would freeze the window). Writing
        `input_buffer.text` from there is exactly the unsafe cross-thread mutation the
        previous implementation backed away from, since the UI thread edits the same
        buffer on every keystroke.

        Same escape hatch as `_set_output_document` above: hand the mutation to the
        event loop when we're off the main thread, apply it directly when we're on it
        (startup, and the tests) so behaviour stays synchronous and observable.
        """
        def apply():
            self.input_buffer.text = text
            self.input_buffer.cursor_position = len(text)

        loop = getattr(self.application, 'loop', None) if getattr(
            self, 'application', None) is not None else None
        if loop is None or threading.current_thread() is threading.main_thread():
            apply()
            return
        try:
            loop.call_soon_threadsafe(apply)
        except RuntimeError:
            pass            # loop already closed (we're quitting)

    # ── Scrollback (PageUp/PageDown/Ctrl+E) ────────────────────────────────────

    def _page_rows(self) -> int:
        """How many rows one PageUp/PageDown should move: an actual screenful.

        This was hard-coded to 8. Worse, moving only the CURSOR does not move the VIEW while
        the cursor is still inside the viewport, so on a normal-sized window the first few
        PageUp presses did NOTHING VISIBLE — measured on a 32-row window: presses 1-3 left
        vertical_scroll unchanged at 269. The user pressed PageUp three times, the status bar
        said "Scrolled", and the text never budged.
        """
        info = getattr(self.output_window, 'render_info', None)
        height = getattr(info, 'window_height', 0) if info is not None else 0
        return max(1, height - 1) if height else 8      # keep one line of context

    def _scroll_by(self, rows: int):
        doc = self.output_buffer.document
        new_row = max(0, min(doc.line_count - 1, doc.cursor_position_row + rows))
        self.output_buffer.cursor_position = doc.translate_row_col_to_index(new_row, 0)
        # Drive the viewport explicitly as well; the cursor move alone is not enough (above).
        info = getattr(self.output_window, 'render_info', None)
        if info is not None:
            height = max(1, getattr(info, 'window_height', 1))
            top = new_row if rows < 0 else max(0, new_row - height + 1)
            self.output_window.vertical_scroll = max(0, min(top, max(0, doc.line_count - 1)))

    def action_scroll_up(self):
        """PageUp — freeze the log and scroll back through history."""
        self.follow_tail = False
        self._scroll_by(-self._page_rows())

    def action_scroll_down(self):
        """PageDown — scroll forward; snap back to live at the bottom."""
        self._scroll_by(self._page_rows())
        doc = self.output_buffer.document
        if doc.cursor_position_row >= doc.line_count - 1:
            self.action_scroll_end()

    def action_scroll_end(self):
        """Ctrl+E — jump back to the live bottom and resume following."""
        self.follow_tail = True
        self.output_buffer.cursor_position = len(self.output_buffer.text)

    def action_search_next(self):
        """Enter (while the search bar is open) — jump the log to the next match of the search
        string, wrapping around. Search used to only highlight matches that were already on
        screen; this makes it a real find that can reach a match scrolled out of view."""
        needle = SEARCH_STRING
        if not needle:
            return
        text = self.output_buffer.text
        low, nl = text.lower(), needle.lower()
        idx = low.find(nl, self.output_buffer.cursor_position + 1)
        if idx < 0:
            idx = low.find(nl, 0)          # wrap to the top
        if idx >= 0:
            self.follow_tail = False       # hold the view on the match; don't snap back to live
            self.output_buffer.cursor_position = idx

    def _clear_output(self):
        with self._out_lock:
            self._output_seq += 1
            self.output_buffer.set_document(Document("", 0), bypass_readonly=True)
        self._ts_line_start = True     # an empty log is at the start of a line

    def _append_to_output(self, text: str):
        """Append text to the output log and scroll to bottom. Raw — timestamps are applied to
        incoming DEVICE data in `_process_incoming`, not here, so the app's own status messages
        ('Log saved', 'Capture started', …) are never stamped.

        The read-modify-write is held under a lock: this is called from BOTH the background read
        thread (incoming data) and the UI thread (send echo, capture/log messages), so without it a
        message written at the same instant as an incoming chunk could be silently lost."""
        if not text:
            return
        with self._out_lock:
            self._write_output(self.output_buffer.text + text)
        # Maintain the timestamp line-start tracker HERE, the one funnel every append passes through — so it
        # stays correct no matter what wrote (timestamped device data, un-timestamped data, a local echo, or an
        # app message like "Log saved"). Keeping it only inside _apply_timestamps left it stale after an app
        # message/echo (which bypass timestamping), so a device line arriving after one lost its stamp.
        self._ts_line_start = text.endswith('\n')

    def _apply_timestamps(self, text: str) -> str:
        """Prefix an [HH:MM:SS] stamp at the START of each line, tracking line-start state ACROSS
        calls, so a line that arrives in pieces (the normal case for a serial stream) gets exactly
        one stamp at its real start.

        Split ONLY on '\\n', never `str.splitlines`: splitlines also breaks on \\v, \\f (a form-feed,
        which plenty of instruments emit to clear the screen), \\x1c-\\x1e, \\x85, \\u2028 and \\u2029,
        so it would inject a stray timestamp mid-line at any of those bytes AND corrupt the line-start
        tracking (a fragment ending in \\f isn't a real new line). Those characters must stay INLINE."""
        ts = time.strftime("[%H:%M:%S] ")
        out = []
        parts = text.split('\n')
        for i, part in enumerate(parts):
            if i > 0:                              # the newline that terminates the previous line
                if self._ts_line_start:            # previous line was empty → still stamp the blank line
                    out.append(ts)
                out.append('\n')
                self._ts_line_start = True
            if part:                               # content on this line
                if self._ts_line_start:
                    out.append(ts)
                    self._ts_line_start = False
                out.append(part)
        return "".join(out)

    def _process_incoming(self, incoming: str, display: bool = True):
        """Clean incoming device data, feed the capture, and (when `display`) append it to the log.

        `display` is False while the on-screen log is PAUSED (Ctrl+P): the bytes are still read, decoded,
        CR-normalised and CAPTURED to file — pausing the DISPLAY must not lose data or stop a running
        capture — they're just not shown until you resume."""
        global CAPTURE_LOG

        # Normalise line endings for display. The old code DELETED every '\r', which is fine for a
        # CRLF device (\r\n -> \n) but concatenates ALL output onto one line for a CR-only device (many
        # legacy/embedded consoles) and for '\r' progress redraws ("50%\r75%\r100%"). Instead: CRLF -> one
        # newline, and a lone CR -> a newline (so CR-only lines break and progress redraws stack readably).
        # A trailing '\r' is held across reads so a CRLF that splits between two reads still collapses to
        # a single newline (matching the incremental UTF-8 decoder's carry discipline).
        incoming = self._cr_pending + incoming
        self._cr_pending = ""
        if incoming.endswith('\r'):
            self._cr_pending = '\r'
            incoming = incoming[:-1]
        clean = (incoming
                 .replace('\r\n', '\n')
                 .replace('\r', '\n')
                 .replace('\b', ''))
        # NOTE: we deliberately do NOT strip the literal two-char text "^M". Every real carriage
        # return (0x0D) is already turned into a newline above, so a remaining "^M" is genuine device
        # output — e.g. `cat -v`, `stty`, or vim showing CR line-endings in caret notation — and
        # deleting it silently corrupted that text.

        # ── Capture ───────────────────────────────────────────────────────
        # Just accumulate while capturing; STARTING and STOPPING (which writes the
        # file) are handled the instant Ctrl+W is pressed — see action_toggle_capture.
        # Doing the save here meant a stopped capture never hit disk until the next
        # byte arrived, so stopping on a quiet device silently lost the whole capture.
        if CAPTURE:
            # Held under the capture lock: this runs on the READ thread while the UI thread may be
            # flushing/resetting CAPTURE_LOG on Ctrl+W. Without it, a byte arriving at the instant you
            # stop could resurrect the just-flushed content into the NEXT capture file.
            with self._capture_lock:
                CAPTURE_LOG += clean     # capture stays RAW device data (never timestamped)

        # ── Strip the device's ANSI escape sequences for DISPLAY ──────────
        # Done AFTER the capture above on purpose: the capture file keeps the raw bytes
        # (it is evidence of what the device sent), while the on-screen log gets readable
        # text instead of "^[[1;32mroot@target^[[0m:". See strip_ansi for why we strip
        # rather than colourise. The carry runs even when NOT displaying (paused), so a
        # sequence split across the pause boundary can't leak its tail on resume.
        shown, self._esc_pending = strip_ansi(clean, self._esc_pending)

        # Remember the tail of what the device has sent so action_send can tell whether the device
        # is sitting on a "Password:" prompt right now. Updated even while the display is PAUSED —
        # the device is still asking, and the secret must not be recorded just because Ctrl+P is on.
        # 400 chars is far more than any prompt needs and keeps this O(1) per read.
        if shown:
            self._device_tail = (self._device_tail + shown)[-400:]

        # A plain prompt_toolkit Buffer does NOT interpret ANSI escape codes, so the
        # old "\x1b[1;33m…" highlight wrote literal escape garbage into the log. The
        # active search pattern is surfaced in the status bar instead.
        if display and shown:
            # The line-start tracker is maintained in _append_to_output (the one funnel), so it stays correct
            # whether timestamps are on or off here — and across app messages / echo too.
            self._append_to_output(self._apply_timestamps(shown) if TIMESTAMPS else shown)

    def action_toggle_capture(self):
        """Ctrl+W — start/stop capturing incoming data to Capture_log*.txt. Stopping writes
        the file IMMEDIATELY (not on the next incoming byte), so it works on a quiet device."""
        global CAPTURE, CAPTURE_LOG
        CAPTURE = not CAPTURE
        if CAPTURE:
            with self._capture_lock:
                CAPTURE_LOG = ""
            self._append_to_output("\n─── Capture started ───\n")
        else:
            self._flush_capture()

    def _flush_capture(self):
        """Write the accumulated capture buffer to the next Capture_log*.txt and reset it."""
        global CAPTURE_LOG, CAPTURE_LOG_FILE_COUNTER
        # Grab-AND-reset atomically so a byte arriving on the read thread mid-flush can't reappear in
        # the next capture; do the (slow) file write outside the lock on the local copy.
        with self._capture_lock:
            content = CAPTURE_LOG
            CAPTURE_LOG = ""
        if not content:
            self._append_to_output("\n─── Capture stopped (nothing captured) ───\n")
            return
        filename, idx = self._next_free_filename(self.session_cwd, 'Capture_log', '.txt',
                                                 CAPTURE_LOG_FILE_COUNTER)
        capture_path = os.path.join(self.session_cwd, filename)
        try:
            with open(capture_path, 'w', encoding='UTF-8') as f:
                f.write(content)
            CAPTURE_LOG_FILE_COUNTER = idx + 1
            self._append_to_output(f"\n─── Capture saved → {filename} ───\n")
        except OSError as err:
            self._append_to_output(f"\n─── Capture save failed: {err} ───\n")

    # ── Background update loop ────────────────────────────────────────────────

    def _is_disconnected(self) -> bool:
        """True when the device has gone away, cross-platform.

        The serial layer flips is_dev_open() to False when a read/write raises (the adapter was
        unplugged) — that works on every OS. The filesystem-existence check is a POSIX-only FAST
        PATH: a /dev/tty* node vanishes the instant a USB-serial adapter is pulled. It is NOT used
        on Windows, where a COM port is not a filesystem path, so os.path.exists("COM4") is always
        False — the old check treated that as "disconnected" and quit the app the moment it started.
        """
        if self.simulator_mode:
            return False
        if self.ser_dev is None:
            return False          # no real port managed yet — not a disconnect (and never crash the thread)
        if not self.ser_dev.is_dev_open():
            return True
        if os.name == "posix" and not exists(self.serial_dev_path):
            return True
        return False

    def periodic_update(self):
        """
        Background thread. Its ONLY job is the parts that must not block the UI:
        polling the device for incoming data, servicing capture/tab (which read
        the serial port), updating the status bar, and detecting a disconnect.
        Every user *action* (send, clear, history, help, …) is handled directly
        in the key bindings now, so nothing the user does waits on this loop.
        """
        global UPDATE_LOG_FLAG, TAB_PRESSED  # pylint: disable=global-statement

        while UPDATE_LOG_FLAG:
            # ── Device disconnect check ───────────────────────────────────
            if self._is_disconnected():
                UPDATE_LOG_FLAG = False
                self._append_to_output(
                    f"\n─── ERROR: {self.serial_dev_path} disconnected ───\n")
                try:
                    get_app().exit()
                except Exception:  # pylint: disable=broad-except
                    pass
                return

            # ── Status bar ───────────────────────────────────────────────
            # Status is a FormattedTextControl now: it pulls from status_segments()
            # on every render, so there is nothing to push from here. This used to
            # rebuild the whole string ~50x a second into a buffer.

            # ── Tab autocomplete: forward the current line + \t, show the reply ─────
            # Kept in the thread because it reads the serial port (and briefly waits for the
            # device to answer); doing it in the key binding would freeze the UI for that wait.
            # Both SEND the tab and APPLY the completion back into the input bar.
            #
            # This used to only display the device's reply and leave the input alone,
            # on two objections. Both are answered now, and the behaviour it produced
            # was wrong anyway: in a terminal emulator the input line IS the device's
            # line, so the shell's redraw updates what you are editing. SoftCOM has a
            # SEPARATE local input bar, so "show it in the log" left the user reading a
            # completion off the screen and then typing it out by hand — which is not
            # autocomplete, it is a hint.
            #   (a) unsafe cross-thread buffer write -> _set_input_text() hops to the
            #       event loop, the same way _set_output_document already does.
            #   (b) "the last line rarely starts with the typed prefix" -> true, because
            #       the PROMPT precedes it; extract_completion() searches within the
            #       line instead of anchoring at its start, and refuses anything that
            #       would not extend exactly what was typed.
            if TAB_PRESSED:
                TAB_PRESSED = False
                if not self.simulator_mode:
                    typed = self.input_buffer.text
                    self.ser_dev.exe_command(typed + "\t")
                    time.sleep(0.3)
                    response = self.ser_dev.read()
                    if response:
                        # Route the completion through the SAME pipeline as every other incoming byte
                        # (CR-normalise → capture → timestamp → pause). The old direct append skipped all
                        # of it: a tab-completed session LOST those bytes from the capture file, ignored
                        # the Ctrl+P pause, and never got an [HH:MM:SS] stamp — and it re-implemented (with
                        # the same redundant '^M' bug) the CR cleaning _process_incoming already does right.
                        self._process_incoming(response, display=not PAUSE_LOGGING)
                        completed = extract_completion(typed, response)
                        if completed is not None and completed != typed:
                            self._set_input_text(completed)

            # ── Incoming serial / simulator data ─────────────────────────
            # ALWAYS read the port, even while paused: pausing (Ctrl+P) freezes the on-screen log, but the
            # port must keep being drained or the OS serial buffer overflows and data is LOST during a long
            # pause — and a running CAPTURE must keep recording. `_process_incoming(display=...)` still
            # decodes, CR-normalises and captures the bytes; it just doesn't append to the log while paused.
            if self.simulator_mode:
                # Drain any replies to sent commands FIRST — they show promptly. Then, only if there's no
                # reply and enough time has passed, emit ONE line of slow idle "heartbeat" chatter. The loop
                # itself sleeps only briefly (0.05s) so a reply queued mid-idle drains right away instead of
                # waiting on the heartbeat interval — sleeping the full interval here would delay every reply
                # by up to _SIM_IDLE_INTERVAL. Replies are drained even while PAUSED (so a running capture
                # still records them) — just not displayed; chatter is suppressed while paused.
                sim_out = ""
                while True:
                    try:
                        sim_out += self._sim_queue.get_nowait()
                    except queue.Empty:
                        break
                now = time.time()
                if not sim_out and not PAUSE_LOGGING and now - self._last_sim_chatter >= _SIM_IDLE_INTERVAL:
                    sim_out = random_text_generator()
                    self._last_sim_chatter = now
                incoming = sim_out
                time.sleep(0.05)
            else:
                incoming = (self.ser_dev.read() if self.ser_dev is not None else "") or ""
            if incoming:
                self._process_incoming(incoming, display=not PAUSE_LOGGING)
            elif not self.simulator_mode:
                # A real read() is NON-blocking (it polls in_waiting and returns "" at once when nothing
                # is queued). Without a nap here the loop spins flat-out at 100% CPU whenever the device is
                # quiet — which is most of the time for a monitor. 20 ms keeps it responsive (~50 Hz).
                time.sleep(0.02)


# ── Key bindings ──────────────────────────────────────────────────────────────

def _call(method_name: str):
    """Invoke a method on the running GuiController from a key binding, and NEVER let it
    escape.

    An exception raised inside a key binding propagates straight out of prompt_toolkit's key
    processor and tears down the whole Application: the terminal is left half-restored and the
    user loses the session — including a running capture and the scrollback — because one
    shortcut hit a bad path (an unwritable log directory, a clipboard-less system, a device
    yanked mid-action). A failing shortcut must cost you the shortcut, not the session, so
    report it in the log and carry on.
    """
    inst = _gui_instance
    if inst is None:
        return
    try:
        getattr(inst, method_name)()
    except Exception as err:                    # pylint: disable=broad-except
        try:
            inst._append_to_output(              # pylint: disable=protected-access
                f"\n─── {method_name} failed: {type(err).__name__}: {err} ───\n")
        except Exception:                        # pylint: disable=broad-except
            pass                                 # never fail while reporting a failure


@kb.add("c-q", eager=True)
def _(event):
    """Ctrl+Q — quit"""
    global UPDATE_LOG_FLAG  # pylint: disable=global-statement
    UPDATE_LOG_FLAG = False
    event.app.exit()


@kb.add("c-x", eager=True)
def _(_):
    """Ctrl+X — clear output log"""
    _call("action_clear_log")


@kb.add("c-s", eager=True)
def _(_):
    """Ctrl+S — save output log to a file in the working directory"""
    _call("action_save_log")


@kb.add("c-c", eager=True)
def _(_):
    """Ctrl+C — send ^C (interrupt) to the device"""
    _call("action_send_interrupt")


@kb.add("c-d", eager=True)
def _(_):
    """Ctrl+D — send ^D (EOF) to the device"""
    _call("action_send_eof")


@kb.add("c-y", eager=True)
def _(_):
    """Ctrl+Y — copy output log to clipboard"""
    _call("action_copy_log")


@kb.add("c-w", eager=True)
def _(_):
    """Ctrl+W — start/stop capture (stop writes the file immediately)"""
    _call("action_toggle_capture")


@kb.add("c-l", eager=True)
def _(_):
    """Ctrl+L — show license in output log"""
    _call("action_show_license")


# These four target the INPUT bar, so they must stay out of the way while the search
# field is focused — otherwise Enter would fire a command at the device mid-search, Tab
# would trigger autocomplete, and Up/Down/Ctrl+K would edit the (hidden) input line.
@kb.add("c-m", eager=True)
def _(_):
    """Enter — send the input to the device, or (while searching) jump to the next match"""
    if SEARCH_ACTIVE:
        _call("action_search_next")
    else:
        _call("action_send")


@kb.add("tab", eager=True)
def _(_):
    """Tab — send Tab to the device for shell autocomplete"""
    global TAB_PRESSED  # pylint: disable=global-statement
    if not SEARCH_ACTIVE:
        TAB_PRESSED = True


@kb.add(Keys.BracketedPaste)
def _(event):
    """Paste — send each COMPLETE pasted line as its own command.

    The input bar is one row high, so a multi-line paste (a little shell script, a few config
    commands — a very common way to drive a device over serial) used to drop every embedded
    newline into that single row: you saw one mangled line, and the whole blob went out as a
    single command with the newlines buried inside it, so the device's line ending and this
    app's Ctrl+N line-ending setting no longer agreed. Behave like a real terminal instead:
    every complete line is sent (and recorded in history) in order, and any trailing fragment
    with no newline after it is left in the input bar for you to finish typing.
    """
    inst = _gui_instance
    data = event.data
    if inst is None or SEARCH_ACTIVE:
        # While searching, a paste belongs to the search field verbatim.
        event.current_buffer.insert_text(data.replace("\n", " ").replace("\r", " "))
        return
    if "\n" not in data and "\r" not in data:
        event.current_buffer.insert_text(data)      # ordinary single-line paste
        return
    lines = data.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    tail = lines.pop()                              # text after the last newline (may be "")
    try:
        for line in lines:
            inst.input_buffer.text = line
            inst.input_buffer.cursor_position = len(line)
            inst.action_send()
        inst.input_buffer.text = tail
        inst.input_buffer.cursor_position = len(tail)
    except Exception as err:                        # pylint: disable=broad-except
        inst._append_to_output(f"\n─── paste failed: {err} ───\n")   # pylint: disable=protected-access


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


# The filter is load-bearing. `escape` with eager=True short-circuits EVERY `escape,<key>`
# binding, and `escape,<key>` is exactly how a terminal delivers Alt/Meta — so with the filter
# missing, Alt+B in the input bar typed a literal "b" and Alt+D typed "d" instead of doing
# word-backward / delete-word (verified in the running app). Restricting the binding to the
# time the search bar is actually open gives Meta back everywhere else.
@kb.add("escape", eager=True, filter=_is_search_active)
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


@kb.add("c-n", eager=True)
def _(_):
    """Ctrl+N — cycle the line ending appended to sent commands (None/LF/CR/CRLF)"""
    _call("action_cycle_line_ending")


@kb.add("c-o", eager=True)
def _(_):
    """Ctrl+O — toggle local echo of sent commands"""
    _call("action_toggle_local_echo")


@kb.add("c-k", eager=True)
def _(_):
    """Ctrl+K — clear the input bar"""
    if not SEARCH_ACTIVE:
        _call("action_clear_input")


# NOTE: Help is F1, not Ctrl+H. In prompt_toolkit `Keys.Backspace == "c-h"`, so a
# Ctrl+H binding silently swallows every Backspace — you could not delete a
# character in the input or search fields. F1 is the conventional help key anyway.
@kb.add("f1", eager=True)
def _(_):
    """F1 — show help in output log"""
    _call("action_show_help")


@kb.add("c-p", eager=True)
def _(_):
    """Ctrl+P — pause / resume incoming log"""
    global PAUSE_LOGGING  # pylint: disable=global-statement
    PAUSE_LOGGING = not PAUSE_LOGGING


@kb.add("up", eager=True)
def _(_):
    """Up arrow — recall an older command"""
    if not SEARCH_ACTIVE:
        _call("action_history_up")


@kb.add("down", eager=True)
def _(_):
    """Down arrow — recall a newer command"""
    if not SEARCH_ACTIVE:
        _call("action_history_down")


@kb.add("pageup", eager=True)
def _(_):
    """PageUp — scroll back through the log (freezes auto-follow)"""
    _call("action_scroll_up")


@kb.add("pagedown", eager=True)
def _(_):
    """PageDown — scroll forward through the log"""
    _call("action_scroll_down")


@kb.add("c-e", eager=True)
def _(_):
    """Ctrl+E — jump back to the live bottom of the log"""
    _call("action_scroll_end")
