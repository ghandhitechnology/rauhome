from __future__ import annotations

import base64
import queue

import pytest

from rau.voice.pronunciation import normalize_for_tts
from rau.voice.tts_stream import speak_realtime_stream, synth_sentence


@pytest.mark.parametrize(
    ("written", "spoken"),
    [
        # distance, area, volume, mass
        ("Walk 5 km.", "Walk 5 kilometers."),
        ("Move it 1 cm.", "Move it 1 centimeter."),
        ("The gap is 3.5mm.", "The gap is 3.5 millimeters."),
        ("The gap is .5 mm.", "The gap is .5 millimeters."),
        ("It is 2 m wide.", "It is 2 meters wide."),
        ("A 10 m² room.", "A 10 square meters room."),
        ("Use 1 m3 of soil.", "Use 1 cubic meter of soil."),
        ("The trail is 2 mi.", "The trail is 2 miles."),
        ("Cut 12 in.", "Cut 12 inches."),
        ("Add 250 mL.", "Add 250 milliliters."),
        ("Use 1 tbsp.", "Use 1 tablespoon."),
        ("The bag is 20 kg.", "The bag is 20 kilograms."),
        ("Take 500 mg.", "Take 500 milligrams."),
        ("It weighs 2 lbs.", "It weighs 2 pounds."),
        # rates, time, frequency
        ("We reached 60 km/h.", "We reached 60 kilometers per hour."),
        ("It travels at 5 km/s.", "It travels at 5 kilometers per second."),
        ("Acceleration is 9.8 m/s².", "Acceleration is 9.8 meters per second squared."),
        ("The pace is 20 m·s⁻¹.", "The pace is 20 meters per second."),
        ("Wait 250 ms.", "Wait 250 milliseconds."),
        ("Wait 1 hr.", "Wait 1 hour."),
        ("The display runs at 120 Hz.", "The display runs at 120 hertz."),
        ("The motor turns at 3000 rpm.", "The motor turns at 3000 revolutions per minute."),
        ("Heart rate is 72 bpm.", "Heart rate is 72 beats per minute."),
        ("Video is 60 fps.", "Video is 60 frames per second."),
        ("The limit is 65 mph.", "The limit is 65 miles per hour."),
        # temperature, angles, science, medicine
        ("It is 25°C.", "It is 25 degrees Celsius."),
        ("It is 25 ℃.", "It is 25 degrees Celsius."),
        ("It is −5°C.", "It is −5 degrees Celsius."),
        ("Set it to 77°F.", "Set it to 77 degrees Fahrenheit."),
        ("Turn 45° left.", "Turn 45 degrees left."),
        ("The latitude is 37.5° N.", "The latitude is 37.5 degrees north."),
        ("The sample is 300 K.", "The sample is 300 kelvin."),
        ("Voltage is 12 V.", "Voltage is 12 volts."),
        ("Power draw is 1.5 kW.", "Power draw is 1.5 kilowatts."),
        ("Energy use was 20 kWh.", "Energy use was 20 kilowatt hours."),
        ("Battery capacity is 5000 mAh.", "Battery capacity is 5000 milliamp hours."),
        ("Pressure is 101.3 kPa.", "Pressure is 101.3 kilopascals."),
        ("Blood pressure was 120 mmHg.", "Blood pressure was 120 millimeters of mercury."),
        ("Glucose is 90 mg/dL.", "Glucose is 90 milligrams per deciliter."),
        ("Concentration is 400 ppm.", "Concentration is 400 parts per million."),
        ("The sound is 85 dB.", "The sound is 85 decibels."),
        ("Use a 10 kΩ resistor.", "Use a 10 kiloohms resistor."),
        # digital quantities
        ("The file is 5 MB.", "The file is 5 megabytes."),
        ("Memory is 16 GiB.", "Memory is 16 gibibytes."),
        ("The link is 100 Mbps.", "The link is 100 megabits per second."),
        ("Transfer at 10 MB/s.", "Transfer at 10 megabytes per second."),
        ("The icon is 24 px.", "The icon is 24 pixels."),
        ("Print at 300 dpi.", "Print at 300 dots per inch."),
        # money, percentages, dimensions, ranges, height
        ("It costs $1.", "It costs 1 dollar."),
        ("It costs €20.", "It costs 20 euros."),
        ("The valuation is $5m.", "The valuation is 5 million dollars."),
        ("Revenue reached $2.5bn.", "Revenue reached 2.5 billion dollars."),
        ("The price is ₩10,000.", "The price is 10,000 won."),
        ("Battery is at 85%.", "Battery is at 85 percent."),
        ("Use a 1920×1080 image.", "Use a 1920 by 1080 image."),
        ("It is 2x faster.", "It is 2 times faster."),
        ("Choose 3–5 items.", "Choose 3 to 5 items."),
        ("He is 5'10\" tall.", "He is 5 feet 10 inches tall."),
        # scientific notation and symbols
        ("Tolerance is 5 ± 0.2 mm.", "Tolerance is 5 plus or minus 0.2 millimeters."),
        ("Use ≤ 10 W.", "Use less than or equal to 10 watts."),
        ("The values are ≈ 3.", "The values are approximately 3."),
        ("The result is 1e-3.", "The result is 1 times ten to the minus 3."),
        ("Compute 10^3.", "Compute 10 to the 3 power."),
        ("See #5.", "See number 5."),
        # common formulas and explicit element labels
        ("Water is H2O.", "Water is water."),
        ("CO2 levels rose.", "carbon dioxide levels rose."),
        ("Use NaCl.", "Use sodium chloride."),
        ("O₂ is oxygen.", "oxygen is oxygen."),
        ("He (helium) is inert.", "helium is inert."),
        ("H(helium) was requested.", "helium was requested."),
        ("Element Fe is common.", "Element Fe is common."),
        # prose abbreviations
        ("Use warm colors, e.g. red.", "Use warm colors, for example red."),
        ("It is optional, i.e. not required.", "It is optional, that is not required."),
        ("Cats vs. dogs.", "Cats versus dogs."),
        ("ETA is 5 min.", "estimated time of arrival is 5 minutes."),
        ("Approx. 2 km remain.", "approximately 2 kilometers remain."),
        ("No. 7 is ready.", "number 7 is ready."),
        ("Salt & pepper.", "Salt and pepper."),
    ],
)
def test_daily_notation_is_pronounceable(written: str, spoken: str) -> None:
    assert normalize_for_tts(written) == spoken


