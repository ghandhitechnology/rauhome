"""Korean for the strings the hub hands the interface.

The provider catalog and the auth slots carry their own prose: what a slot is
for, what a backend is good at, what a model is worth using. None of it lives
in the web app, so translating the front end alone leaves a Korean Settings
page describing its models in English.

Translating in place would mean two copies of a table that changes every time
a model ships. Instead this is an overlay keyed by the English text: one walk
over the structure swaps any `label`, `blurb`, `note` or `help` it recognises
and leaves everything else exactly as it was. Brand names and model ids are
therefore untranslated by construction rather than by a rule someone has to
remember, and a note added upstream without a Korean line shows through in
English instead of disappearing.
"""
from __future__ import annotations

from typing import Any, Dict

#: Only the labels that are words. Every brand and model name is absent on
#: purpose: "Claude Sonnet 5" is what the provider's own console calls it.
LABELS: Dict[str, str] = {
    "Face": "얼굴",
    "Subagent": "하위 에이전트",
    "Dream": "꿈",
    "Automatic": "자동",
    "Automatic (recommended)": "자동 (권장)",
    "Local (faster-whisper)": "로컬 (faster-whisper)",
    "Natural": "자연 그대로",
    "Robot": "로봇",
    "Robotic": "로봇",
    "Childlike": "아이 같은",
    "Girlfriend": "여자친구",
    "Grandfather": "할아버지",
}

#: Slot guidance, provider pitches, and the two one-line service descriptions.
BLURBS: Dict[str, str] = {
    # slots
    "The voice you talk to. Prefer Flash / Luna / Haiku-class latency.":
        "당신이 이야기하는 목소리입니다. Flash, Luna, Haiku급의 빠른 응답이 좋습니다.",
    "Silent deep work. Prefer Sol / Fable / Opus / K3 / V4 Pro.":
        "말없이 깊게 파고드는 역할입니다. Sol, Fable, Opus, K3, V4 Pro가 어울립니다.",
    "Nightly memory compaction. Balanced quality is enough.":
        "밤사이 기억을 정리하는 역할입니다. 무난한 품질이면 충분합니다.",
    # chat providers
    "One key → July 2026 frontier + value models.":
        "키 하나로 2026년 7월 기준 최상위 모델과 가성비 모델을 함께 씁니다.",
    "OpenAI API: Use models like GPT-5.6 sol, terra, luna, or whisper":
        "OpenAI API입니다. GPT-5.6 Sol, Terra, Luna, Whisper 같은 모델을 씁니다.",
    "Direct OpenAI API (same key as Codex).":
        "OpenAI API에 직접 연결합니다. Codex와 같은 키를 씁니다.",
    "Direct Anthropic API from platform.claude.com. Best Claude quality without OpenRouter.":
        "platform.claude.com의 Anthropic API에 직접 연결합니다. OpenRouter 없이 Claude를 가장 좋은 품질로 씁니다.",
    "xAI API from console.x.ai. OpenAI-compatible; strong realtime / coding.":
        "console.x.ai의 xAI API입니다. OpenAI 호환이고 실시간 정보와 코딩에 강합니다.",
    "Google AI Studio key. OpenAI-compatible Gemini endpoint.":
        "Google AI Studio 키입니다. OpenAI 호환 Gemini 엔드포인트를 씁니다.",
    "Ultra cheap, strong and fast models: Deepseek v4 flash and pro. Best when you are on a budget.":
        "아주 저렴하면서도 빠르고 튼튼한 DeepSeek V4 Flash와 Pro를 씁니다. 예산이 빠듯할 때 가장 좋습니다.",
    "GLM membership on api.z.ai coding endpoint. Paste a Coding Plan key, not pay-as-you-go.":
        "api.z.ai 코딩 엔드포인트의 GLM 멤버십입니다. 종량제 키가 아니라 Coding Plan 키를 넣어 주세요.",
    "Caution: Kimi k3 isn't recommended; too slow for continuous talking. Use it for deep research subagents or dreaming.":
        "참고: Kimi K3는 계속 이어지는 대화에는 느려서 권하지 않습니다. 깊이 파고드는 하위 에이전트나 꿈에 쓰세요.",
    "Membership plan on api.kimi.com/coding (Anthropic-compatible).":
        "api.kimi.com/coding의 멤버십 플랜입니다. Anthropic 호환입니다.",
    # speech
    "Expressive speech with account voices and the four built-in personalities.":
        "표현이 풍부한 음성입니다. 계정의 목소리와 기본 성격 네 가지를 함께 씁니다.",
    "Sonic 3.5 speech with a persistent low-latency streaming connection.":
        "Sonic 3.5 음성입니다. 지연이 짧은 연결을 계속 열어 둡니다.",
    # hearing
    "Uses Deepgram when connected, then ElevenLabs, OpenAI, and local Whisper.":
        "Deepgram이 연결되어 있으면 그것을 쓰고, 없으면 ElevenLabs, OpenAI, 로컬 Whisper 순으로 넘어갑니다.",
    "Real streaming — live partials and server-side endpointing. Best for conversation.":
        "진짜 스트리밍입니다. 말하는 중에도 중간 결과가 오고, 말이 끝나는 지점도 서버가 잡아 줍니다. 대화에 가장 좋습니다.",
    "Reuses your ElevenLabs TTS key — no extra signup. Waits for you to finish.":
        "쓰던 ElevenLabs 키를 그대로 씁니다. 따로 가입할 필요는 없고, 말이 끝날 때까지 기다립니다.",
    "Reuses your OpenAI key. Waits for you to finish speaking.":
        "쓰던 OpenAI 키를 그대로 씁니다. 말이 끝날 때까지 기다립니다.",
    "No key, no network, nothing leaves the machine. Slower, no live transcript.":
        "키도 인터넷도 필요 없고, 아무것도 이 컴퓨터를 벗어나지 않습니다. 대신 느리고 실시간 자막은 없습니다.",
    # reading the web
    "Uses Firecrawl when connected, otherwise Browserbase.":
        "Firecrawl이 연결되어 있으면 그것을 쓰고, 없으면 Browserbase를 씁니다.",
    "Scrapes a page to clean markdown. Fast and cheap, and the only one that can search the web.":
        "페이지를 깔끔한 마크다운으로 긁어 옵니다. 빠르고 저렴하며, 웹 검색이 되는 유일한 백엔드입니다.",
    "Drives a real cloud browser, so pages that build themselves with JavaScript still come back. Slower, and billed by the minute.":
        "클라우드의 진짜 브라우저를 움직입니다. JavaScript로 스스로 그려지는 페이지도 제대로 가져오지만, 느리고 분당 요금이 붙습니다.",
}

