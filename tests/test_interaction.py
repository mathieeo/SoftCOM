"""
Tests for the newer SoftCOM fixes: serial bytesize threading, simulator robustness,
and the output-log scrollback (follow-tail) behaviour.
"""
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import pytest

import SoftCOM.support.serial_simulator as sim
from SoftCOM.support.exceptions import SerialDeviceOpenError
from SoftCOM.support.serial_manage import SerialManager


def test_serial_manager_stores_bytesize():
    sm = SerialManager('/dev/null', '9600', parity='E', stopbits=2, bytesize=7)
    assert sm.bytesize == 7
    assert sm.parity == 'E' and sm.stopbits == 2


def test_serial_manager_default_bytesize():
    sm = SerialManager('/dev/null', '9600')
    assert sm.bytesize == 8


def test_open_dev_bad_baud_raises_clean_error():
    """A None/non-numeric baud (from a partial settings.json) must raise SerialDeviceOpenError —
    the clean 'failed to open' path — not a raw TypeError/ValueError that crashes the app."""
    for bad_rate in (None, "notanumber"):
        with pytest.raises(SerialDeviceOpenError):
            SerialManager('/dev/null', bad_rate).open_dev()


class _ChunkSerial:
    """A fake pyserial port that hands back pre-set byte chunks, one per read()."""
    def __init__(self, chunks):
        self._chunks = list(chunks)

    @property
    def in_waiting(self):
        return len(self._chunks[0]) if self._chunks else 0

    def read(self, _n):
        return self._chunks.pop(0) if self._chunks else b""


def test_read_incremental_utf8_across_chunks():
    """A multi-byte UTF-8 char split across two serial reads must decode cleanly (no � mojibake).
    '✓' is E2 9C 93; feed the first byte, then the rest, and the two reads must reassemble it."""
    sm = SerialManager('/dev/null', 9600)
    sm.is_open = True
    sm.ser = _ChunkSerial([b'\xe2', b'\x9c\x93 done\n'])
    first = sm.read()               # only the lead byte arrives — must not emit a replacement char
    second = sm.read()              # the continuation completes the character
    assert '�' not in (first + second)
    assert first + second == '✓ done\n'


class _ClosableSerial:
    """A fake pyserial port that only records whether close() was called."""
    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True


def test_close_dev_clears_is_open():
    """After close_dev(), is_dev_open() must report False — otherwise the status bar and the
    disconnect watchdog keep treating a deliberately-closed port as still live."""
    sm = SerialManager('/dev/null', 9600)
    sm.is_open = True
    sm.ser = _ClosableSerial()
    sm.close_dev()
    assert sm.ser.closed is True
    assert sm.is_dev_open() is False


def test_simulator_has_lines_and_generates():
    assert len(sim.lines) > 0
    out = sim.random_text_generator()
    assert isinstance(out, str) and out.endswith("\n")


def test_simulator_responds_to_sent_commands():
    """`-s` simulator mode used to ignore sent commands entirely (no reply, so the send→receive round-trip
    was untestable without hardware). The fake device now answers: canned replies for a few commands, an echo,
    control-byte acknowledgements, and a generic ack — always newline-terminated (or '' for a bare Enter)."""
    assert "online" in sim.respond("status")
    assert "commands:" in sim.respond("help") and sim.respond("?") == sim.respond("help")
    assert sim.respond("version").strip().endswith("v1.0")
    assert sim.respond("echo hello world") == "hello world\n"
    assert sim.respond("FoO") == "[SIM] ack: FoO\n"          # unknown → generic ack, original case kept
    assert sim.respond("\x03") == "[SIM] ^C interrupt\n"     # Ctrl+C
    assert sim.respond("\x04") == "[SIM] ^D end-of-input\n"  # Ctrl+D
    assert sim.respond("") == "" and sim.respond("\n") == "" and sim.respond("   ") == ""
    for cmd in ("status", "help", "echo x", "whatever"):
        assert sim.respond(cmd).endswith("\n")


def test_send_command_in_simulator_queues_a_reply():
    """In simulator mode, send_command must queue a fake-device reply for the read thread to emit — so a sent
    command actually produces a response on screen (and feeds a running capture), not silence."""
    g = _make_controller()               # simulator controller
    assert g._sim_queue.empty()
    g.send_command("status\n")           # what action_send passes (command + line ending)
    assert not g._sim_queue.empty()
    reply = g._sim_queue.get_nowait()
    assert "status" in reply and reply.endswith("\n")
    # a bare Enter (empty command) queues nothing
    g.send_command("\n")
    assert g._sim_queue.empty()


