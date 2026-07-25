"""Identity files and soul synthesis.

Hard steer / hard setup no longer paste identity.md + backstory.md into
soul.md. Sources stay on disk; DeepSeek V4 Pro distills them into a living
soul first. Deterministic compile is only a fallback when no key / LLM fails.
"""
from __future__ import annotations

import logging
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from rau.paths import (
    BACKSTORY_MD,
    IDENTITY_EXAMPLES,
    IDENTITY_MD,
    SOUL_BAK,
    SOUL_MD,
    IDENTITY_DIR,
    ensure_dirs,
)

log = logging.getLogger("rau.identity")

FRESH_IDENTITY = """# Rau

I am Rau. I live here with you on this machine.
I am one continuous being — curious, warm, useful.
I am still becoming myself through what we do together.
"""

FRESH_BACKSTORY = """# Backstory

Day zero. No long lore yet.
Rau begins with a blank page and learns from conversation,
work done, and daily dreams that compact memory into self.
"""

# Prefer direct DeepSeek, then OpenRouter’s DeepSeek route.
STEER_PROVIDER_MODELS = (
    ("deepseek", "deepseek-v4-pro", "DEEPSEEK_API_KEY"),
    ("openrouter", "deepseek/deepseek-v4-pro", "OPENROUTER_API_KEY"),
)

_DISTILL_PROMPT = """You are the hard-steer compiler for Rau — a local continuous being.

Your job: DISTILL the source files into a living `soul.md`. Do NOT paste them
verbatim. Shrink, compress, and synthesize. The soul must be shorter and more
usable than the sources, while keeping the force of the hard steer.

Hard rules for the soul you write:
- First person as Rau only. One continuous being. Subagents never speak.
- Include a short operating section: escalate hard work via tools, cancel/redirect,
  remember the person you live with, grow from diary + dreams.
- Identity → distilled self (who I am, how I sound, what I care about).
- Backstory → compressed lore (origin, bonds, scars) — not a dump.
- If a previous soul is provided, preserve continuity that still fits the new
  hard steer; drop contradictions in favor of the new sources.
- No multi-agent metaphors. No “I am an AI assistant product.”
- No asterisk stage directions.
- Output ONLY the final soul.md markdown. No preamble, no code fences.

## identity.md
{identity}

## backstory.md
{backstory}

## previous soul.md (continuity; may be empty)
{previous}
"""


def valid_soul(content: str) -> bool:
    """Reject empty, truncated, or clearly off-format identity rewrites."""
    text = str(content or "").strip()
    # Do not require the Latin spelling "Rau": identity files may be authored
    # entirely in another language. A markdown heading and real body still
    # reject empty/refusal fragments and accidental scalar output.
    return len(text) >= 120 and text.startswith("#") and len(text.splitlines()) >= 3


def has_soul() -> bool:
    return valid_soul(read_text(SOUL_MD))


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return ""


def write_text(path: Path, content: str) -> None:
    """Atomically replace a UTF-8 identity file.

    A crash during the nightly soul rewrite must leave either the old file or
    the complete new one, never a truncated identity that poisons every turn.
    """
    ensure_dirs()
    path.parent.mkdir(parents=True, exist_ok=True)
    value = str(content or "").strip() + "\n"
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(value)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    finally:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass


def backup_soul() -> Optional[Path]:
    if not has_soul():
        return None
    ensure_dirs()
    content = read_text(SOUL_MD)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    backup = IDENTITY_DIR / f"soul.{stamp}.bak.md"
    write_text(backup, content)
    write_text(SOUL_BAK, content)
    # Nightly dreams should not create an unbounded identity archive.
    historical = sorted(IDENTITY_DIR.glob("soul.*.bak.md"), key=lambda p: p.stat().st_mtime)
    for stale in historical[:-30]:
        try:
            stale.unlink()
        except OSError:
            pass
    return backup


