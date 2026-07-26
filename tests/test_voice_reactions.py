"""
The hesitations Rau makes while thinking.

Two things matter and neither is "does it play a sound". It must be *varied* —
a filler that repeats stops reading as thought within a few turns — and it must
never be able to hurt a turn, because it is decoration in front of the only
part the user actually asked for.
"""
import threading
import unittest
from collections import Counter
from unittest import mock

from rau.voice import reactions
from rau.voice.reactions import FAMILIES, ReactionPool, classify


class ChoiceVarietyTests(unittest.TestCase):
    def test_never_says_the_same_thing_twice_running(self):
        pool = ReactionPool(seed=7)
        previous = ""
        for _ in range(400):
            text = pool.choose("thinking")
            self.assertNotEqual(text, previous, "a filler repeated back to back")
            previous = text

    def test_works_through_the_whole_pool_before_repeating_any_of_it(self):
        # The point of a bag over random.choice: with choice, ten draws from a
        # ten-item pool would touch about six of them.
        pool = ReactionPool(seed=3)
        distinct = {r.text for r in FAMILIES["thinking"]}
        drawn = {pool.choose("thinking") for _ in range(len(reactions._expand(FAMILIES["thinking"])))}
        self.assertEqual(drawn, distinct)

    def test_the_order_changes_between_passes(self):
        pool = ReactionPool(seed=11)
        size = len(reactions._expand(FAMILIES["thinking"]))
        first = [pool.choose("thinking") for _ in range(size)]
        second = [pool.choose("thinking") for _ in range(size)]
        self.assertNotEqual(first, second, "the bag deals the same order every pass")

    def test_weights_are_honoured_without_starving_anything(self):
        pool = ReactionPool(seed=5)
        counts = Counter(pool.choose("thinking") for _ in range(2000))
        for reaction in FAMILIES["thinking"]:
            self.assertGreater(counts[reaction.text], 0, f"{reaction.text} never played")
        self.assertGreater(counts["Hmm."], counts["Mm…"], "weight had no effect")

    def test_each_family_keeps_its_own_place_in_the_rotation(self):
        pool = ReactionPool(seed=2)
        self.assertIn(pool.choose("searching"), {r.text for r in FAMILIES["searching"]})
        self.assertIn(pool.choose("acknowledging"), {r.text for r in FAMILIES["acknowledging"]})

    def test_an_unknown_family_falls_back_rather_than_going_silent(self):
        pool = ReactionPool(seed=1)
        self.assertIn(pool.choose("nonsense"), {r.text for r in FAMILIES["thinking"]})


class ClassifyTests(unittest.TestCase):
    def test_a_short_remark_only_wants_acknowledging(self):
        self.assertEqual(classify("thanks"), "acknowledging")
        self.assertEqual(classify("okay sure"), "acknowledging")

    def test_an_opinion_question_gets_a_considering_beat(self):
        self.assertEqual(classify("why do you think that happened?"), "considering")
        self.assertEqual(classify("what do you think about it?"), "considering")

    def test_a_pending_tool_says_so_rather_than_just_hesitating(self):
        self.assertEqual(classify("look up the weather", tool_expected=True), "searching")

    def test_anything_else_takes_the_safe_default(self):
        self.assertEqual(classify("tell me how the deploy went yesterday"), "thinking")
        self.assertEqual(classify(""), "thinking")


class AudioTests(unittest.TestCase):
    def setUp(self):
        self.pool = ReactionPool(seed=1)

    def _voice(self):
        return mock.patch.object(
            ReactionPool,
            "_current_voice",
            return_value=reactions._Voice("v", "m", "none"),
        )

    def test_a_synthesised_clip_is_cached_rather_than_refetched(self):
        with self._voice(), mock.patch.object(
            ReactionPool, "_load_from_disk", return_value=None
        ), mock.patch.object(ReactionPool, "_save_to_disk"), mock.patch.object(
            ReactionPool, "_synthesise", return_value=b"\x01\x02"
        ) as synth:
            self.assertEqual(self.pool.audio("Hmm."), b"\x01\x02")
            self.assertEqual(self.pool.audio("Hmm."), b"\x01\x02")
        self.assertEqual(synth.call_count, 1, "the clip was synthesised twice")

    def test_a_changed_voice_throws_the_cache_away(self):
        # A hesitation in the old voice in front of a reply in the new one is
        # worse than no hesitation at all.
        with mock.patch.object(ReactionPool, "_load_from_disk", return_value=None), \
             mock.patch.object(ReactionPool, "_save_to_disk"), \
             mock.patch.object(ReactionPool, "_synthesise", return_value=b"\x01\x02") as synth:
            with mock.patch.object(
                ReactionPool, "_current_voice", return_value=reactions._Voice("a", "m", "none")
            ):
                self.pool.audio("Hmm.")
            with mock.patch.object(
                ReactionPool, "_current_voice", return_value=reactions._Voice("b", "m", "none")
            ):
                self.pool.audio("Hmm.")
        self.assertEqual(synth.call_count, 2)

    def test_a_failed_synthesis_is_silence_rather_than_an_exception(self):
        with self._voice(), mock.patch.object(
            ReactionPool, "_load_from_disk", return_value=None
        ), mock.patch.object(ReactionPool, "_save_to_disk"), mock.patch.object(
            ReactionPool, "_synthesise", side_effect=RuntimeError("no key")
        ):
            with self.assertRaises(RuntimeError):
                self.pool.audio("Hmm.")

    def test_a_provider_failure_inside_synthesis_yields_no_audio(self):
        with self._voice(), mock.patch(
            "rau.voice.tts_stream.synth_sentence", side_effect=RuntimeError("boom")
        ), mock.patch.object(ReactionPool, "_load_from_disk", return_value=None):
            self.assertEqual(self.pool.audio("Hmm."), b"")

    def test_a_runaway_clip_is_discarded_rather_than_played(self):
        from rau.voice.tts_stream import MAX_REACTION_BYTES

        essay = [b"\x00" * (MAX_REACTION_BYTES + 2)]
        with self._voice(), mock.patch(
            "rau.voice.tts_stream.synth_sentence", return_value=iter(essay)
        ), mock.patch.object(ReactionPool, "_load_from_disk", return_value=None):
            self.assertEqual(self.pool.audio("Hmm."), b"")

    def test_a_truncated_cache_file_is_ignored(self):
        # An odd byte count is half a sample, which reads back as a click.
        with self._voice(), mock.patch.object(
            reactions.Path, "is_file", return_value=True
        ), mock.patch.object(reactions.Path, "read_bytes", return_value=b"\x01"):
            self.assertIsNone(self.pool._load_from_disk("Hmm.", reactions._Voice("v", "m", "none")))

    def test_empty_text_asks_for_nothing(self):
        self.assertEqual(self.pool.audio(""), b"")

    def test_choosing_is_safe_from_several_threads(self):
        pool = ReactionPool(seed=4)
        seen = []
        lock = threading.Lock()

        def draw():
            for _ in range(100):
                text = pool.choose("thinking")
                with lock:
                    seen.append(text)

        threads = [threading.Thread(target=draw) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(len(seen), 400)
        self.assertTrue(all(seen))


if __name__ == "__main__":
    unittest.main()