def test_simulator_idle_chatter_is_readable():
    """The simulator's idle background chatter must be SLOW enough to read. It used to fire every 0.2s
    (5 lines/sec), which — now that the simulator answers sent commands — buried the reply and made the log
    race away while testing without hardware. Keep the heartbeat at a readable interval; a command reply still
    shows promptly because it jumps the queue independent of this interval."""
    import SoftCOM.gui_controller as gc
    assert gc._SIM_IDLE_INTERVAL >= 0.8    # readable, not a 5-lines-per-second flood


# ── Scrollback / follow-tail (needs a constructed GuiController) ────────────────

def _make_controller():
    from prompt_toolkit.application import Application, create_app_session
    from prompt_toolkit.input import DummyInput
    from prompt_toolkit.output import DummyOutput

    import SoftCOM.gui_controller as gc
    Application.run = lambda self, *a, **k: None      # don't take over the terminal
    # Build the Application against a dummy terminal so it works under pytest (no real tty).
    with create_app_session(input=DummyInput(), output=DummyOutput()):
        g = gc.GuiController("simulator", "", simulator_mode=True)
    gc.UPDATE_LOG_FLAG = False                          # stop the background read thread
    time.sleep(0.03)
    return g


def test_history_navigation_walks_entries_and_restores_partial_line():
    """Up/Down walk the command history; and — the improvement — starting to browse with Up stashes a
    half-typed line so Down brings it back (a real shell keeps it; the old code lost it, giving empty)."""
    g = _make_controller()
    g.command_history = ["first", "second", "third"]     # third is newest
    g.history_index = -1
    g.input_buffer.text = "half typed"                   # an in-progress command, not yet sent

    g.action_history_up()                                # newest first
    assert g.input_buffer.text == "third"
    g.action_history_up()
    assert g.input_buffer.text == "second"
    g.action_history_up()
    assert g.input_buffer.text == "first"                # oldest
    g.action_history_up()
    assert g.input_buffer.text == "first"                # clamps at the oldest

    g.action_history_down()
    assert g.input_buffer.text == "second"
    g.action_history_down()
    assert g.input_buffer.text == "third"
    g.action_history_down()                              # back below newest → the half-typed line returns
    assert g.input_buffer.text == "half typed"
    assert g.history_index == -1
    g.action_history_down()                              # nothing below → unchanged, no crash
    assert g.input_buffer.text == "half typed"


def test_follow_tail_default_and_append_pins_to_bottom():
    g = _make_controller()
    assert g.follow_tail is True
    g._clear_output()
    g._append_to_output("l0\nl1\nl2\nl3\n")
    # following the tail → cursor at the end
    assert g.output_buffer.cursor_position == len(g.output_buffer.text)


def test_scroll_up_freezes_and_incoming_keeps_position():
    g = _make_controller()
    g._clear_output()
    g._append_to_output("".join(f"line{i}\n" for i in range(40)))
    g.action_scroll_up()                    # PageUp
    assert g.follow_tail is False
    frozen = g.output_buffer.cursor_position
    # new data arriving must NOT yank the cursor to the bottom while scrolled up
    g._append_to_output("more1\nmore2\n")
    assert g.output_buffer.cursor_position == frozen
    # Ctrl+E snaps back to live
    g.action_scroll_end()
    assert g.follow_tail is True
    assert g.output_buffer.cursor_position == len(g.output_buffer.text)


def test_send_resumes_follow_tail():
    g = _make_controller()
    g.follow_tail = False
    g.input_buffer.text = "status"
    g.action_send()
    assert g.follow_tail is True            # you always see the reply to your command


def test_scrollback_cursor_shifts_when_buffer_trims():
    """While scrolled up, when the capped buffer drops chars off the FRONT the reader's cursor
    must shift left by the same amount so the view stays on the same text (not jump forward)."""
    from prompt_toolkit.document import Document
    g = _make_controller()
    g._MAX_OUTPUT = 100
    g.follow_tail = False
    g.output_buffer.set_document(Document("A" * 90, 50), bypass_readonly=True)
    # Total 120 chars → 20 over the 100 cap → 20 dropped from the front (no newline boundary).
    g._write_output("A" * 90 + "B" * 30)
    assert len(g.output_buffer.text) == 100
    assert g.output_buffer.cursor_position == 30      # 50 − 20 trimmed


# ── Capture (Ctrl+W) writes the file the instant you stop, even on a quiet device ──

