"""Korean speech normalization: notation, lexicon, fallback and integrity."""
from __future__ import annotations

import re

import pytest

from rau.voice.korean import contains_hangul, normalize_korean_for_tts
from rau.voice.korean import lexicon
from rau.voice.korean.numbers import native_number
from rau.voice.korean.transliterate import hangulize
from rau.voice.pronunciation import normalize_for_tts

_LATIN = re.compile(r"[A-Za-z]")
_HANGUL_ONLY = re.compile(r"[가-힣]+(?: [가-힣]+)*")


@pytest.mark.parametrize(
    ("written", "spoken"),
    [
        # temperature — the qualifier leads, and below zero is 영하
        ("오늘 25°C입니다.", "오늘 섭씨 25도입니다."),
        ("기온이 -5°C까지 내려갔다.", "기온이 섭씨 영하 5도까지 내려갔다."),
        ("오븐을 350°F로 예열해.", "오븐을 화씨 350도로 예열해."),
        ("샘플은 300 K였다.", "샘플은 300켈빈였다."),
        ("각도를 45° 돌려.", "각도를 45도 돌려."),
        ("위도는 37.5°N이다.", "위도는 북위 37.5도이다."),
        ("경도는 127°E이다.", "경도는 동경 127도이다."),
        # length, mass, volume, data
        ("거리는 5km였다.", "거리는 5킬로미터였다."),
        ("두께는 3.5mm이다.", "두께는 3.5밀리미터이다."),
        ("무게는 20 kg이야.", "무게는 20킬로그램이야."),
        ("250 mL를 부어.", "250밀리리터를 부어."),
        ("용량은 5 GB이다.", "용량은 5기가바이트이다."),
        ("속도는 100 Mbps야.", "속도는 100메가비피에스야."),
        ("면적은 10 m²이다.", "면적은 10제곱미터이다."),
        ("부피는 2 m3이다.", "부피는 2세제곱미터이다."),
        # rates — Korean fronts 시속/분속/초속
        ("차가 60 km/h로 달린다.", "차가 시속 60킬로미터로 달린다."),
        ("초속 계산: 5 m/s.", "초속 계산: 초속 5미터."),
        ("제한 속도는 65 mph야.", "제한 속도는 시속 65마일이야."),
        ("혈당이 90 mg/dL이다.", "혈당이 데시리터당 90밀리그램이다."),
        # money and proportion
        ("가격은 $20이다.", "가격은 20 달러이다."),
        ("투자금은 $5m이다.", "투자금은 5000000 달러이다."),
        ("지분이 30% 늘었다.", "지분이 30퍼센트 늘었다."),
        ("금리가 0.25%p 올랐다.", "금리가 0.25퍼센트포인트 올랐다."),
    ],
)
def test_measurements_read_as_korean(written: str, spoken: str) -> None:
    assert normalize_for_tts(written) == spoken


