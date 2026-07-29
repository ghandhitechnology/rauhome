"""Known-good model choices per provider (curated for July 2026 SOTA).

This is a convenience list, not exhaustive — every slot still accepts a
free-text model id. IDs verified against OpenRouter / provider docs as of
2026-07-25.
"""
from __future__ import annotations

from typing import Any, Dict, List

# Which auth slot (rau.env.AUTH_SLOTS id) powers each chat provider.
PROVIDER_AUTH: Dict[str, str] = {
    "openrouter": "openrouter",
    "deepseek": "deepseek",
    "kimi": "kimi",
    "moonshot": "kimi",
    "kimi_code": "kimi_code",
    "codex": "codex",
    "openai": "codex",
    "zai_code": "zai_code",
    "zai": "zai_code",
    "anthropic": "anthropic",
    "claude": "anthropic",
    "xai": "xai",
    "grok": "xai",
    "gemini": "gemini",
    "google": "gemini",
}

# provider id -> UI metadata + suggested models
CATALOG: Dict[str, Dict[str, Any]] = {
    "openrouter": {
        "label": "OpenRouter",
        "blurb": "One key → July 2026 frontier + value models.",
        "models": [
            {
                "id": "openai/gpt-5.6-sol",
                "label": "GPT-5.6 Sol",
                "note": "SOTA coding / agentic (Jul 2026)",
            },
            {
                "id": "anthropic/claude-fable-5",
                "label": "Claude Fable 5",
                "note": "top Claude for hard coding",
            },
            {
                "id": "anthropic/claude-opus-4.8",
                "label": "Claude Opus 4.8",
                "note": "everyday frontier default",
            },
            {
                "id": "anthropic/claude-sonnet-5",
                "label": "Claude Sonnet 5",
                "note": "writing + instruction following",
            },
            {
                "id": "google/gemini-3.1-pro-preview",
                "label": "Gemini 3.1 Pro",
                "note": "multimodal, huge context",
            },
            {
                "id": "google/gemini-3.6-flash",
                "label": "Gemini 3.6 Flash",
                "note": "frontier price/perf",
            },
            {
                "id": "moonshotai/kimi-k3",
                "label": "Kimi K3",
                "note": "open frontier; frontend arena #1",
            },
            {
                "id": "deepseek/deepseek-v4-pro",
                "label": "DeepSeek V4 Pro",
                "note": "near-frontier value",
            },
            {
                "id": "deepseek/deepseek-v4-flash",
                "label": "DeepSeek V4 Flash",
                "note": "cheap + fast face default",
            },
            {
                "id": "z-ai/glm-5.2",
                "label": "GLM-5.2",
                "note": "top open intelligence/$",
            },
            {
                "id": "openai/gpt-5.6-luna",
                "label": "GPT-5.6 Luna",
                "note": "fast GPT-5.6 tier",
            },
            {
                "id": "x-ai/grok-4.5",
                "label": "Grok 4.5",
                "note": "realtime / web context",
            },
        ],
    },
    "codex": {
        "label": "OpenAI",
        "blurb": "OpenAI API: Use models like GPT-5.6 sol, terra, luna, or whisper",
        "models": [
            {
                "id": "gpt-5.6-sol",
                "label": "GPT-5.6 Sol",
                "note": "flagship; best coding",
            },
            {
                "id": "gpt-5.6-terra",
                "label": "GPT-5.6 Terra",
                "note": "balanced 5.6",
            },
            {
                "id": "gpt-5.6-luna",
                "label": "GPT-5.6 Luna",
                "note": "fast / cheap 5.6",
            },
            {
                "id": "gpt-5.5",
                "label": "GPT-5.5",
                "note": "previous frontier fallback",
            },
        ],
    },
    "openai": {
        "label": "OpenAI",
        "blurb": "Direct OpenAI API (same key as Codex).",
        "models": [
            {
                "id": "gpt-5.6-sol",
                "label": "GPT-5.6 Sol",
                "note": "flagship",
            },
            {
                "id": "gpt-5.6-terra",
                "label": "GPT-5.6 Terra",
                "note": "balanced",
            },
            {
                "id": "gpt-5.6-luna",
                "label": "GPT-5.6 Luna",
                "note": "fast face pick",
            },
            {
                "id": "gpt-5.5",
                "label": "GPT-5.5",
                "note": "fallback",
            },
        ],
    },
    "anthropic": {
        "label": "Anthropic",
        "blurb": "Direct Anthropic API from platform.claude.com. Best Claude quality without OpenRouter.",
        "models": [
            {
                "id": "claude-fable-5",
                "label": "Claude Fable 5",
                "note": "top Claude for hard coding",
            },
            {
                "id": "claude-opus-5",
                "label": "Claude Opus 5",
                "note": "frontier agentic default",
            },
            {
                "id": "claude-sonnet-5",
                "label": "Claude Sonnet 5",
                "note": "writing + instruction following",
            },
            {
                "id": "claude-haiku-4-5",
                "label": "Claude Haiku 4.5",
                "note": "fast face pick",
            },
        ],
    },
    "xai": {
        "label": "xAI",
        "blurb": "xAI API from console.x.ai. OpenAI-compatible; strong realtime / coding.",
        "models": [
            {
                "id": "grok-4.5",
                "label": "Grok 4.5",
                "note": "flagship; coding + chat",
            },
            {
                "id": "grok-4.3",
                "label": "Grok 4.3",
                "note": "1M context value tier",
            },
            {
                "id": "grok-4.20",
                "label": "Grok 4.20",
                "note": "reasoning alias",
            },
        ],
    },
    "gemini": {
        "label": "Google AI",
        "blurb": "Google AI Studio key. OpenAI-compatible Gemini endpoint.",
        "models": [
            {
                "id": "gemini-3.1-pro-preview",
                "label": "Gemini 3.1 Pro",
                "note": "multimodal, huge context",
            },
            {
                "id": "gemini-3.6-flash",
                "label": "Gemini 3.6 Flash",
                "note": "frontier price/perf; face pick",
            },
        ],
    },    "deepseek": {
        "label": "DeepSeek",
        "blurb": "Ultra cheap, strong and fast models: Deepseek v4 flash and pro. Best when you are on a budget.",
        "models": [
            {
                "id": "deepseek-v4-flash",
                "label": "DeepSeek V4 Flash",
                "note": "default; set effort for thinking",
            },
            {
                "id": "deepseek-v4-pro",
                "label": "DeepSeek V4 Pro",
                "note": "harder reasoning / coding",
            },
        ],
    },
    "zai_code": {
        "label": "Z.AI",
        "blurb": "GLM membership on api.z.ai coding endpoint. Paste a Coding Plan key, not pay-as-you-go.",
        "models": [
            {
                "id": "glm-5.2",
                "label": "GLM-5.2",
                "note": "flagship; up to 1M ctx",
            },
            {
                "id": "glm-5-turbo",
                "label": "GLM-5 Turbo",
                "note": "faster GLM-5 tier",
            },
            {
                "id": "glm-4.7",
                "label": "GLM-4.7",
                "note": "lighter quota burn",
            },
            {
                "id": "glm-4.5-air",
                "label": "GLM-4.5 Air",
                "note": "cheap / fast",
            },
        ],
    },
    "kimi": {
        "label": "Kimi",
        "blurb": "Caution: Kimi k3 isn't recommended; too slow for continuous talking. Use it for deep research subagents or dreaming.",
        "models": [
            {
                "id": "kimi-k3",
                "label": "Kimi K3",
                "note": "2.8T MoE; 1M context; thinking always on",
            },
            {
                "id": "kimi-k2.7-code",
                "label": "Kimi K2.7 Code",
                "note": "coding specialist",
            },
            {
                "id": "kimi-k2.6",
                "label": "Kimi K2.6",
                "note": "prior open frontier",
            },
            {
                "id": "kimi-k2-thinking",
                "label": "Kimi K2 Thinking",
                "note": "extended reasoning",
            },
        ],
    },
    "kimi_code": {
        "label": "Kimi Code",
        "blurb": "Membership plan on api.kimi.com/coding (Anthropic-compatible).",
        "models": [
            {
                "id": "k3",
                "label": "k3",
                "note": "Kimi K3 via Coding Plan; up to 1M ctx",
            },
            {
                "id": "k3-256k",
                "label": "k3-256k",
                "note": "same quality, less quota than k3",
            },
            {
                "id": "kimi-for-coding",
                "label": "kimi-for-coding",
                "note": "K2.7 Code — all members",
            },
            {
                "id": "kimi-for-coding-highspeed",
                "label": "kimi-for-coding-highspeed",
                "note": "Allegretto+; ~5–6× faster",
            },
        ],
    },

}