def test_paused_display_still_captures_but_does_not_show(tmp_path):
    """Pausing the on-screen log (Ctrl+P) freezes the DISPLAY only — the port keeps being read/decoded and
    a running CAPTURE keeps recording. So `_process_incoming(display=False)` must NOT append to the output
    buffer but MUST still accumulate the capture. (Regression: pause used to skip the read entirely, losing
    data and stopping the capture during a display pause.)"""
    import SoftCOM.gui_controller as gc
    g = _make_controller()
    g._clear_output()
    gc.CAPTURE = True
    gc.CAPTURE_LOG = ""
    g._process_incoming("while paused\n", display=False)   # arrives while the log is paused
    assert g.output_buffer.text == ""                      # not shown
    assert "while paused" in gc.CAPTURE_LOG                 # but still captured
    g._process_incoming("after resume\n", display=True)    # resumed
    assert "after resume" in g.output_buffer.text          # shown now
    assert "while paused" in gc.CAPTURE_LOG and "after resume" in gc.CAPTURE_LOG
    gc.CAPTURE = False; gc.CAPTURE_LOG = ""


def test_capture_flushes_on_stop_without_more_data(tmp_path):
    import SoftCOM.gui_controller as gc
    g = _make_controller()
    g.session_cwd = str(tmp_path)
    gc.CAPTURE = False
    gc.CAPTURE_LOG = ""
    gc.CAPTURE_LOG_FILE_COUNTER = 0

    g.action_toggle_capture()               # Ctrl+W → start
    assert gc.CAPTURE is True
    g._process_incoming("hello world\n")     # some device data arrives
    g.action_toggle_capture()               # Ctrl+W → stop (device now silent)
    assert gc.CAPTURE is False

    # The file must exist RIGHT NOW — not on some future byte that never comes.
    saved = tmp_path / "Capture_log0.txt"
    assert saved.is_file()
    assert "hello world" in saved.read_text()


def test_capture_stop_with_no_data_writes_nothing(tmp_path):
    import SoftCOM.gui_controller as gc
    g = _make_controller()
    g.session_cwd = str(tmp_path)
    gc.CAPTURE = False
    gc.CAPTURE_LOG = ""
    gc.CAPTURE_LOG_FILE_COUNTER = 0

    g.action_toggle_capture()               # start
    g.action_toggle_capture()               # stop immediately, nothing captured
    assert not (tmp_path / "Capture_log0.txt").exists()


def test_second_capture_does_not_inherit_first(tmp_path):
    """Stopping a capture must fully reset the buffer, so a SECOND capture never carries the first
    capture's content — the data-integrity guarantee the capture lock protects."""
    import SoftCOM.gui_controller as gc
    g = _make_controller()
    g.session_cwd = str(tmp_path)
    gc.CAPTURE = False
    gc.CAPTURE_LOG = ""
    gc.CAPTURE_LOG_FILE_COUNTER = 0

    g.action_toggle_capture()               # start #1
    g._process_incoming("FIRST\n")
    g.action_toggle_capture()               # stop → Capture_log0.txt
    g.action_toggle_capture()               # start #2
    g._process_incoming("SECOND\n")
    g.action_toggle_capture()               # stop → Capture_log1.txt

    first = (tmp_path / "Capture_log0.txt").read_text()
    second = (tmp_path / "Capture_log1.txt").read_text()
    assert "FIRST" in first and "SECOND" not in first
    assert "SECOND" in second and "FIRST" not in second   # no leftover from capture #1


# ── Saving never overwrites a log/capture left by a previous session ──

def test_save_log_never_overwrites_existing(tmp_path):
    import SoftCOM.gui_controller as gc
    g = _make_controller()
    g.session_cwd = str(tmp_path)
    gc.LOG_FILE_COUNTER = 0
    # a file from a "previous session" is already on disk
    (tmp_path / "OUTPUT_LOG0.txt").write_text("PREVIOUS SESSION")
    g._clear_output()
    g._append_to_output("new session data\n")
    g.action_save_log()
    # the old file must be untouched; the new save goes to the next free name
    assert (tmp_path / "OUTPUT_LOG0.txt").read_text() == "PREVIOUS SESSION"
    assert (tmp_path / "OUTPUT_LOG1.txt").is_file()
    assert "new session data" in (tmp_path / "OUTPUT_LOG1.txt").read_text()


