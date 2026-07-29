"""Generated, locale-aware presence nudges with a two-message silence cap."""

from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from rau import state
from rau.heartbeat import presence
from rau.providers.base import ChatResult


class PresenceNudgeTimingTests(unittest.TestCase):
    def setUp(self) -> None:
        presence.end_user_turn()
        state.set_listening(True)
        state.set_face_busy(False)
        state.update_presence(
            last_user_ts=0.0,
            last_initiate_ts=0.0,
            last_nudge_attempt_ts=0.0,
            nudge_count=0,
            muted_until=0.0,
            heartbeat_events=[],
        )

    def tearDown(self) -> None:
        presence.end_user_turn()
        state.update_presence(
            last_user_ts=0.0,
            last_initiate_ts=0.0,
            last_nudge_attempt_ts=0.0,
            nudge_count=0,
            muted_until=0.0,
            heartbeat_events=[],
        )

    def test_first_at_twelve_minutes_second_an_hour_later_then_silent(self) -> None:
        base = 1_700_000_000.0
        state.update_presence(last_user_ts=base)
        with mock.patch.object(presence, "_runtime_allows_nudge", return_value=True):
            self.assertFalse(presence.can_initiate(base + presence.FIRST_NUDGE_SEC - 1))
            self.assertTrue(presence.can_initiate(base + presence.FIRST_NUDGE_SEC))

            first = base + presence.FIRST_NUDGE_SEC
            state.update_presence(
                nudge_count=1,
                last_initiate_ts=first,
                last_nudge_attempt_ts=first,
            )
            self.assertFalse(
                presence.can_initiate(first + presence.SECOND_NUDGE_SEC - 1)
            )
            self.assertTrue(presence.can_initiate(first + presence.SECOND_NUDGE_SEC))

            state.update_presence(nudge_count=2)
            self.assertFalse(
                presence.can_initiate(first + 2 * presence.SECOND_NUDGE_SEC)
            )

    def test_failed_attempt_retries_after_five_minutes(self) -> None:
        now = 1_700_000_000.0
        state.update_presence(
            last_user_ts=now - presence.FIRST_NUDGE_SEC,
            last_nudge_attempt_ts=now,
        )
        with mock.patch.object(presence, "_runtime_allows_nudge", return_value=True):
            self.assertFalse(presence.can_initiate(now + presence.NUDGE_RETRY_SEC - 1))
            self.assertTrue(presence.can_initiate(now + presence.NUDGE_RETRY_SEC))

    def test_user_contact_resets_the_allowance(self) -> None:
        state.update_presence(
            last_user_ts=10.0,
            last_initiate_ts=20.0,
            last_nudge_attempt_ts=30.0,
            nudge_count=2,
        )
        with (
            mock.patch.object(presence, "begin_user_turn"),
            mock.patch.object(presence, "save_presence"),
            mock.patch.object(presence.time, "time", return_value=100.0),
        ):
            presence.note_user_reply()
        current = state.presence()
        self.assertEqual(current["last_user_ts"], 100.0)
        self.assertEqual(current["nudge_count"], 0)
        self.assertEqual(current["last_initiate_ts"], 0.0)
        self.assertEqual(current["last_nudge_attempt_ts"], 0.0)