# Slot-level guidance shown next to each assignment in the wizard.
SLOTS: List[Dict[str, Any]] = [
    {
        "id": "face",
        "label": "Face",
        "blurb": "The voice you talk to. Prefer Flash / Luna / Haiku-class latency.",
        "prefers": "fast",
    },
    {
        "id": "subagent",
        "label": "Subagent",
        "blurb": "Silent deep work. Prefer Sol / Fable / Opus / K3 / V4 Pro.",
        "prefers": "smart",
    },
    {
        "id": "dream",
        "label": "Dream",
        "blurb": "Nightly memory compaction. Balanced quality is enough.",
        "prefers": "balanced",
    },
]

# ElevenLabs' default premade voices are available to every account. These
# four presets are intentionally role-shaped rather than just a list of names:
# selecting one changes the source voice, synthesis tuning, and local effect.
VOICE_PRESETS: List[Dict[str, Any]] = [
    {
        "id": "robotic",
        "label": "Robotic",
        "note": "Synthetic companion with a crisp vocoder edge.",
        "voice_id": "TX3LPaxmHKxFdv7VOQHJ",
        "voice_name": "Liam",
        "effect": "robot",
        "settings": {
            "stability": 0.72,
            "similarity_boost": 0.72,
            "style": 0.12,
            "speed": 1.0,
            "use_speaker_boost": True,
        },
    },
    {
        "id": "grandfather",
        "label": "Grandfather",
        "note": "Wise, unhurried, comforting older storyteller.",
        "voice_id": "pqHfZKP75CvOlQylNhV4",
        "voice_name": "Bill",
        "effect": "none",
        "settings": {
            "stability": 0.74,
            "similarity_boost": 0.84,
            "style": 0.18,
            "speed": 0.88,
            "use_speaker_boost": True,
        },
    },
    {
        "id": "girlfriend",
        "label": "Girlfriend",
        "note": "Warm, playful adult conversational voice.",
        "voice_id": "cgSgspJ2msm6clMCkdW9",
        "voice_name": "Jessica",
        "effect": "none",
        "settings": {
            "stability": 0.46,
            "similarity_boost": 0.82,
            "style": 0.34,
            "speed": 0.98,
            "use_speaker_boost": True,
        },
    },
    {
        "id": "child",
        "label": "Childlike",
        "note": "Bright fictional character voice with a gentle pitch lift.",
        "voice_id": "FGY2WhTYpPnrIDTdsKH5",
        "voice_name": "Laura",
        "effect": "childlike",
        "settings": {
            "stability": 0.44,
            "similarity_boost": 0.76,
            "style": 0.42,
            "speed": 1.06,
            "use_speaker_boost": True,
        },
    },
]