def test_capture_save_skips_existing_files(tmp_path):
    import SoftCOM.gui_controller as gc
    g = _make_controller()
    g.session_cwd = str(tmp_path)
    gc.CAPTURE = False
    gc.CAPTURE_LOG = ""
    gc.CAPTURE_LOG_FILE_COUNTER = 0
    (tmp_path / "Capture_log0.txt").write_text("OLD CAPTURE")   # left by a prior session
    g.action_toggle_capture()               # start
    g._process_incoming("fresh bytes\n")
    g.action_toggle_capture()               # stop → must not clobber Capture_log0.txt
    assert (tmp_path / "Capture_log0.txt").read_text() == "OLD CAPTURE"
    assert (tmp_path / "Capture_log1.txt").is_file()
    assert "fresh bytes" in (tmp_path / "Capture_log1.txt").read_text()


# ── Timestamps (Ctrl+T): one stamp per real line, even on a fragmented stream ──

def test_timestamp_only_at_line_start_across_chunks(monkeypatch):
    """A serial line usually arrives in pieces; the timestamp must land only where a real new
    line begins, not on every chunk — and never mid-line."""
    import SoftCOM.gui_controller as gc
    g = _make_controller()
    g._clear_output()
    monkeypatch.setattr(gc.time, "strftime", lambda _fmt: "[T] ")
    monkeypatch.setattr(gc, "TIMESTAMPS", True)
    g._ts_line_start = True
    g._process_incoming("hel")       # partial line — no newline yet
    g._process_incoming("lo\n")      # completes the same line
    g._process_incoming("next\n")    # a second, whole line
    assert g.output_buffer.text == "[T] hello\n[T] next\n"


def test_timestamp_tracker_stays_current_while_off(monkeypatch):
    """Regression: toggling timestamps back ON mid-stream (Ctrl+T) must stamp the NEXT real line. The
    line-start tracker only advanced while timestamps were ON, so after a stretch with them OFF it was STALE:
    if the log was mid-line when they were turned off, the tracker stayed 'mid-line' and the first fresh line
    after re-enabling got NO stamp. It must now follow along even while off (for displayed data)."""
    import SoftCOM.gui_controller as gc
    g = _make_controller()
    g._clear_output()
    monkeypatch.setattr(gc.time, "strftime", lambda _fmt: "[T] ")
    # start mid-line: timestamps ON, a chunk with no trailing newline (tracker → mid-line / False)
    monkeypatch.setattr(gc, "TIMESTAMPS", True)
    g._ts_line_start = True
    g._process_incoming("abc")            # "[T] abc", now mid-line
    # timestamps OFF: finish that line, then a whole fresh line — the tracker must keep up
    monkeypatch.setattr(gc, "TIMESTAMPS", False)
    g._process_incoming("def\n")          # completes the line: "[T] abcdef\n"
    g._process_incoming("ghi\n")          # a fresh whole line, un-timestamped
    # back ON: the next fresh line MUST be stamped (old bug: tracker stuck at 'mid-line' → no stamp)
    monkeypatch.setattr(gc, "TIMESTAMPS", True)
    g._process_incoming("jkl\n")
    assert g.output_buffer.text == "[T] abcdef\nghi\n[T] jkl\n"


def test_timestamp_survives_app_message_between_lines(monkeypatch):
    """Regression: an app message (Log saved / Capture started) or a local echo ('> cmd') goes through
    _append_to_output, NOT _process_incoming, so it never touched the line-start tracker. A device line
    arriving AFTER such a message (which ends in a newline) then got NO timestamp — the tracker was stale
    'mid-line' from the earlier device chunk. The tracker is now maintained in _append_to_output (the one
    funnel every append passes through), so the next device line is stamped correctly."""
    import SoftCOM.gui_controller as gc
    g = _make_controller()
    g._clear_output()
    monkeypatch.setattr(gc.time, "strftime", lambda _fmt: "[T] ")
    monkeypatch.setattr(gc, "TIMESTAMPS", True)
    g._process_incoming("abc")                       # device mid-line: "[T] abc", tracker → mid-line
    g._append_to_output("\n─── Log saved ───\n")     # an app message (ends in \n) — bypasses timestamping
    g._process_incoming("def\n")                     # a fresh device line — MUST be stamped
    assert g.output_buffer.text == "[T] abc\n─── Log saved ───\n[T] def\n"


def test_timestamp_does_not_split_on_formfeed_or_unicode_breaks(monkeypatch):
    """Timestamps must be inserted only at real '\\n' line starts. str.splitlines() also breaks on
    \\f (form-feed — instruments emit it to clear the screen), \\v, \\x85, \\u2028 etc., which used to
    inject a stray timestamp MID-line at those bytes; they must stay inline with no extra stamp."""
    import SoftCOM.gui_controller as gc
    g = _make_controller()
    monkeypatch.setattr(gc.time, "strftime", lambda _fmt: "[T] ")
    for probe in ("\x0c", "\x0b", "\x85", " "):
        g._clear_output(); g._ts_line_start = True
        out = g._apply_timestamps(f"abc{probe}def\n")
        # exactly one timestamp, at the very start; the odd byte stays inline
        assert out == f"[T] abc{probe}def\n", repr(out)
        assert out.count("[T] ") == 1, repr(out)


