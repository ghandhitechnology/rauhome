from __future__ import annotations

from unittest.mock import patch

from rau import language


def test_locale_normalization_is_closed_to_the_supported_pair():
    assert language.normalize_locale("ko") == "ko"
    assert language.normalize_locale("EN") == "en"
    assert language.normalize_locale("fr") == "en"


def test_language_preference_is_persisted_without_losing_other_settings():
    with (
        patch("rau.language.load_settings", return_value={"resource_profile": "eco"}),
        patch("rau.language.save_settings") as save,
    ):
        assert language.set_locale("ko") == {"language": "ko"}
    save.assert_called_once_with({"resource_profile": "eco", "language": "ko"})


def test_strict_korean_instruction_covers_conversation_and_exceptions():
    with patch("rau.language.get_locale", return_value="ko"):
        prompt = language.response_language_instruction()
    assert "Always speak and reply in natural Korean" in prompt
    assert "code, commands" in prompt
    assert "Do not switch to English" in prompt


def test_game_banter_inherits_the_selected_language():
    from rau.games.kittens import banter

    with patch(
        "rau.language.response_language_instruction",
        return_value="Always answer in Korean.",
    ):
        # A minimal table object is enough because the view function is isolated
        # here; this test is about the separate player-model prompt.
        with patch(
            "rau.games.kittens.view.talker_fragment",
            return_value="The table is quiet.",
        ):
            prompt = banter._prompt(object(), "idle")  # noqa: SLF001
    assert "Always answer in Korean." in prompt
