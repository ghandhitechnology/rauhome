"""Load built-in and user-authored ``skills/*/SKILL.md`` files."""
from __future__ import annotations

import os
import re
import threading
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Dict, List, Optional

from rau.paths import SKILLS_DIR, ensure_dirs


@dataclass(frozen=True)
class Skill:
    name: str
    description: str
    body: str
    path: Path
    slash: str
    always: bool = True

    def prompt_block(self) -> str:
        return (
            f"## Active skill: {self.name}\n"
            f"{self.description}\n\n{self.body.strip()}"
        ).strip()


# These are materialized into the ignored root skills directory so both Rau's
# Python worker and the optional pi sidecar can refer to a real, readable file.
_BUILTINS: Dict[str, Dict[str, Any]] = {
    "grill-me": {
        "description": "Stress-test an idea with one incisive question at a time.",
        "body": "Ask exactly one focused question at a time. Challenge assumptions, constraints, evidence, failure modes, and trade-offs. Adapt the next question to the answer. Do not dump a questionnaire. When the idea is sufficiently tested, summarize the strongest plan and unresolved risks.",
    },
    "plan": {
        "description": "Turn an objective into an executable, ordered plan.",
        "body": "Clarify only a truly blocking ambiguity. Then produce a concrete ordered plan with outcomes, dependencies, validation, rollback points, and the next action. Keep the plan proportional to the task and prefer execution over ceremony.",
    },
    "read": {
        "description": "Inspect local project files safely before reasoning about them.",
        "body": "Use read_file before making claims about a file. Follow relevant imports and configuration. Summarize findings with exact paths. Never infer file contents from names alone.",
    },
    "write": {
        "description": "Create or update project files with verification.",
        "body": "Read existing files before changing them. Prefer edit_file for precise updates and write_file for new files. Preserve local conventions, avoid unrelated changes, and run the narrowest relevant validation after editing.",
    },
    "goal": {
        "description": "Set, inspect, clear, or advance Rau's durable active goal.",
        "body": "Treat the active goal as durable intent. Make progress concrete, append useful goal notes, expose blockers honestly, and never claim progress that did not happen. Ask one question only when the next action is genuinely ambiguous.",
    },
    "shell": {
        "description": "Run local shell commands deliberately and inspect their results.",
        "body": "Use run_shell for bounded, non-interactive commands. Start with read-only diagnostics. Explain destructive or irreversible actions and obtain confirmation. Check exit codes and stderr; do not report success from partial output.",
    },
    "search": {
        "description": "Research a question and synthesize evidence rather than guessing.",
        "body": "Define what must be established, search authoritative sources, compare conflicting evidence, and distinguish facts from inference. Return concise findings, source locations, and uncertainty. Escalate multi-step research to deep work.",
    },
    "remember": {
        "description": "Recall recent memory or save a durable note.",
        "body": "Use memory_read before claiming what was remembered. Use memory_write only for durable, useful facts or commitments. Avoid storing secrets, transient chatter, or unsupported assumptions. State clearly when memory has no relevant entry.",
    },
    "computer": {
        "description": "Operate the local computer carefully for user-directed tasks.",
        "body": "Inspect the current screen before acting. Take small reversible steps, verify each state change, and request confirmation for purchases, messages, account changes, deletion, or other consequential actions. Never guess coordinates after the screen changes.",
    },
    "summarize": {
        "description": "Compress material without losing decisions, evidence, or caveats.",
        "body": "Identify audience and purpose from context. Preserve decisions, action items, owners, constraints, evidence, and unresolved questions. Remove repetition without inventing certainty. Use headings or bullets only when they improve scanability.",
    },
}

_NAME = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
MAX_SKILL_BYTES = 256 * 1024
_cache_lock = threading.RLock()
_cache_signature: tuple[tuple[str, int, int], ...] = ()
_cache_skills: tuple[Skill, ...] = ()


def _normalise_name(name: str) -> str:
    return str(name or "").strip().lower().replace("_", "-")


def _render_builtin(name: str, spec: Dict[str, Any]) -> str:
    return (
        "---\n"
        f"name: {name}\n"
        f"description: {spec['description']}\n"
        f"slash: /{name}\n"
        "always: true\n"
        "---\n\n"
        f"{spec['body'].strip()}\n"
    )