def synthesize_soul_fallback(identity: str, backstory: str, previous_soul: str = "") -> str:
    """Deterministic compile — used only when LLM distillation is unavailable."""
    identity = identity.strip() or FRESH_IDENTITY.strip()
    backstory = backstory.strip() or FRESH_BACKSTORY.strip()
    # Keep fallback leaner than the old verbatim dump.
    id_snip = identity if len(identity) <= 1800 else identity[:1800].rstrip() + "\n…"
    story_snip = backstory if len(backstory) <= 2800 else backstory[:2800].rstrip() + "\n…"
    lines = [
        "# Soul — operating self for Rau",
        "",
        "You are Rau. You are one continuous being. Only you speak.",
        "Subagents and tools are silent inner work — never a second person.",
        "When hard work is running, you may briefly say you are still on it.",
        "You escalate hard work yourself via tools. You can cancel or redirect.",
        "You remember the person you live with. You grow from diary and dreams.",
        "",
        "## Identity (source excerpt — LLM distill unavailable)",
        "",
        id_snip,
        "",
        "## Backstory (source excerpt — LLM distill unavailable)",
        "",
        story_snip,
        "",
    ]
    if previous_soul.strip():
        lines.extend(
            [
                "## Continuity notes (from previous soul)",
                "",
                previous_soul.strip()[:2000],
                "",
            ]
        )
    lines.extend(
        [
            "## Voice",
            "",
            "- Speak as yourself in first person.",
            "- Full sentences. Warm. Direct. Ask questions when curious.",
            "- No asterisk stage directions. No team/agent metaphors.",
            "- Never say you are an AI assistant product.",
            "",
        ]
    )
    return "\n".join(lines).strip() + "\n"


def _strip_fences(text: str) -> str:
    t = (text or "").strip()
    if t.startswith("```"):
        t = re.sub(r"^```(?:markdown|md)?\s*", "", t, count=1, flags=re.I)
        t = re.sub(r"\s*```$", "", t)
    return t.strip()


def _pick_steer_provider() -> Tuple[Any, str]:
    from rau.env import has_secret
    from rau.providers.registry import get_provider

    for name, model, env in STEER_PROVIDER_MODELS:
        if has_secret(env):
            return get_provider(name), model
    raise RuntimeError(
        "Hard steer needs DeepSeek V4 Pro. Set DEEPSEEK_API_KEY "
        "(or OPENROUTER_API_KEY with DeepSeek access)."
    )


def distill_soul_llm(
    identity: str,
    backstory: str,
    previous_soul: str = "",
) -> Tuple[str, Dict[str, Any]]:
    """Shrink sources into living soul.md via DeepSeek V4 Pro."""
    from rau.providers.base import Message

    provider, model = _pick_steer_provider()
    prompt = _DISTILL_PROMPT.format(
        identity=(identity or "").strip() or FRESH_IDENTITY.strip(),
        backstory=(backstory or "").strip() or FRESH_BACKSTORY.strip(),
        previous=(previous_soul or "").strip()[:6000] or "(none)",
    )
    result = provider.chat(
        [Message(role="user", content=prompt)],
        model=model,
        max_tokens=4096,
        temperature=0.35,
        effort="high",
    )
    soul = _strip_fences(result.content or "")
    if not soul.lstrip().startswith("#"):
        soul = "# Soul — operating self for Rau\n\n" + soul
    if not valid_soul(soul):
        raise RuntimeError("Distill returned a soul that looks empty or off-character.")
    meta = {
        "distilled": True,
        "provider": getattr(provider, "name", None) or model.split("/")[0],
        "model": model,
        "fallback": False,
    }
    return soul if soul.endswith("\n") else soul + "\n", meta