@pytest.mark.parametrize(
    "text",
    [
        "He went home.",  # He must not become helium.
        "I am in a room.",  # in/m are ordinary words without a quantity.
        "Please use the cmake build.",  # unit substrings inside words.
        "Email 5km@example.com.",
        "Open https://example.com/maps/5km?x=25°C.",
        "Run `sleep 5s` now.",
        "Version 2.5.1 is current.",
    ],
)
def test_ambiguous_or_protected_text_is_not_rewritten(text: str) -> None:
    expected = text.replace("`", "")
    assert normalize_for_tts(text) == expected


def test_http_tts_boundary_receives_normalized_text() -> None:
    requests = []

    class _TextToSpeech:
        def stream(self, **request):
            requests.append(request)
            return iter([b"\x00\x00"])

    class _Client:
        text_to_speech = _TextToSpeech()

    assert list(
        synth_sentence(
            "Travel 5 km/s at 25°C.",
            client=_Client(),
            provider="elevenlabs",
            voice_id="voice",
            model="model",
        )
    ) == [b"\x00\x00"]
    assert requests[0]["text"] == (
        "Travel 5 kilometers per second at 25 degrees Celsius."
    )


def test_realtime_tts_boundary_normalizes_but_keeps_original_caption() -> None:
    sent = []
    captions = []
    pcm = b"\x00\x00" * 20

    class _Session:
        def __init__(self):
            self.messages = queue.Queue()

        def open_context(self, *_args, **_kwargs):
            return self.messages

        def text(self, _context_id, text, *, flush=False):
            sent.append((text, flush))
            self.messages.put(
                {
                    "audio": base64.b64encode(pcm).decode(),
                    "normalizedAlignment": {
                        "chars": list(text),
                        "char_start_times_ms": list(range(len(text))),
                    },
                }
            )

        def flush_context(self, _context_id):
            self.messages.put({"isFinal": True})

        def close_context(self, _context_id):
            return None

        def close(self):
            return None

    list(
        speak_realtime_stream(
            iter(["Travel 5 km/s at 25°C."]),
            on_audio=lambda _pcm: None,
            on_sentence=captions.append,
            session=_Session(),
        )
    )
    assert sent == [
        ("Travel 5 kilometers per second at 25 degrees Celsius. ", True)
    ]
    assert captions == ["Travel 5 km/s at 25°C."]
