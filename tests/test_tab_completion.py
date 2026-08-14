"""Tab autocomplete: reading the device's answer back into the input bar.

Tab used to send the tab, print whatever came back into the log, and leave the input
bar exactly as the user left it. In a terminal emulator that is correct behaviour,
because the input line IS the device's line and the shell's redraw updates what you
are editing. SoftCOM has a SEPARATE local input bar, so the same behaviour left the
user reading a completion off the screen and typing it out by hand. That is a hint,
not autocomplete, and it is what "the tab feature is broken" meant in practice.

`extract_completion` is the parser that closes the loop. It carries one invariant that
matters more than any completion it gets right:

    THE RESULT ALWAYS STARTS WITH WHAT THE USER TYPED.

It is allowed to decline (return None). It is never allowed to shorten, truncate or
rewrite the input bar, because a misparse that eats a half-typed command is far worse
than a Tab that did nothing. Most of what follows is testing the refusals.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from SoftCOM.gui_controller import extract_completion  # noqa: E402


class TestUniqueMatchSuffix:
    """The shell had exactly one candidate and sent only the missing characters."""

    def test_plain_suffix_is_appended(self):
        assert extract_completion("ls /ho", "me/") == "ls /home/"

    def test_suffix_with_trailing_newline(self):
        assert extract_completion("cat READ", "ME.md\r\n") == "cat README.md"

    def test_suffix_may_contain_a_space(self):
        # `ls -la ` — a completed word ending in a space is normal.
        assert extract_completion("systemctl stat", "us ") == "systemctl status "


class TestLineRedraw:
    """The shell reprinted its prompt and the whole completed line."""

    def test_prompt_then_completed_line(self):
        resp = "\r\x1b[K root@target:/# ls /home/"
        assert extract_completion("ls /ho", resp) == "ls /home/"

    def test_coloured_prompt(self):
        # The default prompt on most Linux targets is colourised.
        resp = "\r\x1b[1;32mroot@target\x1b[0m:\x1b[1;34m/\x1b[0m# cd /var/log/"
        assert extract_completion("cd /var/l", resp) == "cd /var/log/"

    def test_candidate_list_then_redraw_of_the_unchanged_prefix(self):
        # Ambiguous: the shell lists candidates and redraws what you already had.
        # Nothing to apply — and critically, the input must not be damaged.
        resp = "\r\n log1  log2  log3 \r\n root@target:/# cd /var/lo"
        assert extract_completion("cd /var/lo", resp) is None


class TestRefusals:
    """Every case where the honest answer is "leave the input alone"."""

    def test_no_response(self):
        assert extract_completion("ls", "") is None

    def test_empty_input(self):
        assert extract_completion("", "anything") is None

    def test_response_that_is_only_escapes(self):
        assert extract_completion("ls", "\x1b[K\x1b[0m") is None

    def test_bell_only_means_no_match(self):
        # A lone BEL is the shell saying "nothing matches". strip_ansi drops it,
        # leaving nothing to apply.
        assert extract_completion("ls /nosuch", "\x07") is None

    def test_multiline_reply_without_the_prefix_is_refused(self):
        # A candidate list with no redraw of our line: we cannot know what the
        # input should become, so we must not guess.
        resp = "\r\n alpha  beta  gamma \r\n"
        assert extract_completion("ls a", resp) is None

    def test_control_characters_are_never_typed_into_the_bar(self):
        # A cursor-position report or similar leaking through must not become input.
        resp = "me/\x08\x08"
        assert extract_completion("ls /ho", resp) is None


class TestTheInvariant:
    """The property the input bar's safety rests on, checked directly."""

    CASES = [
        ("ls /ho", "me/"),
        ("cd /var/l", "\r\x1b[Kroot@t:/# cd /var/log/"),
        ("cat READ", "ME.md\r\n"),
        ("ls", "\r\n a  b \r\n"),
        ("git che", "ckout "),
        ("x", "\x07"),
        ("systemctl re", "start "),
    ]

    def test_result_is_always_an_extension_of_what_was_typed(self):
        for typed, response in self.CASES:
            out = extract_completion(typed, response)
            if out is None:
                continue
            assert out.startswith(typed), (
                f"completion rewrote the user's input: {typed!r} -> {out!r}")
            assert len(out) >= len(typed), (
                f"completion shortened the user's input: {typed!r} -> {out!r}")

    def test_result_never_contains_control_characters(self):
        for typed, response in self.CASES:
            out = extract_completion(typed, response)
            if out is None:
                continue
            assert not any(ord(c) < 0x20 or ord(c) == 0x7f for c in out), (
                f"control character reached the input bar: {out!r}")