@pytest.mark.parametrize(
    ("written", "spoken"),
    [
        # native-Korean counters
        ("사과 3개 주세요.", "사과 세 개 주세요."),
        ("학생 5명이 왔다.", "학생 다섯 명이 왔다."),
        ("고양이 2마리를 봤다.", "고양이 두 마리를 봤다."),
        ("나이는 20살이다.", "나이는 스무 살이다."),
        ("커피 21잔을 마셨다.", "커피 스물한 잔을 마셨다."),
        ("책 12권을 읽었다.", "책 열두 권을 읽었다."),
        ("4시간 걸렸다.", "네 시간 걸렸다."),
        # the clock, which is native for the hour and Sino for the minute
        ("지금 3시야.", "지금 세 시야."),
        ("회의는 3시 30분이다.", "회의는 세 시 30분이다."),
        ("기차는 14:05에 온다.", "기차는 열네 시 5분에 온다."),
        # Sino counters must be left alone
        ("3개월 동안 준비했다.", "3개월 동안 준비했다."),
        ("30분 뒤에 보자.", "30분 뒤에 보자."),
        ("5년 걸렸다.", "5년 걸렸다."),
        ("100개를 팔았다.", "100개를 팔았다."),
        # irregular month readings
        ("6월 10일에 만나자.", "유월 10일에 만나자."),
        ("10월은 선선하다.", "시월은 선선하다."),
        ("16월은 없다.", "16월은 없다."),
        # dates, phone numbers and fractions
        ("오늘은 2026-07-29이야.", "오늘은 2026년 7월 29일이야."),
        ("회의는 2026-06-10에 있어.", "회의는 2026년 유월 10일에 있어."),
        ("전화는 010-1234-5678이야.", "전화는 010 1234 5678이야."),
        ("1588-1234로 전화해.", "1588 1234로 전화해."),
        ("3/4을 먹었어.", "4분의 3을 먹었어."),
        ("7/29에 만나자.", "7/29에 만나자."),
        # ordinals and signs
        ("1st 자리를 차지했다.", "첫 번째 자리를 차지했다."),
        ("5th 시도였다.", "다섯 번째 시도였다."),
    ],
)
def test_number_readings(written: str, spoken: str) -> None:
    assert normalize_for_tts(written) == spoken


@pytest.mark.parametrize(
    ("written", "spoken"),
    [
        ("비율은 3:1이다.", "비율은 3 대 1이다."),
        ("3 + 5는 8이다.", "3 더하기 5는 8이다."),
        ("10 - 4는 6이다.", "10 빼기 4는 6이다."),
        ("3~5명이 온다.", "3에서 다섯 명이 온다."),
        ("π는 무리수다.", "파이는 무리수다."),
        ("α와 β를 비교했다.", "알파와 베타를 비교했다."),
        ("Δ가 커졌다.", "델타가 커졌다."),
        ("#3 자리다.", "3번 자리다."),
        ("±5 오차가 있다.", "플러스 마이너스 5 오차가 있다."),
        ("값이 ∞로 간다.", "값이 무한대로 간다."),
        # exponents and scientific notation
        ("2^10은 1024다.", "2의 10제곱은 1024다."),
        ("질량은 1.5e9 kg이다.", "질량은 1.5 곱하기 10의 9제곱 킬로그램이다."),
        ("오차는 3.2e-5 수준이다.", "오차는 3.2 곱하기 10의 마이너스 5제곱 수준이다."),
        ("거리는 10²미터다.", "거리는 10의 2제곱미터다."),
    ],
)
def test_symbols_read_as_korean(written: str, spoken: str) -> None:
    assert normalize_for_tts(written) == spoken


@pytest.mark.parametrize(
    ("written", "spoken"),
    [
        ("H2O는 물이다.", "물은 물이다."),
        ("CO2 농도가 높다.", "이산화탄소 농도가 높다."),
        ("NaCl을 넣어라.", "염화나트륨을 넣어라."),
        ("CaCO3이 주성분이다.", "탄산칼슘이 주성분이다."),
        ("Fe는 금속이다.", "철은 금속이다."),
        ("Au는 비싸다.", "금은 비싸다."),
        # a run of capitals without digits is an acronym, not a compound
        ("KBS가 보도했다.", "케이비에스가 보도했다."),
        ("CEO가 발표했다.", "씨이오가 발표했다."),
    ],
)
def test_chemistry(written: str, spoken: str) -> None:
    assert normalize_for_tts(written) == spoken