# Kept for older clients; new clients use voice_presets and the live account
# voice endpoint. The IDs mirror the presets so no picker can select an
# inaccessible legacy voice.
VOICES: List[Dict[str, str]] = [
    {
        "id": str(preset["voice_id"]),
        "label": f'{preset["label"]} · {preset["voice_name"]}',
        "note": str(preset["note"]),
    }
    for preset in VOICE_PRESETS
]

VOICE_EFFECTS: List[Dict[str, str]] = [
    {"id": "none", "label": "Natural", "note": "No local processing"},
    {"id": "robot", "label": "Robot", "note": "Pitch, bitcrush and light reverb"},
    {"id": "childlike", "label": "Childlike", "note": "Gentle pitch lift"},
]

TTS_MODELS: List[Dict[str, str]] = [
    {"id": "eleven_flash_v2_5", "label": "Flash v2.5", "note": "lowest latency"},
    {"id": "eleven_turbo_v2_5", "label": "Turbo v2.5", "note": "balanced"},
    {"id": "eleven_multilingual_v2", "label": "Multilingual v2", "note": "highest quality"},
]

TTS_PROVIDERS: Dict[str, Dict[str, Any]] = {
    "elevenlabs": {
        "label": "ElevenLabs",
        "blurb": "Expressive speech with account voices and the four built-in personalities.",
        "auth": "elevenlabs",
        "models": TTS_MODELS,
    },
    "cartesia": {
        "label": "Cartesia",
        "blurb": "Sonic 3.5 speech with a persistent low-latency streaming connection.",
        "auth": "cartesia",
        "models": [
            {
                "id": "sonic-3.5",
                "label": "Sonic 3.5",
                "note": "latest low-latency model",
            }
        ],
    },
}