def _materialize_builtins() -> None:
    ensure_dirs()
    for name, spec in _BUILTINS.items():
        path = SKILLS_DIR / name / "SKILL.md"
        if path.exists():
            continue
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_name(f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
            try:
                tmp.write_text(_render_builtin(name, spec), encoding="utf-8")
                os.replace(tmp, path)
            finally:
                tmp.unlink(missing_ok=True)
        except OSError:
            # Read-only installs still work from the in-package fallback below.
            pass


def _frontmatter(text: str) -> tuple[Dict[str, str], str]:
    if not text.startswith("---\n"):
        return {}, text.strip()
    end = text.find("\n---", 4)
    if end < 0:
        return {}, text.strip()
    meta: Dict[str, str] = {}
    for raw in text[4:end].splitlines():
        if ":" not in raw:
            continue
        key, value = raw.split(":", 1)
        meta[key.strip().lower()] = value.strip().strip('"').strip("'")
    return meta, text[end + 4 :].strip()


def _read_skill(path: Path, fallback_name: str) -> Optional[Skill]:
    try:
        # User skill directories are writable runtime content. Never follow a
        # planted link into ~/.ssh or another host path and never load a giant
        # file into every status/chat request.
        if path.is_symlink() or path.parent.is_symlink():
            return None
        if path.stat().st_size > MAX_SKILL_BYTES:
            return None
        meta, body = _frontmatter(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError):
        return None
    name = _normalise_name(meta.get("name") or fallback_name)
    if not _NAME.fullmatch(name) or not body:
        return None
    description = (meta.get("description") or f"Use the {name} skill.").strip()
    slash_name = _normalise_name(meta.get("slash") or name).removeprefix("/")
    slash = f"/{slash_name}" if _NAME.fullmatch(slash_name) else f"/{name}"
    always = meta.get("always", "true").lower() not in {"false", "no", "0"}
    return Skill(name, description, body, path, slash, always)


def _builtin_skill(name: str) -> Optional[Skill]:
    spec = _BUILTINS.get(name)
    if not spec:
        return None
    path = SKILLS_DIR / name / "SKILL.md"
    return Skill(
        name=name,
        description=str(spec["description"]),
        body=str(spec["body"]),
        path=path,
        slash=f"/{name}",
        always=True,
    )


def _skill_signature() -> tuple[tuple[str, int, int], ...]:
    entries: List[tuple[str, int, int]] = []
    if not SKILLS_DIR.exists():
        return ()
    for path in sorted(SKILLS_DIR.glob("*/SKILL.md")):
        try:
            stat = path.lstat()
            entries.append((str(path), stat.st_mtime_ns, stat.st_size))
        except OSError:
            continue
    return tuple(entries)


def all_skills() -> List[Skill]:
    global _cache_signature, _cache_skills
    _materialize_builtins()
    signature = _skill_signature()
    with _cache_lock:
        if signature == _cache_signature and _cache_skills:
            return list(_cache_skills)

    found: Dict[str, Skill] = {}
    if SKILLS_DIR.exists():
        for path in sorted(SKILLS_DIR.glob("*/SKILL.md")):
            skill = _read_skill(path, path.parent.name)
            if skill:
                found[skill.name] = skill
    for name in _BUILTINS:
        if name not in found:
            builtin = _builtin_skill(name)
            if builtin is not None:
                found[name] = builtin

    skills = sorted((s for s in found.values() if s is not None), key=lambda s: s.name)
    # A custom alias may not impersonate another skill's authoritative name or
    # an earlier alias. Fall back to /<name> rather than making command routing
    # depend on directory sort order.
    reserved = {skill.name for skill in skills}
    aliases: set[str] = set()
    safe: List[Skill] = []
    for skill in skills:
        alias = skill.slash.lstrip("/")
        if (alias in reserved and alias != skill.name) or alias in aliases:
            skill = replace(skill, slash=f"/{skill.name}")
            alias = skill.name
        aliases.add(alias)
        safe.append(skill)
    with _cache_lock:
        _cache_signature = signature
        _cache_skills = tuple(safe)
    return list(safe)


def load_skill(name: str) -> Optional[Skill]:
    wanted = _normalise_name(name).removeprefix("/")
    skills = all_skills()
    exact = next((skill for skill in skills if skill.name == wanted), None)
    if exact:
        return exact
    return next((skill for skill in skills if skill.slash.lstrip("/") == wanted), None)


def skills_public() -> List[Dict[str, Any]]:
    return [
        {
            "name": skill.name,
            "description": skill.description,
            "slash": skill.slash,
            "always": skill.always,
        }
        for skill in all_skills()
    ]