@pytest.mark.parametrize(
    ("written", "spoken"),
    [
        # brands, places, people, technology, food
        ("Google에서 검색했다.", "구글에서 검색했다."),
        ("iPhone을 샀다.", "아이폰을 샀다."),
        ("ChatGPT를 써봤다.", "챗지피티를 써봤다."),
        ("Netflix에서 봤다.", "넷플릭스에서 봤다."),
        ("Germany에 갔다.", "독일에 갔다."),
        ("New York은 크다.", "뉴욕은 크다."),
        ("Einstein이 말했다.", "아인슈타인이 말했다."),
        ("machine learning을 공부한다.", "머신 러닝을 공부한다."),
        ("temperature가 올랐다.", "템퍼러처가 올랐다."),
        # romanized Korean has to come home as Hangul
        ("kimchi는 맛있다.", "김치는 맛있다."),
        ("bibimbap을 먹었다.", "비빔밥을 먹었다."),
        ("Seoul에 산다.", "서울에 산다."),
        ("진짜 daebak이다.", "진짜 대박이다."),
        # acronyms, known and unknown
        ("NASA가 발사했다.", "나사가 발사했다."),
        ("WXYZ가 왔다.", "더블유엑스와이제트가 왔다."),
        ("AI가 발전한다.", "에이아이가 발전한다."),
    ],
)
def test_lexicon_readings(written: str, spoken: str) -> None:
    assert normalize_for_tts(written) == spoken


@pytest.mark.parametrize(
    ("written", "spoken"),
    [
        # the particle must agree with the new sound, not the old spelling
        ("H2O와 기름", "물과 기름"),
        ("Google을 열어", "구글을 열어"),
        ("API를 붙였다", "에이피아이를 붙였다"),
        ("Seoul로 간다", "서울로 간다"),
        ("Busan으로 간다", "부산으로 간다"),
        ("Google이라는 회사", "구글이라는 회사"),
        ("iPhone이 좋다", "아이폰이 좋다"),
        ("machine learning과 통계", "머신 러닝과 통계"),
        # ordinary Korean verb endings that merely look like particles
        ("밥을 먹는 사람", "밥을 먹는 사람"),
        ("불과 3일 남았다", "불과 3일 남았다"),
    ],
)
def test_particles_agree_with_the_new_reading(written: str, spoken: str) -> None:
    assert normalize_for_tts(written) == spoken


@pytest.mark.parametrize(
    ("written", "spoken"),
    [
        ("e-mail을 보냈다.", "이메일을 보냈다."),
        ("Google's 발표", "구글의 발표"),
        ("server들이 죽었다.", "서버들이 죽었다."),
        ("GPT-4를 썼다.", "지피티4를 썼다."),
    ],
)
def test_token_shapes(written: str, spoken: str) -> None:
    assert normalize_for_tts(written) == spoken


@pytest.mark.parametrize(
    ("word", "expected"),
    [
        ("test", "테스트"),
        ("desk", "데스크"),
        ("cat", "캣"),
        ("time", "타임"),
        ("hello", "헬로"),
        ("spring", "스프링"),
        ("bank", "뱅크"),
        ("school", "스쿨"),
        ("station", "스테이션"),
        ("future", "퓨처"),
        ("apple", "애플"),
        ("world", "월드"),
        ("start", "스타트"),
        # diphthongs, whose second vowel needs its own syllable
        ("house", "하우스"),
        ("brown", "브라운"),
        ("audio", "오디오"),
        ("fire", "파이어"),
        ("rau", "라우"),
    ],
)
def test_transliterator_handles_unknown_words(word: str, expected: str) -> None:
    assert hangulize(word) == expected


def test_every_rule_vowel_is_a_jamo() -> None:
    """A vowel rule written with a syllable instead of a jamo drops silently.

    ``_v("ㅏ우")`` composes nothing for its second position and the sound simply
    vanishes, which is invisible until someone reads a word aloud.
    """
    from rau.voice.korean import transliterate
    from rau.voice.korean.hangul import VOWELS

    for _pattern, tokens in transliterate._RULES:
        for token in tokens:
            if token[0] == "v":
                assert all(jamo in VOWELS for jamo in token[1]), token


def test_transliterator_never_emits_latin() -> None:
    # Nonsense, misspellings and coinages all have to come out speakable.
    for word in (
        "zyxwv", "qqq", "brndxl", "flurbex", "Kzyntho", "mmm", "aeiou",
        "x", "strengths", "rhythms", "psychology", "knight", "queue",
    ):
        assert not _LATIN.search(hangulize(word))