# ── speech-to-text ────────────────────────────────────────────────────
# `partials` drives whether the UI promises a live transcript. Only Deepgram
# streams interim results; the rest cannot return anything until you stop
# speaking, and pretending otherwise would make the UI feel broken.
#: Ways of reading the web. The two are not interchangeable, so the blurbs say
#: what each is actually for rather than which is "better".
BROWSE_PROVIDERS: Dict[str, Dict[str, Any]] = {
    "auto": {
        "label": "Automatic",
        "blurb": "Uses Firecrawl when connected, otherwise Browserbase.",
        "auth": "",
        "can_search": True,
    },
    "firecrawl": {
        "label": "Firecrawl",
        "blurb": "Scrapes a page to clean markdown. Fast and cheap, and the only one that can search the web.",
        "auth": "firecrawl",
        "can_search": True,
    },
    "browserbase": {
        "label": "Browserbase",
        "blurb": "Drives a real cloud browser, so pages that build themselves with JavaScript still come back. Slower, and billed by the minute.",
        "auth": "browserbase",
        "can_search": False,
    },
}


STT_PROVIDERS: Dict[str, Dict[str, Any]] = {
    "auto": {
        "label": "Automatic (recommended)",
        "blurb": "Uses Deepgram when connected, then ElevenLabs, OpenAI, and local Whisper.",
        "auth": "",
        "partials": True,
        "models": [],
    },
    "deepgram": {
        "label": "Deepgram",
        "blurb": "Real streaming — live partials and server-side endpointing. Best for conversation.",
        "auth": "deepgram",
        "partials": True,
        "models": [
            {"id": "nova-3", "label": "Nova 3", "note": "most accurate, lowest latency"},
            {"id": "nova-2", "label": "Nova 2", "note": "cheaper"},
        ],
    },
    "elevenlabs": {
        "label": "ElevenLabs Scribe",
        "blurb": "Reuses your ElevenLabs TTS key — no extra signup. Waits for you to finish.",
        "auth": "elevenlabs",
        "partials": False,
        "models": [
            {"id": "scribe_v2", "label": "Scribe v2", "note": "current high-accuracy model"},
            {"id": "scribe_v1", "label": "Scribe v1", "note": "legacy fallback"},
        ],
    },
    "openai": {
        "label": "OpenAI",
        "blurb": "Reuses your OpenAI key. Waits for you to finish speaking.",
        "auth": "codex",
        "partials": False,
        "models": [
            {"id": "gpt-4o-transcribe", "label": "gpt-4o-transcribe", "note": "best quality"},
            {"id": "gpt-4o-mini-transcribe", "label": "gpt-4o-mini-transcribe", "note": "cheaper"},
            {"id": "whisper-1", "label": "whisper-1", "note": "legacy"},
        ],
    },
    "local": {
        "label": "Local (faster-whisper)",
        "blurb": "No key, no network, nothing leaves the machine. Slower, no live transcript.",
        "auth": "",
        "partials": False,
        "models": [
            {"id": "tiny", "label": "tiny", "note": "fastest, least accurate"},
            {"id": "base", "label": "base", "note": "balanced"},
            {"id": "small", "label": "small", "note": "default"},
            {"id": "medium", "label": "medium", "note": "slow on CPU"},
        ],
    },
}


