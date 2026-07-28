from __future__ import annotations

import json
import threading
from types import SimpleNamespace
from unittest.mock import patch


def _models_with_tts(tts: dict) -> dict:
    from rau.providers.registry import _default_models

    models = _default_models()
    models["tts"] = tts
    return models


def test_model_validation_accepts_cartesia_sonic_35() -> None:
    from rau.providers.registry import _validated_models

    checked = _validated_models(
        _models_with_tts(
            {
                "provider": "cartesia",
                "voice_id": "voice-123",
                "model": "sonic-3.5",
                "preset": "custom",
                "effect": "none",
                "voice_settings": {
                    "stability": 0.5,
                    "similarity_boost": 0.75,
                    "style": 0.0,
                    "speed": 1.1,
                    "use_speaker_boost": True,
                },
            }
        )
    )

    assert checked["tts"]["provider"] == "cartesia"
    assert checked["tts"]["model"] == "sonic-3.5"


def test_cartesia_voice_mapping_exposes_only_picker_fields() -> None:
    from rau.voice import cartesia_api

    class Response:
        def raise_for_status(self) -> None:
            return None

        def json(self):
            return {
                "data": [
                    {
                        "id": "voice-123",
                        "name": "Calm Guide",
                        "description": "Measured and friendly",
                        "is_owner": True,
                        "gender": "feminine",
                        "language": "en",
                        "country": "US",
                        "private_embedding": "must not escape",
                    }
                ],
                "has_more": False,
            }

    client = SimpleNamespace(get=lambda *_args, **_kwargs: Response())
    with patch.object(cartesia_api, "_client", return_value=client):
        voices = cartesia_api.list_voices()

    assert voices == [
        {
            "id": "voice-123",
            "label": "Calm Guide",
            "category": "owned",
            "description": "Measured and friendly",
            "labels": {
                "gender": "feminine",
                "language": "en",
                "country": "US",
            },
        }
    ]


def test_cartesia_client_falls_back_when_http2_extra_is_missing() -> None:
    from rau.voice import cartesia_api

    created = []

    def client(**kwargs):
        created.append(kwargs)
        return SimpleNamespace(close=lambda: None)

    original_client = cartesia_api._http_client
    original_key = cartesia_api._http_client_key
    cartesia_api._http_client = None
    cartesia_api._http_client_key = ""
    try:
        with (
            patch.object(cartesia_api, "get_secret", return_value="key"),
            patch.object(cartesia_api, "find_spec", return_value=None),
            patch.object(cartesia_api.httpx, "Client", side_effect=client),
        ):
            cartesia_api._client()
    finally:
        cartesia_api._http_client = original_client
        cartesia_api._http_client_key = original_key

    assert created[0]["http2"] is False


def test_cartesia_http_stream_requests_pcm16_24k_and_speed() -> None:
    from rau.voice import cartesia_api

    seen = {}

    class Stream:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def raise_for_status(self) -> None:
            return None

        def iter_bytes(self):
            # HTTP chunk boundaries are not guaranteed to align to PCM16
            # samples; the adapter must carry the odd byte forward.
            yield b"\x01"
            yield b"\x00\x02"
            yield b"\x00"

    class Client:
        def stream(self, method, path, *, json):
            seen.update(method=method, path=path, payload=json)
            return Stream()

    with patch.object(cartesia_api, "_client", return_value=Client()):
        audio = b"".join(
            cartesia_api.stream_audio(
                text="Hello.",
                voice_id="voice-123",
                model="sonic-3.5",
                speed=1.1,
            )
        )

    assert audio == b"\x01\x00\x02\x00"
    assert seen["payload"]["model_id"] == "sonic-3.5"
    assert seen["payload"]["voice"] == {"id": "voice-123"}
    assert seen["payload"]["output_format"] == {
        "container": "raw",
        "encoding": "pcm_s16le",
        "sample_rate": 24000,
    }
    assert seen["payload"]["generation_config"]["speed"] == 1.1


def test_synth_sentence_routes_cartesia_without_elevenlabs_client() -> None:
    from rau.voice import cartesia_api, tts_stream

    with (
        patch.object(
            cartesia_api,
            "stream_audio",
            return_value=iter([b"\x03\x00" * 4]),
        ) as stream,
        patch.object(tts_stream, "_client", side_effect=AssertionError("wrong provider")),
    ):
        audio = b"".join(
            tts_stream.synth_sentence(
                "Hello.",
                provider="cartesia",
                voice_id="voice-123",
                model="sonic-3.5",
                voice_settings={"speed": 0.95},
            )
        )

    assert audio == b"\x03\x00" * 4
    assert stream.call_args.kwargs["speed"] == 0.95


def test_cartesia_realtime_context_uses_continuations_and_cancel() -> None:
    from rau.voice import tts_stream

    class Socket:
        def __init__(self):
            self.sent = []
            self.closed = threading.Event()

        def send(self, message):
            self.sent.append(json.loads(message))

        def recv(self):
            self.closed.wait(1)
            return None

        def close(self):
            self.closed.set()

    socket = Socket()
    with (
        patch.object(tts_stream, "get_secret", return_value="key"),
        patch("websockets.sync.client.connect", return_value=socket) as connect,
    ):
        session = tts_stream.RealtimeTtsSession()
        session.open_context(
            "turn-cartesia",
            provider="cartesia",
            voice_id="voice-123",
            model="sonic-3.5",
            voice_settings={"speed": 1.05},
        )
        session.text("turn-cartesia", "Hello. ", flush=True)
        session.close_context("turn-cartesia")
        session.close()

    assert connect.call_args.args[0] == "wss://api.cartesia.ai/tts/websocket"
    headers = connect.call_args.kwargs["additional_headers"]
    assert headers["X-API-Key"] == "key"
    assert headers["Cartesia-Version"] == "2026-03-01"
    generation, cancel = socket.sent
    assert generation["model_id"] == "sonic-3.5"
    assert generation["continue"] is True
    assert generation["flush"] is True
    assert generation["output_format"]["encoding"] == "pcm_s16le"
    assert generation["output_format"]["sample_rate"] == 24000
    assert generation["generation_config"]["speed"] == 1.05
    assert cancel == {"context_id": "turn-cartesia", "cancel": True}