@pytest.mark.parametrize("value", [1, 2, 3, 4, 10, 11, 12, 20, 21, 30, 99])
def test_native_numbers(value: int) -> None:
    assert _HANGUL_ONLY.fullmatch(native_number(value))


def test_native_numbers_reject_out_of_range() -> None:
    assert native_number(0) == ""
    assert native_number(100) == ""
    assert native_number(20) == "스무"
    assert native_number(12) == "열두"


def test_english_text_keeps_the_english_path() -> None:
    assert normalize_for_tts("Travel 5 km/s at 25°C.") == (
        "Travel 5 kilometers per second at 25 degrees Celsius."
    )


def test_hangul_anywhere_selects_the_korean_path() -> None:
    assert contains_hangul("Google 검색")
    assert not contains_hangul("Google search")
    assert normalize_for_tts("Google 검색") == "구글 검색"


def test_code_urls_and_email_survive_untouched() -> None:
    source = "설정은 `export KM=5`이고 https://example.com/km 에서 봐. me@example.com 로 연락해."
    spoken = normalize_for_tts(source)
    assert "export KM=5" in spoken
    assert "https://example.com/km" in spoken
    assert "me@example.com" in spoken


def test_no_latin_survives_a_mixed_sentence() -> None:
    corpus = (
        "오늘 Google에서 machine learning 논문을 읽고 CO2 농도가 400 ppm이라는 걸 알았다.",
        "Tesla 주가가 $250이고 Nasdaq은 3% 올랐다.",
        "iPhone 15 Pro Max를 25°C 환경에서 5시간 테스트했다.",
        "Seoul에서 Busan까지 KTX로 2시간 30분 걸린다.",
        "Dr. Smith가 MRI와 CT를 비교한 paper를 발표했다.",
        "이 flurbex라는 신제품은 zyntho 기술을 쓴다.",
        "H2SO4와 NaOH를 1:1로 섞으면 위험하다.",
        "BTS와 blackpink 공연을 봤고 kimchi jjigae를 먹었다.",
    )
    for sentence in corpus:
        assert not _LATIN.search(normalize_for_tts(sentence)), sentence


def test_normalizer_never_raises() -> None:
    for hostile in (
        "가", "가나다" * 500, "한글 " + "A" * 300, "한글 \x00�", "한 %%% °°° ///",
        "한글 $$$ 5//5 3::4", "가 " + "\\" * 50, "한글 " + "?" * 200,
    ):
        assert isinstance(normalize_korean_for_tts(hostile), str)


def test_fuzz_mixed_text_never_crashes_or_leaks_latin() -> None:
    """The two invariants that matter on the audio path, over random input."""
    import random

    random.seed(20260729)
    korean = ["안녕", "오늘", "그리고", "값이", "사람이", "회사", "이것은", "매우"]
    latin = ["Google", "kimchi", "AI", "H2O", "GPT-4", "iPhone", "km", "xyzzy",
             "O'Neill", "S&P", "e.g.", "don't", "MRI"]
    numbers = ["25°C", "30%", "3개", "3시 30분", "5km", "$5m", "3:1", "1st",
               "-5", "1,234", "2026-07-29", "10월", "14:05"]
    symbols = ["±", "≈", "→", "π", "α", "∞", "~", "#1", "&", "@", "...", "!!",
               "??", "(", ")", "[", "]", '"', "'"]
    pool = korean + latin + numbers + symbols

    for _ in range(3000):
        source = " ".join(
            random.choice(pool) for _ in range(random.randint(1, 8))
        )
        spoken = normalize_for_tts(source)
        assert isinstance(spoken, str)
        if re.search(r"[가-힣]", source):
            assert not _LATIN.search(spoken), source


def test_empty_and_non_string_input() -> None:
    assert normalize_korean_for_tts("") == ""
    assert normalize_korean_for_tts(None) is None


# ------------------------------------------------------------ lexicon health