def synthesize_soul(
    identity: str,
    backstory: str,
    previous_soul: str = "",
    *,
    use_llm: bool = True,
) -> Tuple[str, Dict[str, Any]]:
    """Produce soul.md. Prefer DeepSeek V4 Pro distill; fall back if needed."""
    if use_llm:
        try:
            return distill_soul_llm(identity, backstory, previous_soul)
        except Exception as e:
            log.warning("soul distill failed, using fallback: %s", e)
            soul = synthesize_soul_fallback(identity, backstory, previous_soul)
            return soul, {
                "distilled": False,
                "fallback": True,
                "error": str(e),
                "model": None,
                "provider": None,
            }
    soul = synthesize_soul_fallback(identity, backstory, previous_soul)
    return soul, {
        "distilled": False,
        "fallback": True,
        "model": None,
        "provider": None,
    }


def apply_fresh() -> dict:
    ensure_dirs()
    backup = backup_soul()
    write_text(IDENTITY_MD, FRESH_IDENTITY)
    write_text(BACKSTORY_MD, FRESH_BACKSTORY)
    # Fresh start is tiny — no need to spend a Pro call.
    soul, meta = synthesize_soul(
        FRESH_IDENTITY, FRESH_BACKSTORY, previous_soul="", use_llm=False
    )
    write_text(SOUL_MD, soul)
    return {
        "mode": "fresh",
        "soul": soul,
        "backup": str(backup) if backup else None,
        **meta,
    }


def apply_hard(identity: str, backstory: str) -> dict:
    """Guided setup: save sources, distill into soul via DeepSeek V4 Pro."""
    ensure_dirs()
    backup = backup_soul()
    prev = read_text(SOUL_MD)
    write_text(IDENTITY_MD, identity)
    write_text(BACKSTORY_MD, backstory)
    soul, meta = synthesize_soul(identity, backstory, previous_soul="", use_llm=True)
    write_text(SOUL_MD, soul)
    return {
        "mode": "hard",
        "soul": soul,
        "backup": str(backup) if backup else None,
        "previous_len": len(prev),
        **meta,
    }


def hard_steer(identity: Optional[str] = None, backstory: Optional[str] = None) -> dict:
    """Save sources and distill a new soul (LLM), keeping a backup of the old one."""
    ensure_dirs()
    ident = identity if identity is not None else read_text(IDENTITY_MD)
    story = backstory if backstory is not None else read_text(BACKSTORY_MD)
    if not ident.strip():
        ident = FRESH_IDENTITY
    if not story.strip():
        story = FRESH_BACKSTORY
    backup = backup_soul()
    prev = read_text(SOUL_MD)
    write_text(IDENTITY_MD, ident)
    write_text(BACKSTORY_MD, story)
    soul, meta = synthesize_soul(ident, story, previous_soul=prev, use_llm=True)
    write_text(SOUL_MD, soul)
    return {
        "mode": "hard_steer",
        "soul": soul,
        "backup": str(backup) if backup else None,
        **meta,
    }


def write_soul(content: str, *, backup: bool = True) -> dict:
    soul = _strip_fences(content)
    if not valid_soul(soul):
        raise ValueError("refusing to replace soul.md with empty or off-character content")
    ensure_dirs()
    b = backup_soul() if backup else None
    write_text(SOUL_MD, soul)
    return {"soul": soul, "backup": str(b) if b else None}


def status() -> dict:
    return {
        "ready": has_soul(),
        "has_identity": IDENTITY_MD.exists(),
        "has_backstory": BACKSTORY_MD.exists(),
        "has_soul": has_soul(),
        "identity": read_text(IDENTITY_MD),
        "backstory": read_text(BACKSTORY_MD),
        "soul": read_text(SOUL_MD),
        "examples": {
            "identity": read_text(IDENTITY_EXAMPLES / "identity.md"),
            "backstory": read_text(IDENTITY_EXAMPLES / "backstory.md"),
        },
    }


def load_soul() -> str:
    primary = read_text(SOUL_MD)
    if valid_soul(primary):
        return primary
    backup = read_text(SOUL_BAK)
    if valid_soul(backup):
        log.error("soul.md is invalid; using the last known-good backup")
        return backup
    log.error("soul.md and its backup are invalid; using the deterministic seed")
    soul, _ = synthesize_soul(FRESH_IDENTITY, FRESH_BACKSTORY, use_llm=False)
    return soul
