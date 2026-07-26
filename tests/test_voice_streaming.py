"""
Getting the first word out, and the seams between the ones after it.

Nothing is audible until the opening chunk has been synthesised in full, so
every character that chunk waits for is silence the user sits through. These
tests pin the trade: the first fragment may break early, and nothing else may.
"""
import unittest

import numpy as np

from rau.voice.session import Utterance
from rau.voice.tts_stream import (
    FIRST_MIN_CHARS,
    MIN_CHARS,
    SR,
    SentenceBuffer,
    soften_edges,
)


def run(buffer: SentenceBuffer, text: str):
    """Feed `text` a word at a time, as a token stream would arrive."""
    out = []
    for word in text.split(" "):
        out += buffer.push(word + " ")
    tail = buffer.flush()
    if tail:
        out.append(tail)
    return out


class FirstChunkTests(unittest.TestCase):
    def test_a_long_opening_sentence_does_not_hold_everything_silent(self):
        chunks = run(
            SentenceBuffer(),
            "Right, so the thing about that is it really depends on what you mean.",
        )
        self.assertEqual(chunks[0], "Right,")
        # The whole point: the first thing sent to TTS is short.
        self.assertLess(len(chunks[0]), MIN_CHARS)

    def test_only_the_first_fragment_gets_that_licence(self):
        # After the opener, a clause break stops being a split point: later
        # chunks synthesise while earlier ones play, so their length is free
        # and phrasing wins. A chunk ending in a comma is a clause split.
        for text in (
            "Yes it is. Well, the second sentence here is quite long indeed.",
            "Right, so I looked. Then, later, we can look again at the whole thing.",
        ):
            chunks = run(SentenceBuffer(), text)
            for chunk in chunks[1:]:
                self.assertFalse(
                    chunk.endswith(","), f"split a later chunk at a clause: {chunk!r}"
                )

    def test_a_short_reply_is_left_whole(self):
        self.assertEqual(run(SentenceBuffer(), "Yes."), ["Yes."])
        self.assertEqual(run(SentenceBuffer(), "It is done."), ["It is done."])

    def test_a_stub_before_a_comma_is_not_worth_a_request(self):
        # "So," alone is a click, not a word, and costs a whole TTS call.
        chunks = run(SentenceBuffer(), "So, I had a look at the whole thing this morning.")
        self.assertNotEqual(chunks[0], "So,")

    def test_a_sentence_end_still_wins_over_a_clause_break(self):
        chunks = run(SentenceBuffer(), "That is right. Then, later on, we can look again.")
        self.assertEqual(chunks[0], "That is right.")

    def test_the_first_fragment_threshold_is_below_the_general_one(self):
        self.assertLess(FIRST_MIN_CHARS, MIN_CHARS)

    def test_a_reply_with_no_punctuation_at_all_still_streams(self):
        chunks = run(SentenceBuffer(), "yes " * 120)
        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(c.strip() for c in chunks))

    def test_every_word_survives_the_split(self):
        text = "Right, so I looked at it and the answer is that it depends. Sorry."
        rejoined = " ".join(run(SentenceBuffer(), text)).split()
        self.assertEqual(rejoined, text.split())


class EdgeFadeTests(unittest.TestCase):
    def _tone(self, ms: float, level: int = 20000) -> bytes:
        count = int(SR * ms / 1000.0)
        return (np.ones(count, dtype=np.int16) * level).tobytes()

    def test_both_ends_reach_zero_so_the_join_does_not_click(self):
        out = np.frombuffer(soften_edges(self._tone(100)), dtype=np.int16)
        self.assertEqual(out[0], 0)
        self.assertEqual(out[-1], 0)

    def test_the_middle_is_untouched(self):
        out = np.frombuffer(soften_edges(self._tone(100)), dtype=np.int16)
        self.assertEqual(out[len(out) // 2], 20000)

    def test_the_ramp_is_far_too_short_to_hear_as_a_fade(self):
        pcm = self._tone(100)
        out = np.frombuffer(soften_edges(pcm), dtype=np.int16)
        # Under 1% of a 100 ms clip at each end.
        touched = int(np.count_nonzero(out != 20000))
        self.assertLess(touched, out.size * 0.05)

    def test_the_length_never_changes(self):
        pcm = self._tone(50)
        self.assertEqual(len(soften_edges(pcm)), len(pcm))

    def test_a_clip_too_short_to_ramp_is_returned_untouched(self):
        tiny = self._tone(0.5)
        self.assertEqual(soften_edges(tiny), tiny)

    def test_malformed_audio_is_passed_through_rather_than_raising(self):
        self.assertEqual(soften_edges(b""), b"")
        self.assertEqual(soften_edges(b"\x01"), b"\x01")


class ReactionTimelineTests(unittest.TestCase):
    """
    A hesitation holds time but is not speech.

    Both halves matter. If it does not hold time, every caption and every barge
    offset after it is wrong by its duration. If it counts as speech, the model
    is told it said "hmm" and will answer as though it had.
    """

    def _pcm(self, ms: float) -> bytes:
        return b"\x00\x00" * int(SR * ms / 1000.0)

    def test_the_sentence_after_it_starts_where_the_audio_actually_starts(self):
        utterance = Utterance()
        utterance.add("", self._pcm(600))
        chunk = utterance.add("Right, here is the answer.", self._pcm(1000))
        self.assertAlmostEqual(chunk.start_ms, 600, delta=1)

    def test_it_is_never_reported_as_something_he_said(self):
        utterance = Utterance()
        utterance.add("", self._pcm(600))
        utterance.add("Here is the answer.", self._pcm(1000))
        self.assertEqual(utterance.heard_text(2000), "Here is the answer.")

    def test_a_reply_cut_off_during_the_hesitation_reports_nothing_heard(self):
        utterance = Utterance()
        utterance.add("", self._pcm(600))
        utterance.add("Here is the answer.", self._pcm(1000))
        self.assertEqual(utterance.heard_text(200), "")

    def test_two_hesitations_are_not_merged_into_one_the_way_sentences_are(self):
        # Repeated-text merging exists for the many PCM fragments of one
        # sentence; two empty-text clips are not one clip.
        utterance = Utterance()
        utterance.add("", self._pcm(100))
        utterance.add("", self._pcm(100))
        self.assertEqual(len(utterance.chunks), 2)

    def test_a_repeated_sentence_still_merges(self):
        utterance = Utterance()
        utterance.add("One.", self._pcm(100))
        utterance.add("One.", self._pcm(100))
        self.assertEqual(len(utterance.chunks), 1)
        self.assertAlmostEqual(utterance.total_ms, 200, delta=1)


if __name__ == "__main__":
    unittest.main()