# ── reasoning / effort capabilities ───────────────────────────────────
# Declared like STT `partials`: UI and wire adapters read this instead of
# assuming every model understands reasoning_effort the same way.

_ALL = ("low", "medium", "high", "max")
_DEEPSEEK = {
    "supported": True,
    "levels": ["high", "max"],
    "default": "high",
    "param": "deepseek",
}
_OPENAI_REASONING = {
    "supported": True,
    "levels": list(_ALL),
    "default": "medium",
    "param": "openai",
}
_OPENAI_FAST = {
    "supported": False,
    "levels": [],
    "default": "medium",
    "param": "none",
}
_KIMI = {
    "supported": True,
    "levels": ["low", "high", "max"],
    "default": "high",
    "param": "kimi",
}
# Kimi Coding Plan is Anthropic-compatible: effort rides in a thinking
# payload, and thinking forbids a non-default temperature (fixed_temperature).
_KIMI_CODE = {
    "supported": True,
    "levels": ["low", "high", "max"],
    "default": "high",
    "param": "anthropic",
    "fixed_temperature": True,
}
# Strict OpenAI reasoning endpoints (o-series / GPT-5) reject any non-default
# temperature with HTTP 400, so the wire layer must omit it entirely.
_OPENAI_STRICT = {
    "supported": True,
    "levels": list(_ALL),
    "default": "medium",
    "param": "openai",
    "fixed_temperature": True,
}
_CLAUDE = {
    "supported": True,
    "levels": list(_ALL),
    "default": "medium",
    "param": "openai",
}
# Direct Anthropic Messages API (Claude Console): thinking budget, no temperature.
_ANTHROPIC = {
    "supported": True,
    "levels": list(_ALL),
    "default": "medium",
    "param": "anthropic",
    "fixed_temperature": True,
}

#: provider id → default when the model id is not in the curated list
PROVIDER_REASONING_DEFAULTS: Dict[str, Dict[str, Any]] = {
    "deepseek": dict(_DEEPSEEK),
    "kimi": dict(_KIMI),
    "moonshot": dict(_KIMI),
    "kimi_code": dict(_KIMI_CODE),
    # Unlisted openai/codex ids are treated as ordinary chat models: their
    # configured temperature passes through. reasoning_for() upgrades ids
    # matching the reasoning families (o-series, GPT-5) to _OPENAI_STRICT,
    # which omits temperature because only those endpoints 400 on it.
    "codex": dict(_OPENAI_REASONING),
    "openai": dict(_OPENAI_REASONING),
    "openrouter": dict(_OPENAI_REASONING),
    "zai_code": dict(_OPENAI_REASONING),
    "zai": dict(_OPENAI_REASONING),
    "anthropic": dict(_ANTHROPIC),
    "claude": dict(_ANTHROPIC),
    "xai": dict(_OPENAI_REASONING),
    "grok": dict(_OPENAI_REASONING),
    "gemini": dict(_OPENAI_REASONING),
    "google": dict(_OPENAI_REASONING),
}