#: The short note beside a model, a voice, or an effect.
NOTES: Dict[str, str] = {
    # chat models
    "SOTA coding / agentic (Jul 2026)": "코딩과 에이전트 최상위 (2026년 7월)",
    "top Claude for hard coding": "어려운 코딩에 가장 좋은 Claude",
    "everyday frontier default": "일상용 최상위 기본값",
    "writing + instruction following": "글쓰기와 지시 이행",
    "multimodal, huge context": "멀티모달, 아주 긴 맥락",
    "frontier price/perf": "최상위 가성비",
    "frontier price/perf; face pick": "최상위 가성비, 얼굴에 추천",
    "open frontier; frontend arena #1": "오픈 최상위, 프런트엔드 1위",
    "near-frontier value": "최상위에 가까운 가성비",
    "cheap + fast face default": "저렴하고 빠른 얼굴 기본값",
    "1M context value tier": "100만 맥락 가성비 등급",
    "2.8T MoE; 1M context; thinking always on": "2.8T MoE, 100만 맥락, 사고 항상 켜짐",
    "balanced 5.6": "균형 잡힌 5.6",
    "balanced": "균형",
    "cheap / fast": "저렴하고 빠름",
    "coding specialist": "코딩 특화",
    "default; set effort for thinking": "기본값, 사고량은 따로 설정",
    "default": "기본값",
    "extended reasoning": "긴 추론",
    "fallback": "대체용",
    "fast / cheap 5.6": "빠르고 저렴한 5.6",
    "fast face pick": "빠른 얼굴 추천",
    "fast GPT-5.6 tier": "빠른 GPT-5.6 등급",
    "faster GLM-5 tier": "더 빠른 GLM-5 등급",
    "flagship; best coding": "대표 모델, 코딩 최고",
    "flagship; coding + chat": "대표 모델, 코딩과 대화",
    "flagship; up to 1M ctx": "대표 모델, 최대 100만 맥락",
    "flagship": "대표 모델",
    "frontier agentic default": "최상위 에이전트 기본값",
    "harder reasoning / coding": "더 어려운 추론과 코딩",
    "K2.7 Code — all members": "K2.7 Code, 모든 멤버십",
    "Kimi K3 via Coding Plan; up to 1M ctx": "Coding Plan의 Kimi K3, 최대 100만 맥락",
    "lighter quota burn": "할당량 소모가 적음",
    "previous frontier fallback": "이전 최상위 대체용",
    "prior open frontier": "이전 오픈 최상위",
    "realtime / web context": "실시간 웹 맥락",
    "reasoning alias": "추론용 별칭",
    "same quality, less quota than k3": "품질은 같고 k3보다 할당량을 덜 씀",
    "top open intelligence/$": "가격 대비 오픈 모델 최고 성능",
    # speech models
    "lowest latency": "가장 짧은 지연",
    "highest quality": "가장 높은 품질",
    "latest low-latency model": "최신 저지연 모델",
    "Allegretto+; ~5–6× faster": "Allegretto+, 약 5~6배 빠름",
    # hearing models
    "most accurate, lowest latency": "가장 정확하고 지연이 짧음",
    "cheaper": "더 저렴함",
    "current high-accuracy model": "현재의 고정확도 모델",
    "legacy fallback": "구형 대체용",
    "legacy": "구형",
    "best quality": "가장 좋은 품질",
    "fastest, least accurate": "가장 빠르고 가장 부정확",
    "slow on CPU": "CPU에서는 느림",
    # voices and effects
    "Synthetic companion with a crisp vocoder edge.": "보코더가 살짝 걸린 또렷한 합성 목소리입니다.",
    "Warm, playful adult conversational voice.": "따뜻하고 장난기 있는 성인 대화 목소리입니다.",
    "Wise, unhurried, comforting older storyteller.": "지혜롭고 서두르지 않는, 편안한 어른의 목소리입니다.",
    "Bright fictional character voice with a gentle pitch lift.": "음을 살짝 올린 밝은 캐릭터 목소리입니다.",
    "No local processing": "후처리 없음",
    "Pitch, bitcrush and light reverb": "음높이, 비트크러시, 가벼운 리버브",
    "Gentle pitch lift": "음을 살짝 올림",
}