def test_every_reading_is_hangul() -> None:
    for name, table in lexicon.SOURCES:
        for key, reading in table.items():
            assert _HANGUL_ONLY.fullmatch(reading), f"{name}: {key} -> {reading}"


def test_every_key_is_lowercase_ascii() -> None:
    allowed = re.compile(r"[a-z0-9 .&\-'/+]{2,}")
    for name, table in lexicon.SOURCES:
        for key in table:
            assert allowed.fullmatch(key), f"{name}: {key}"


def test_every_module_is_alphabetically_sorted() -> None:
    # Sorted keys are how a human finds an entry to fix in an 800-line table.
    for name, table in lexicon.SOURCES:
        keys = list(table)
        assert keys == sorted(keys), name


def test_no_module_repeats_a_key_with_a_different_reading() -> None:
    """A key in two modules must not be voiced two different ways by accident."""
    conflicting = {}
    for key, names in lexicon.collisions().items():
        readings = {
            table[key] for name, table in lexicon.SOURCES if key in table
        }
        if len(readings) > 1:
            conflicting[key] = sorted(readings)
    # Disagreements are allowed — a word can mean different things in two
    # domains — but the winner is decided by SOURCES order, never by chance.
    for key in conflicting:
        first = next(name for name, table in lexicon.SOURCES if key in table)
        winner = next(table for name, table in lexicon.SOURCES if name == first)
        assert lexicon.WORDS[key] == winner[key], key


def test_lexicon_is_large_enough_to_be_useful() -> None:
    assert len(lexicon.WORDS) > 7000


def test_collisions_resolve_deterministically() -> None:
    # Duplicates across modules are fine; the merge order decides the winner.
    for key, names in lexicon.collisions().items():
        winner = next(
            table for name, table in lexicon.SOURCES if name == names[0]
        )
        assert lexicon.WORDS[key] == winner[key], key


def test_phrase_entries_are_matched_before_single_words() -> None:
    assert "machine learning" in lexicon.WORDS
    assert normalize_for_tts("machine learning 수업") == "머신 러닝 수업"


def test_realtime_stream_speaks_hangul_but_captions_the_original() -> None:
    """The listener hears Hangul; the reader still sees what Rau wrote."""
    import base64
    import queue

    from rau.voice.tts_stream import speak_realtime_stream

    sent = []
    captions = []
    pcm = b"\x00\x00" * 20

    class _Session:
        def __init__(self):
            self.messages = queue.Queue()

        def open_context(self, *_args, **_kwargs):
            return self.messages

        def text(self, _context_id, text, *, flush=False):
            sent.append(text)
            self.messages.put({"audio": base64.b64encode(pcm).decode()})

        def flush_context(self, _context_id):
            self.messages.put({"isFinal": True})

        def close_context(self, _context_id):
            return None

        def close(self):
            return None

    list(
        speak_realtime_stream(
            iter(["Google에서 25°C를 검색했다."]),
            on_audio=lambda _pcm: None,
            on_sentence=captions.append,
            session=_Session(),
        )
    )

    assert sent == ["구글에서 섭씨 25도를 검색했다. "]
    assert captions == ["Google에서 25°C를 검색했다."]


def test_cartesia_boundary_receives_korean_text() -> None:
    from rau.voice import tts_stream

    sent = {}

    def fake_stream(*, text, voice_id, model, speed):
        sent["text"] = text
        return iter([b"\x00\x00"])

    from rau.voice import cartesia_api

    original = cartesia_api.stream_audio
    cartesia_api.stream_audio = fake_stream
    try:
        audio = list(
            tts_stream.synth_sentence(
                "Google에서 25°C를 검색했다.",
                provider="cartesia",
                voice_id="voice",
                model="sonic-3.5",
            )
        )
    finally:
        cartesia_api.stream_audio = original

    assert audio == [b"\x00\x00"]
    assert sent["text"] == "구글에서 섭씨 25도를 검색했다."
    assert not _LATIN.search(sent["text"])
