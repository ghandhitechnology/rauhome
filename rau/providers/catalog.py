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
    "deepseek": {
        "label": "DeepSeek",
        "blurb": "Direct DeepSeek API. Legacy deepseek-chat retired 2026-07-24.",
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
    "kimi": {
        "label": "Kimi / Moonshot",
        "blurb": "Moonshot pay-as-you-go platform (api.moonshot.ai).",
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
        "label": "Kimi Coding Plan",
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
    "codex": {
        "label": "OpenAI / Codex",
        "blurb": "Direct OpenAI API. GPT-5.6 is the Codex model (no separate -codex id).",
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

# ElevenLabs voices worth starting from.
VOICES: List[Dict[str, str]] = [
    {"id": "TX3LPaxmHKxFdv7VOQHJ", "label": "Liam", "note": "warm, neutral"},
    {"id": "21m00Tcm4TlvDq8ikWAM", "label": "Rachel", "note": "calm, clear"},
    {"id": "AZnzlk1XvdvUeBnXmlld", "label": "Domi", "note": "bright, energetic"},
    {"id": "pNInz6obpgDQGcFmaJgB", "label": "Adam", "note": "deep, steady"},
]

TTS_MODELS: List[Dict[str, str]] = [
    {"id": "eleven_flash_v2_5", "label": "Flash v2.5", "note": "lowest latency"},
    {"id": "eleven_turbo_v2_5", "label": "Turbo v2.5", "note": "balanced"},
    {"id": "eleven_multilingual_v2", "label": "Multilingual v2", "note": "highest quality"},
]

# ── speech-to-text ────────────────────────────────────────────────────
# `partials` drives whether the UI promises a live transcript. Only Deepgram
# streams interim results; the rest cannot return anything until you stop
# speaking, and pretending otherwise would make the UI feel broken.
STT_PROVIDERS: Dict[str, Dict[str, Any]] = {
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
            {"id": "scribe_v1", "label": "Scribe v1", "note": "accurate, 99 languages"},
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


def catalog() -> Dict[str, Any]:
    return {
        "providers": CATALOG,
        "provider_auth": PROVIDER_AUTH,
        "slots": SLOTS,
        "voices": VOICES,
        "tts_models": TTS_MODELS,
        "stt_providers": STT_PROVIDERS,
    }