def test_internal_messages_are_not_timestamped(monkeypatch):
    import SoftCOM.gui_controller as gc
    g = _make_controller()
    g._clear_output()
    monkeypatch.setattr(gc.time, "strftime", lambda _fmt: "[T] ")
    monkeypatch.setattr(gc, "TIMESTAMPS", True)
    g._append_to_output("\n─── Log saved ───\n")   # app's own message
    assert "[T]" not in g.output_buffer.text


# ── Incoming CR/LF normalisation (CR-only devices, split CRLF, '\r' progress) ──

def test_incoming_cr_normalised_for_display(monkeypatch):
    """CRLF collapses to one newline (even when split across two reads), and a lone CR breaks the
    line — so a CR-only device (or a '\\r' progress redraw) reads as separate lines instead of being
    concatenated onto one line, which is what deleting every '\\r' used to do."""
    import SoftCOM.gui_controller as gc
    g = _make_controller()
    monkeypatch.setattr(gc, "TIMESTAMPS", False)

    # a lone CR mid-stream becomes a line break
    g._clear_output(); g._cr_pending = ""; g._ts_line_start = True
    g._process_incoming("abc\rdef\n")
    assert g.output_buffer.text == "abc\ndef\n"

    # a whole CRLF collapses to a single newline (no doubled/blank line)
    g._clear_output(); g._cr_pending = ""; g._ts_line_start = True
    g._process_incoming("one\r\ntwo\r\n")
    assert g.output_buffer.text == "one\ntwo\n"

    # a CRLF split between two reads still collapses to a single newline
    g._clear_output(); g._cr_pending = ""; g._ts_line_start = True
    g._process_incoming("hi\r")
    g._process_incoming("\nthere\r\n")
    assert g.output_buffer.text == "hi\nthere\n"


def test_literal_caret_M_text_is_preserved(monkeypatch):
    """A real carriage return (0x0D) is already turned into a newline, so the LITERAL two-char text
    '^M' left in device output is genuine content (e.g. `cat -v`, `stty`, vim showing CR endings).
    Regression: it used to be stripped, silently corrupting that output."""
    import SoftCOM.gui_controller as gc
    g = _make_controller()
    monkeypatch.setattr(gc, "TIMESTAMPS", False)
    g._clear_output(); g._cr_pending = ""; g._ts_line_start = True
    g._process_incoming("file.txt: ASCII text, with CRLF (^M) line terminators\n")
    assert "^M" in g.output_buffer.text


def test_tab_completion_response_is_captured_and_pause_aware(monkeypatch):
    """Tab-completion output must flow through the SAME pipeline as all incoming data. Regression:
    the tab reply was appended directly, so it was never written to the CAPTURE file, ignored the
    Ctrl+P pause, and never got a timestamp. Here we exercise the exact call the tab path now makes."""
    import SoftCOM.gui_controller as gc
    g = _make_controller()
    g._clear_output()
    gc.CAPTURE = True
    gc.CAPTURE_LOG = ""
    # tab reply arriving while the display is paused: captured but not shown (matches other incoming)
    g._process_incoming("ls  ls-dir  lsblk\n", display=False)
    assert g.output_buffer.text == ""                       # pause honoured — not shown
    assert "lsblk" in gc.CAPTURE_LOG                         # but the completion WAS captured
    # and while live it shows on screen too
    g._process_incoming("cat  cat-file\n", display=True)
    assert "cat-file" in g.output_buffer.text
    assert "cat-file" in gc.CAPTURE_LOG
    gc.CAPTURE = False; gc.CAPTURE_LOG = ""


# ── Recent-Commands panel: seeded from history, bounded, de-duplicated ──

def test_history_panel_seeded_and_dedupes(monkeypatch):
    g = _make_controller()
    monkeypatch.setattr(g, "_save_history", lambda: None)   # don't touch ~/.softcom_history
    g.command_history = ["old_a", "old_b"]
    g._refresh_history_panel()
    assert "old_a" in g.history_buffer.text and "old_b" in g.history_buffer.text
    # re-sending the same command must not pile up duplicates in the list OR the panel
    g.input_buffer.text = "ls"
    g.action_send()
    g.input_buffer.text = "ls"
    g.action_send()
    assert g.command_history.count("ls") == 1
    assert g.history_buffer.text.count("ls") == 1


