"""
Containment for the agent's local tools.

Two separate mechanisms, because they buy different amounts of safety:

* Path containment (`resolve_in_root`) is airtight. Every path a file tool
  touches is resolved through symlinks and proven to sit inside the project
  root before it is opened.
* Shell containment leans on macOS seatbelt (`sandbox-exec`), which is present
  on every Mac. It confines writes to the project root and the caches a build
  needs; reads and network are left open. When the binary is missing the tool
  fails closed unless `allow_unconfined_shell` was explicitly enabled.
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import List, Optional, Tuple

from rau.paths import ROOT

# Resolved once: ROOT itself can sit behind a symlink (/tmp, /var, a linked
# home), and every comparison below is against real paths.
REAL_ROOT = Path(os.path.realpath(ROOT))

SANDBOX_EXEC = Path("/usr/bin/sandbox-exec")

NO_SANDBOX_WARNING = (
    "sandbox-exec unavailable — this command ran unconfined on the host, "
    "with only the confirm gate for protection."
)


class PathEscape(Exception):
    """A tool was handed a path that resolves outside the project root."""

    def __init__(self, given: str, resolved: Path):
        self.given = given
        self.resolved = resolved
        super().__init__(
            f"path escapes the project root: {given!r} resolves to {resolved} "
            f"which is outside {REAL_ROOT}"
        )


def resolve_in_root(given: str) -> Path:
    """
    Turn a tool-supplied path into an absolute path proven to be under ROOT.

    Symlinks are followed on every component that exists, so a link planted
    inside the tree cannot be used to hand back a target outside it. A path
    that does not exist yet is fine — a write creates it — but the existing
    prefix it hangs off still has to resolve inside the root.
    """
    raw = (given or "").strip()
    if not raw:
        raise PathEscape(given or "", REAL_ROOT)

    p = Path(raw).expanduser()
    if not p.is_absolute():
        p = REAL_ROOT / p

    resolved = Path(os.path.realpath(p))
    if resolved != REAL_ROOT and REAL_ROOT not in resolved.parents:
        raise PathEscape(raw, resolved)
    return resolved


def _writable_roots() -> List[Path]:
    """Directories a confined command may write to."""
    home = Path(os.path.expanduser("~"))
    candidates = [
        REAL_ROOT,
        Path(os.path.realpath(tempfile.gettempdir())),
        Path("/private/tmp"),
        Path("/private/var/tmp"),
        # Package managers and compilers refuse to run without a cache; these
        # hold no user data, so opening them keeps builds working without
        # widening the blast radius to the rest of $HOME.
        home / "Library" / "Caches",
        home / ".cache",
    ]
    seen: List[Path] = []
    for c in candidates:
        if c not in seen:
            seen.append(c)
    return seen


def _sbpl_string(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _profile() -> str:
    subpaths = " ".join(f"(subpath {_sbpl_string(str(p))})" for p in _writable_roots())
    return "\n".join(
        [
            "(version 1)",
            # Start permissive and subtract: the goal is a write jail, not a
            # general-purpose sandbox. Reads, exec and network stay open so
            # ordinary build and inspection commands still work.
            "(allow default)",
            "(deny file-write*)",
            f"(allow file-write* {subpaths})",
            "(allow file-write-data"
            ' (literal "/dev/null") (literal "/dev/zero")'
            ' (literal "/dev/dtracehelper") (regex #"^/dev/tty.*"))',
        ]
    )


def sandbox_enabled() -> bool:
    from rau.providers.registry import load_settings

    return bool(load_settings().get("shell_sandbox", True))


def allow_unconfined_shell() -> bool:
    """Explicit escape hatch for hosts without macOS seatbelt."""
    from rau.providers.registry import load_settings

    return bool(load_settings().get("allow_unconfined_shell", False))


def shell_argv(command: str) -> Tuple[List[str], Optional[str]]:
    """
    Build the argv for a shell command, plus a warning when it is unconfined.

    A non-empty warning means nothing is holding the command inside the
    project. The execution layer refuses the missing-seatbelt case by default
    and returns the warning only for an explicit override.
    """
    inner = ["/bin/sh", "-c", command]
    if not sandbox_enabled():
        return inner, "shell_sandbox disabled in settings — command ran unconfined."
    if not SANDBOX_EXEC.exists():
        return inner, NO_SANDBOX_WARNING
    return [str(SANDBOX_EXEC), "-p", _profile(), *inner], None