#: Exact curated model ids (and OpenRouter-qualified ids) → capability
MODEL_REASONING: Dict[str, Dict[str, Any]] = {
    # DeepSeek direct
    "deepseek-v4-flash": dict(_DEEPSEEK),
    "deepseek-v4-pro": dict(_DEEPSEEK),
    # OpenRouter DeepSeek
    "deepseek/deepseek-v4-flash": dict(_DEEPSEEK),
    "deepseek/deepseek-v4-pro": dict(_DEEPSEEK),
    # OpenAI / Codex
    "gpt-5.6-sol": dict(_OPENAI_STRICT),
    "gpt-5.6-terra": dict(_OPENAI_STRICT),
    "gpt-5.6-luna": dict(_OPENAI_FAST),
    "gpt-5.5": dict(_OPENAI_STRICT),
    "openai/gpt-5.6-sol": dict(_OPENAI_STRICT),
    "openai/gpt-5.6-terra": dict(_OPENAI_STRICT),
    "openai/gpt-5.6-luna": dict(_OPENAI_FAST),
    # OpenRouter Claude / Gemini
    "anthropic/claude-fable-5": dict(_CLAUDE),
    "anthropic/claude-opus-4.8": dict(_CLAUDE),
    "anthropic/claude-sonnet-5": dict(_CLAUDE),
    "google/gemini-3.1-pro-preview": dict(_CLAUDE),
    "google/gemini-3.6-flash": dict(_OPENAI_FAST),
    # Claude Console (direct Anthropic)
    "claude-fable-5": dict(_ANTHROPIC),
    "claude-opus-5": dict(_ANTHROPIC),
    "claude-sonnet-5": dict(_ANTHROPIC),
    "claude-haiku-4-5": dict(_OPENAI_FAST),
    # Gemini direct
    "gemini-3.1-pro-preview": dict(_CLAUDE),
    "gemini-3.6-flash": dict(_OPENAI_FAST),
    # Grok direct
    "grok-4.5": dict(_OPENAI_REASONING),
    "grok-4.3": dict(_OPENAI_REASONING),
    "grok-4.20": dict(_OPENAI_REASONING),
    # Z.AI Coding Plan
    "glm-5.2": dict(_OPENAI_REASONING),
    "glm-5-turbo": dict(_OPENAI_REASONING),
    "glm-4.7": dict(_OPENAI_REASONING),
    "glm-4.5-air": dict(_OPENAI_FAST),
    # Kimi
    "kimi-k3": dict(_KIMI),
    "kimi-k2.7-code": dict(_KIMI),
    "kimi-k2.6": dict(_KIMI),
    "kimi-k2-thinking": dict(_KIMI),
    "moonshotai/kimi-k3": dict(_KIMI),
    # Kimi Coding Plan ids (Anthropic transport, thinking payload)
    "k3": dict(_KIMI_CODE),
    "k3-256k": dict(_KIMI_CODE),
    "kimi-for-coding": dict(_KIMI_CODE),
    "kimi-for-coding-highspeed": dict(_KIMI_CODE),
    # Misc OpenRouter
    "z-ai/glm-5.2": dict(_OPENAI_REASONING),
    "x-ai/grok-4.5": dict(_OPENAI_REASONING),
}


def _normalize_reasoning(raw: Dict[str, Any]) -> Dict[str, Any]:
    supported = bool(raw.get("supported"))
    levels = [str(x) for x in (raw.get("levels") or []) if str(x) in _ALL]
    default = str(raw.get("default") or "medium")
    if default not in _ALL:
        default = "medium"
    if supported and levels and default not in levels:
        default = levels[0]
    param = str(raw.get("param") or ("openai" if supported else "none"))
    return {
        "supported": supported,
        "levels": levels,
        "default": default,
        "param": param,
        "fixed_temperature": bool(raw.get("fixed_temperature")),
    }