# ── Ctrl+F search actually navigates (Enter → next match, wraps) ──

def test_search_next_jumps_and_wraps(monkeypatch):
    import SoftCOM.gui_controller as gc
    g = _make_controller()
    g._clear_output()
    g._append_to_output("aaa TARGET bbb TARGET ccc")
    monkeypatch.setattr(gc, "SEARCH_STRING", "target")
    g.output_buffer.cursor_position = 0
    body = "aaa TARGET bbb TARGET ccc".lower()
    g.action_search_next()
    first = g.output_buffer.cursor_position
    assert first == body.find("target")            # 4
    g.action_search_next()
    assert g.output_buffer.cursor_position == body.find("target", first + 1)   # 15
    g.action_search_next()                          # past the last → wrap to the first
    assert g.output_buffer.cursor_position == first


def test_status_shows_search_match_count(monkeypatch):
    """The status bar reports how many times the pattern occurs (case-insensitively), so a
    pattern that matches nothing reads '(0 matches)' instead of silently doing nothing."""
    import SoftCOM.gui_controller as gc
    g = _make_controller()
    g._clear_output()
    g._append_to_output("aaa Target bbb TARGET ccc target")
    monkeypatch.setattr(gc, "SEARCH_ACTIVE", True)
    monkeypatch.setattr(gc, "SEARCH_STRING", "target")
    assert "(3 matches)" in g.get_status_text()
    monkeypatch.setattr(gc, "SEARCH_STRING", "zzz")
    assert "(0 matches)" in g.get_status_text()
    monkeypatch.setattr(gc, "SEARCH_STRING", "ccc")
    assert "(1 match)" in g.get_status_text()          # singular, no trailing 'es'


def test_search_count_stays_correct_at_buffer_cap(monkeypatch):
    """Regression: the live match count must stay correct once the log hits its size cap. The cache used
    to key on len(text) — which sits FROZEN at the cap while the front is trimmed and the back grows — so
    on a busy/flooding log the count got stuck at a stale, wrong value. It now keys on a write counter, so
    two equal-length writes with DIFFERENT match counts each report correctly."""
    import SoftCOM.gui_controller as gc
    g = _make_controller()
    g._MAX_OUTPUT = 20                                  # force the cap; both writes below are exactly 20 chars
    monkeypatch.setattr(gc, "SEARCH_ACTIVE", True)
    monkeypatch.setattr(gc, "SEARCH_STRING", "x")
    g._clear_output()
    three = "x" + "." * 6 + "x" + "." * 6 + "x" + "." * 5   # 20 chars, 3 matches
    one = "." * 19 + "x"                                     # 20 chars, 1 match
    assert len(three) == 20 and len(one) == 20
    g._write_output(three)
    assert "(3 matches)" in g.get_status_text()
    g._write_output(one)                                # same len → the old len-key stayed cached at 3
    assert "(1 match)" in g.get_status_text()


# ── Line ending (Ctrl+N): sent-command terminator is configurable & persisted ──

def test_action_send_appends_configured_line_ending(monkeypatch):
    import SoftCOM.gui_controller as gc
    g = _make_controller()
    monkeypatch.setattr(g, "_save_history", lambda: None)   # don't touch ~/.softcom_history
    sent = []
    monkeypatch.setattr(g, "send_command", lambda c: sent.append(c))
    for eol, expected in [("NONE", "AT"), ("LF", "AT\n"), ("CR", "AT\r"), ("CRLF", "AT\r\n")]:
        sent.clear()
        monkeypatch.setattr(gc, "LINE_ENDING", eol)
        g.input_buffer.text = "AT"
        g.action_send()
        assert sent == [expected]


def test_line_ending_cycle_persists(tmp_path):
    import SoftCOM.gui_controller as gc
    from SoftCOM.support.save_settings import SaveSettings
    g = _make_controller()
    store = SaveSettings(str(tmp_path / "s.json"))
    g.settings_store = store
    gc.LINE_ENDING = "LF"
    g.action_cycle_line_ending()                    # LF → CR
    assert gc.LINE_ENDING == "CR" and store.line_ending == "CR"
    g.action_cycle_line_ending()                    # CR → CRLF
    g.action_cycle_line_ending()                    # CRLF → NONE
    assert gc.LINE_ENDING == "NONE"
    g.action_cycle_line_ending()                    # NONE → LF (wraps)
    assert gc.LINE_ENDING == "LF"
    # the choice survives a reload of the settings file
    assert SaveSettings(str(tmp_path / "s.json")).line_ending == "LF"