class PresenceNudgeGenerationTests(unittest.TestCase):
    def setUp(self) -> None:
        presence.end_user_turn()
        state.set_listening(True)
        state.set_face_busy(False)
        state.update_presence(
            last_user_ts=time.time() - presence.FIRST_NUDGE_SEC - 10,
            last_initiate_ts=0.0,
            last_nudge_attempt_ts=0.0,
            nudge_count=0,
            muted_until=0.0,
            heartbeat_events=[],
        )

    def tearDown(self) -> None:
        presence.end_user_turn()
        state.update_presence(
            last_user_ts=0.0,
            last_initiate_ts=0.0,
            last_nudge_attempt_ts=0.0,
            nudge_count=0,
            muted_until=0.0,
            heartbeat_events=[],
        )

    def _common_patches(self):
        return (
            mock.patch("rau.permissions.heartbeat_nudge_allowed", return_value=True),
            mock.patch.object(presence, "_runtime_allows_nudge", return_value=True),
            mock.patch("rau.language.get_locale", return_value="en"),
            mock.patch.object(presence, "save_presence"),
        )

    def test_success_records_and_queues_one_generated_line(self) -> None:
        permission, runtime, locale, save = self._common_patches()
        with (
            permission,
            runtime,
            locale,
            save,
            mock.patch.object(
                presence, "_generate_nudge", return_value="Want to pick this up again?"
            ) as generate,
            mock.patch.object(presence.BUS, "emit") as emit,
            mock.patch.object(state, "push_control") as push,
        ):
            presence.maybe_nudge()

        self.assertEqual(state.presence()["nudge_count"], 1)
        generate.assert_called_once()
        emit.assert_called_once()
        self.assertEqual(emit.call_args.kwargs["locale"], "en")
        command = push.call_args.args[0]
        self.assertEqual(command["action"], "presence_speak")
        self.assertEqual(command["text"], "Want to pick this up again?")

    def test_provider_failure_stays_silent_and_does_not_consume_quota(self) -> None:
        permission, runtime, locale, save = self._common_patches()
        with (
            permission,
            runtime,
            locale,
            save,
            mock.patch.object(
                presence, "_generate_nudge", side_effect=RuntimeError("offline")
            ),
            mock.patch.object(presence.BUS, "emit") as emit,
            mock.patch.object(state, "push_control") as push,
        ):
            presence.maybe_nudge()

        current = state.presence()
        self.assertEqual(current["nudge_count"], 0)
        self.assertGreater(current["last_nudge_attempt_ts"], 0)
        emit.assert_not_called()
        push.assert_not_called()

    def test_user_return_during_generation_discards_stale_output(self) -> None:
        original_last_user = state.presence()["last_user_ts"]

        def generate(**_kwargs):
            state.update_presence(last_user_ts=original_last_user + 1, nudge_count=0)
            return "This is stale."

        permission, runtime, locale, save = self._common_patches()
        with (
            permission,
            runtime,
            locale,
            save,
            mock.patch.object(presence, "_generate_nudge", side_effect=generate),
            mock.patch.object(presence.BUS, "emit") as emit,
            mock.patch.object(state, "push_control") as push,
        ):
            presence.maybe_nudge()

        self.assertEqual(state.presence()["nudge_count"], 0)
        emit.assert_not_called()
        push.assert_not_called()

    def test_korean_prompt_and_output_use_the_active_locale(self) -> None:
        class Provider:
            def __init__(self) -> None:
                self.messages = []

            def chat(self, messages, **_kwargs):
                self.messages = messages
                return ChatResult(content="잠깐 쉬었다가 다시 이야기할래요?")

        provider = Provider()
        with (
            mock.patch.object(
                presence, "chat_for_slot", return_value=(provider, {"model": "face"})
            ),
            mock.patch(
                "rau.identity.store.load_soul", return_value="# Soul\nI am Rau."
            ),
            mock.patch(
                "rau.language.response_language_instruction",
                return_value="Always speak and reply in natural Korean.",
            ),
            mock.patch.object(presence, "recent_context", return_value=""),
        ):
            line = presence._generate_nudge(
                gap=presence.FIRST_NUDGE_SEC,
                count=0,
                locale="ko",
                last_user=1.0,
            )

        self.assertEqual(line, "잠깐 쉬었다가 다시 이야기할래요?")
        prompt = "\n".join(message.content for message in provider.messages)
        self.assertIn("Always speak and reply in natural Korean.", prompt)
        self.assertIn("Active locale: ko", prompt)

    def test_wrong_language_or_malformed_output_is_rejected(self) -> None:
        self.assertEqual(presence._clean_nudge("Still here?", "ko"), "")
        self.assertEqual(
            presence._clean_nudge("다시 이야기할까요?", "ko"), "다시 이야기할까요?"
        )
        self.assertEqual(presence._clean_nudge("다시 이야기할까요?", "en"), "")
        self.assertEqual(presence._clean_nudge("one line\nsecond line", "en"), "")


class PresenceNudgePersistenceTests(unittest.TestCase):
    def tearDown(self) -> None:
        state.update_presence(
            last_user_ts=0.0,
            last_initiate_ts=0.0,
            last_nudge_attempt_ts=0.0,
            nudge_count=0,
            heartbeat_events=[],
        )

    def test_quota_round_trips_and_old_files_default_to_zero(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "presence.json"
            with mock.patch.object(presence, "PRESENCE_FILE", path):
                state.update_presence(
                    last_user_ts=100.0,
                    last_initiate_ts=200.0,
                    last_nudge_attempt_ts=190.0,
                    nudge_count=1,
                )
                presence.save_presence()
                state.update_presence(
                    last_initiate_ts=0.0,
                    last_nudge_attempt_ts=0.0,
                    nudge_count=0,
                )
                presence.load_presence()
                current = state.presence()
                self.assertEqual(current["nudge_count"], 1)
                self.assertEqual(current["last_initiate_ts"], 200.0)
                self.assertEqual(current["last_nudge_attempt_ts"], 190.0)

                path.write_text('{"last_user_ts": 100.0}', encoding="utf-8")
                state.update_presence(
                    last_initiate_ts=200.0,
                    last_nudge_attempt_ts=190.0,
                    nudge_count=2,
                )
                presence.load_presence()
                current = state.presence()
                self.assertEqual(current["nudge_count"], 0)
                self.assertEqual(current["last_initiate_ts"], 0.0)
                self.assertEqual(current["last_nudge_attempt_ts"], 0.0)


class PresenceControlGuardTests(unittest.TestCase):
    def test_stale_presence_control_never_speaks(self) -> None:
        from rau.face import pipeline

        command = {
            "action": "presence_speak",
            "text": "stale",
            "last_user_ts": 1.0,
            "locale": "en",
        }
        with (
            mock.patch(
                "rau.heartbeat.presence.presence_speech_is_current",
                return_value=False,
            ),
            mock.patch.object(pipeline, "speak") as speak,
        ):
            pipeline._handle_control(command)
        speak.assert_not_called()


if __name__ == "__main__":
    unittest.main()