def _openai_rejects_temperature(mid_l: str) -> bool:
    """True for unlisted openai/codex ids that 400 on a non-default temperature.

    Only the reasoning families (o-series, GPT-5) reject temperature;
    ordinary chat ids (gpt-4o, gpt-4.1, ...) accept it, so the provider
    default must not strip it from them.
    """
    tail = mid_l.rsplit("/", 1)[-1]
    return tail.startswith(("o1", "o3", "o4", "gpt-5"))


def reasoning_for(provider: str, model: str) -> Dict[str, Any]:
    """Capability for a provider+model pair (catalog lookup + provider default)."""
    prov = (provider or "").strip().lower()
    mid = (model or "").strip()
    mid_l = mid.lower()

    if mid in MODEL_REASONING:
        return _normalize_reasoning(MODEL_REASONING[mid])
    if mid_l in MODEL_REASONING:
        return _normalize_reasoning(MODEL_REASONING[mid_l])

    # Heuristics for free-text / unlisted ids
    if "luna" in mid_l or "flash" in mid_l or "haiku" in mid_l:
        if prov in ("deepseek",) or mid_l.startswith("deepseek"):
            return _normalize_reasoning(_DEEPSEEK)
        return _normalize_reasoning(_OPENAI_FAST)
    if mid_l.startswith("deepseek") or "/deepseek" in mid_l:
        return _normalize_reasoning(_DEEPSEEK)
    if mid_l.startswith("kimi") or mid_l in ("k3", "k3-256k") or "moonshot" in mid_l:
        # The same free-text id means a different wire format depending on
        # which Kimi surface the slot points at.
        if prov in ("kimi_code", "kimi-code", "kimi_coding"):
            return _normalize_reasoning(_KIMI_CODE)
        return _normalize_reasoning(_KIMI)
    if mid_l.startswith("claude") and prov in ("anthropic", "claude"):
        if "haiku" in mid_l:
            return _normalize_reasoning(_OPENAI_FAST)
        return _normalize_reasoning(_ANTHROPIC)
    if mid_l.startswith("gemini") and ("flash" in mid_l or prov in ("gemini", "google")):
        if "flash" in mid_l:
            return _normalize_reasoning(_OPENAI_FAST)
        return _normalize_reasoning(_CLAUDE)
    if prov in ("openai", "codex") and _openai_rejects_temperature(mid_l):
        return _normalize_reasoning(_OPENAI_STRICT)

    base = PROVIDER_REASONING_DEFAULTS.get(prov) or _OPENAI_REASONING
    return _normalize_reasoning(base)


def catalog(language: str | None = None) -> Dict[str, Any]:
    """The whole catalog, in the reader's language.

    `language` overrides the stored locale so the Settings page can ask for
    Korean copy in the same breath as it switches: the preference is written
    and the catalog refetched, and waiting for the write to land first would
    show one panel of English between the two.
    """
    # Attach reasoning metadata onto each curated model for the Settings UI.
    providers: Dict[str, Any] = {}
    for pid, meta in CATALOG.items():
        models_out = []
        for m in meta.get("models") or []:
            entry = dict(m)
            entry["reasoning"] = reasoning_for(pid, str(m.get("id") or ""))
            models_out.append(entry)
        providers[pid] = {**meta, "models": models_out}
    payload = {
        "providers": providers,
        "provider_auth": PROVIDER_AUTH,
        "provider_reasoning_defaults": {
            k: _normalize_reasoning(v) for k, v in PROVIDER_REASONING_DEFAULTS.items()
        },
        "slots": SLOTS,
        "voices": VOICES,
        "voice_presets": VOICE_PRESETS,
        "voice_effects": VOICE_EFFECTS,
        "tts_models": TTS_MODELS,
        "tts_providers": TTS_PROVIDERS,
        "stt_providers": STT_PROVIDERS,
        "browse_providers": BROWSE_PROVIDERS,
    }
    from rau.language import get_locale

    if (language or get_locale()) == "ko":
        from rau.providers.korean import localize

        # `provider_auth` is a map of ids to ids; localize() leaves it alone
        # because none of its keys are a translatable field name.
        return localize(payload)
    return payload