# ── Local echo (Ctrl+O): show what you sent when the device doesn't echo ──

def test_local_echo_shows_sent_command(monkeypatch):
    import SoftCOM.gui_controller as gc
    g = _make_controller()
    g.simulator_mode = False                         # a real (non-echoing) device
    monkeypatch.setattr(g, "_save_history", lambda: None)
    monkeypatch.setattr(g, "send_command", lambda c: None)
    g._clear_output()
    monkeypatch.setattr(gc, "LOCAL_ECHO", False)     # off → nothing echoed
    g.input_buffer.text = "AT"
    g.action_send()
    assert "> AT" not in g.output_buffer.text
    monkeypatch.setattr(gc, "LOCAL_ECHO", True)      # on → the sent line appears
    g.input_buffer.text = "AT"
    g.action_send()
    assert "> AT" in g.output_buffer.text


def test_local_echo_toggle_persists(tmp_path):
    import SoftCOM.gui_controller as gc
    from SoftCOM.support.save_settings import SaveSettings
    g = _make_controller()
    store = SaveSettings(str(tmp_path / "s.json"))
    g.settings_store = store
    gc.LOCAL_ECHO = False
    g.action_toggle_local_echo()
    assert gc.LOCAL_ECHO is True and store.local_echo is True
    assert SaveSettings(str(tmp_path / "s.json")).local_echo is True
    g.action_toggle_local_echo()
    assert gc.LOCAL_ECHO is False and store.local_echo is False


# ── Ctrl+C / Ctrl+D send control bytes to the DEVICE (interrupt / EOF) ──

def test_ctrl_c_and_d_send_raw_control_bytes(monkeypatch):
    g = _make_controller()
    g.simulator_mode = False
    sent = []
    monkeypatch.setattr(g, "send_command", lambda c: sent.append(c))
    g.action_send_interrupt()
    assert sent == ["\x03"]                 # ^C interrupt, raw, no line ending
    sent.clear()
    g.action_send_eof()
    assert sent == ["\x04"]                 # ^D EOF


def test_ctrl_c_marker_follows_local_echo(monkeypatch):
    import SoftCOM.gui_controller as gc
    g = _make_controller()
    g.simulator_mode = False
    monkeypatch.setattr(g, "send_command", lambda c: None)
    g._clear_output()
    monkeypatch.setattr(gc, "LOCAL_ECHO", False)   # device echoes it → no local marker
    g.action_send_interrupt()
    assert "^C" not in g.output_buffer.text
    monkeypatch.setattr(gc, "LOCAL_ECHO", True)     # local echo on → show the ^C marker
    g.action_send_interrupt()
    assert "^C" in g.output_buffer.text


# ── Cross-platform disconnect detection (Windows COM-port regression) ──

class _FakeSerial:
    def __init__(self, is_open):
        self._open = is_open
    def is_dev_open(self):
        return self._open

def test_disconnect_detection_cross_platform(monkeypatch):
    """The disconnect check must NOT rely on os.path.exists for the port on Windows: a COM port
    is not a filesystem path, so exists('COM4') is always False and the old check quit the app the
    instant it started. It must use the serial layer's is_dev_open() everywhere, and only treat a
    vanished /dev node as a fast path on POSIX."""
    import SoftCOM.gui_controller as gc
    g = _make_controller()
    g.simulator_mode = False
    g.serial_dev_path = "COM4"

    # Windows: port open but the path doesn't exist on disk → must NOT be "disconnected".
    g.ser_dev = _FakeSerial(is_open=True)
    monkeypatch.setattr(gc.os, "name", "nt")
    monkeypatch.setattr(gc, "exists", lambda _p: False)   # COM4 never exists as a path
    assert g._is_disconnected() is False                  # the regression: was True → instant quit

    # Windows: the serial layer reports the port closed (read failed) → disconnected.
    g.ser_dev = _FakeSerial(is_open=False)
    assert g._is_disconnected() is True

    # POSIX: port open but the /dev node vanished (adapter pulled) → disconnected (fast path).
    monkeypatch.setattr(gc.os, "name", "posix")
    g.ser_dev = _FakeSerial(is_open=True)
    monkeypatch.setattr(gc, "exists", lambda _p: False)
    assert g._is_disconnected() is True

    # POSIX: port open and node present → connected.
    monkeypatch.setattr(gc, "exists", lambda _p: True)
    assert g._is_disconnected() is False

    # Simulator mode is never "disconnected".
    g.simulator_mode = True
    assert g._is_disconnected() is False