#: What each connection card says under the provider's name.
HELP: Dict[str, str] = {
    "Unified router for many models. Create a key, paste it here.":
        "여러 모델을 한곳에서 쓰는 라우터입니다. 키를 만들어 여기에 붙여 넣으세요.",
    "OpenAI API key (Codex / GPT providers).": "OpenAI API 키입니다. Codex와 GPT 제공자에 씁니다.",
    "Anthropic Claude Console API key (sk-ant-…). Direct Messages API.":
        "Anthropic Claude Console API 키입니다 (sk-ant-…). Messages API에 직접 연결합니다.",
    "xAI console API key (xai-…). OpenAI-compatible at api.x.ai.":
        "xAI 콘솔 API 키입니다 (xai-…). api.x.ai에서 OpenAI 호환으로 동작합니다.",
    "Google AI Studio / Gemini API key.": "Google AI Studio, 즉 Gemini API 키입니다.",
    "DeepSeek chat API key.": "DeepSeek 대화 API 키입니다.",
    "Z.AI GLM Coding Plan key. Uses the coding endpoint (not pay-as-you-go).":
        "Z.AI GLM Coding Plan 키입니다. 종량제가 아니라 코딩 엔드포인트를 씁니다.",
    "Moonshot Kimi Platform (pay-as-you-go). Base: api.moonshot.ai":
        "Moonshot Kimi 플랫폼 종량제 키입니다. 기본 주소는 api.moonshot.ai입니다.",
    "Kimi Code membership key (separate from Moonshot). Models: kimi-for-coding, k3, k3-256k.":
        "Kimi Code 멤버십 키입니다. Moonshot과는 별개이고, 모델은 kimi-for-coding, k3, k3-256k입니다.",
    "Text-to-speech and optional Scribe speech-to-text.":
        "음성 합성, 그리고 선택 사항인 Scribe 음성 인식입니다.",
    "Low-latency Sonic 3.5 text-to-speech.": "지연이 짧은 Sonic 3.5 음성 합성입니다.",
    "Streaming speech-to-text for voice mode. The only backend with a live transcript.":
        "보이스 모드용 스트리밍 음성 인식입니다. 실시간 자막이 나오는 유일한 백엔드입니다.",
    "Reads a page and hands back clean markdown. Fast, cheap, and the only one that can search.":
        "페이지를 읽어 깔끔한 마크다운으로 돌려줍니다. 빠르고 저렴하며, 검색이 되는 유일한 선택지입니다.",
    "A real browser in the cloud. Slower, but it runs the page's JavaScript — use it for apps that ship an empty page.":
        "클라우드에 있는 진짜 브라우저입니다. 느리지만 페이지의 JavaScript를 실제로 실행하니, 빈 화면부터 그리는 앱에 쓰세요.",
    "App actions via MCP. Save the API key, then open Connect to authorize apps.":
        "MCP를 통한 앱 동작입니다. API 키를 저장한 뒤 Connect를 열어 앱을 인증하세요.",
}

#: Which overlay answers for which field name.
_BY_FIELD = {
    "label": LABELS,
    "blurb": BLURBS,
    "note": NOTES,
    "help": HELP,
}


def localize(value: Any) -> Any:
    """Return `value` with every recognised English string swapped for Korean.

    Structure-preserving and non-destructive: dicts and lists are rebuilt, and
    a string with no entry in its field's table is returned unchanged. Nothing
    here decides *whether* to translate — see `rau.providers.catalog.catalog`,
    which calls this only when the stored locale is Korean.
    """
    if isinstance(value, dict):
        out: Dict[str, Any] = {}
        for key, item in value.items():
            table = _BY_FIELD.get(key)
            if table is not None and isinstance(item, str):
                out[key] = table.get(item, item)
            else:
                out[key] = localize(item)
        return out
    if isinstance(value, list):
        return [localize(item) for item in value]
    return value