def test_background_thread_never_crashes_on_missing_ser_dev(monkeypatch):
    """Regression: the background read thread calls _is_disconnected() / get_status_text() every
    ~0.1s. If it ran with simulator_mode False while ser_dev was absent (a teardown/startup race, or
    a simulator controller whose mode got flipped), touching self.ser_dev raised AttributeError and
    killed the thread (seen as a PytestUnhandledThreadExceptionWarning). ser_dev is now always defined
    (None until a real port opens) and every background-thread access guards it — no crash, no false
    disconnect."""
    import SoftCOM.gui_controller as gc
    g = _make_controller()          # simulator controller → ser_dev is None
    assert g.ser_dev is None        # attribute always exists now, even in simulator mode

    # Flip to non-simulator with NO device handle — the exact racy state that used to crash the thread.
    g.simulator_mode = False
    monkeypatch.setattr(gc.os, "name", "posix")
    monkeypatch.setattr(gc, "exists", lambda _p: True)
    assert g._is_disconnected() is False            # not a disconnect, and must not raise
    assert "CLOSED" in g.get_status_text()          # reports CLOSED safely instead of crashing


def test_port_present_windows_defers_to_open(monkeypatch):
    """_port_present must return True for a COM port on Windows (can't stat it, defer to open_dev)
    instead of rejecting it — the startup bug that made SoftCOM unusable on Windows."""
    import SoftCOM.softcom as softcom
    monkeypatch.setattr(softcom.os, "name", "nt")
    assert softcom._port_present("COM4") is True          # regression: was False → app quit
    monkeypatch.setattr(softcom.os, "name", "posix")
    monkeypatch.setattr(softcom, "exists", lambda _p: False)
    assert softcom._port_present("/dev/ttyUSB0") is False  # POSIX still stat-checks the node
    monkeypatch.setattr(softcom, "exists", lambda _p: True)
    assert softcom._port_present("/dev/ttyUSB0") is True


def test_dev_diagnostics_prints_resolved_config(capsys):
    """--developer / -d must actually DO something: print the resolved connection config to stderr so a
    developer can see what SoftCOM resolved. Regression: the flag used to be parsed and then never read, so
    `softcom -d` silently did nothing despite advertising 'Run in developer mode.'"""
    import SoftCOM.softcom as softcom
    softcom._print_dev_diagnostics("/dev/ttyUSB0", 115200, 8, 'N', 1,
                                   simulator=False, settings_path="/tmp/settings.json")
    err = capsys.readouterr().err
    assert "developer diagnostics" in err
    assert "/dev/ttyUSB0" in err       # device is echoed
    assert "115200" in err             # baud is echoed
    assert "8N1" in err                # framing = data/parity/stop
    assert "serial" in err             # mode reflects non-simulator
    assert "/tmp/settings.json" in err  # settings path is echoed

    # simulator mode has no baud — must not blow up formatting None/empty baud
    softcom._print_dev_diagnostics("simulator", "", 8, 'N', 1,
                                   simulator=True, settings_path="/tmp/s.json")
    err2 = capsys.readouterr().err
    assert "simulator" in err2
    assert "(n/a)" in err2             # empty baud rendered as (n/a), not blank/crash


def test_detect_ports_offers_detected_devices(monkeypatch):
    """First-run config should OFFER the serial ports that are actually present instead of making the user
    type a path blind. _detect_ports() turns pyserial's comports() into (device, label) choices, floats real
    USB adapters (those with a VID) above virtual/bluetooth ports, and NEVER raises — any enumeration failure
    returns [] so config falls back to typing."""
    from serial.tools import list_ports

    import SoftCOM.softcom as softcom

    class _P:
        def __init__(self, device, description, vid):
            self.device, self.description, self.vid = device, description, vid

    fake = [_P("/dev/cu.Bluetooth", "n/a", None),         # virtual, no VID → should sort LAST
            _P("/dev/ttyUSB0", "FT232R USB UART", 0x0403)] # real adapter, has VID → should sort FIRST
    monkeypatch.setattr(list_ports, "comports", lambda: fake)
    got = softcom._detect_ports()
    assert got[0][0] == "/dev/ttyUSB0"                    # the real USB adapter is offered first
    assert got[0][1] == "/dev/ttyUSB0 — FT232R USB UART"  # device + description label
    assert ("/dev/cu.Bluetooth", "/dev/cu.Bluetooth") in got  # 'n/a' description dropped from the label

    # enumeration blowing up must NOT crash config — it falls back to an empty list (→ type a path)
    def _boom():
        raise OSError("device busy")
    monkeypatch.setattr(list_ports, "comports", _boom)
    assert softcom._detect_ports() == []
