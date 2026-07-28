"""Typed tool metadata, validation, result adaptation, and verification."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Callable, Dict, List, Optional

from rau.agent.danger import classify_tool
from rau.agent.tools import TOOL_SCHEMAS


@dataclass(frozen=True)
class ToolResult:
    ok: bool
    summary: str
    artifacts: List[str] = field(default_factory=list)
    mutations: List[str] = field(default_factory=list)
    evidence: List[Dict[str, Any]] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    effect_state: str = "none"
    raw: Dict[str, Any] = field(default_factory=dict, repr=False)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ToolDescriptor:
    name: str
    capability: str
    input_schema: Dict[str, Any]
    effect_class: str
    idempotent: bool
    approval_policy: str
    timeout_sec: float
    concurrency_key: str
    result_adapter: Callable[[Dict[str, Any]], ToolResult]
    verifier: Callable[[ToolResult], bool]


def _capability(name: str) -> str:
    if name.startswith("computer_") or name == "cua_action":
        return "computer_use"
    if "schedule" in name:
        return "scheduling"
    if name in {"run_shell", "read_file", "write_file", "edit_file"}:
        return "filesystem"
    if name.startswith("composio_"):
        return "external_apps"
    if name.startswith("memory_"):
        return "memory"
    if name.endswith("_panel"):
        return "visual"
    if "kittens" in name or "chess" in name:
        return "game"
    return "coordination"


def _effect(name: str) -> str:
    readonly = {
        "read_file",
        "memory_read",
        "use_skill",
        "list_skills",
        "list_schedules",
        "finish",
        "spawn_subagent",
        "computer_status",
        "computer_observe",
        "computer_inspect_ui",
        "computer_wait_for",
        "computer_assert",
    }
    if name in readonly:
        return "read"
    if name in {"composio_execute", "computer_act", "cua_action", "run_schedule_now"}:
        return "external_mutation"
    return "local_mutation"


def _adapt(raw: Dict[str, Any]) -> ToolResult:
    value = raw if isinstance(raw, dict) else {"ok": False, "error": str(raw)}
    ok = bool(value.get("ok", True)) and not bool(value.get("error"))
    candidate = value.get("summary")
    if not isinstance(candidate, (str, int, float, bool)):
        candidate = value.get("error") if not ok else None
    summary = str(candidate or ("Completed" if ok else "Failed"))
    return ToolResult(
        ok=ok,
        summary=summary[:2000],
        artifacts=[str(item) for item in value.get("artifacts") or []][:50],
        mutations=[str(item) for item in value.get("mutations") or []][:50],
        evidence=[
            item if isinstance(item, dict) else {"detail": str(item)}
            for item in value.get("evidence") or value.get("verification") or []
        ][:50],
        errors=[] if ok else [str(value.get("error") or "tool failed")[:2000]],
        effect_state=(
            "unknown"
            if value.get("unknown_effect")
            else ("applied" if ok and value.get("mutations") else "none")
        ),
        raw=value,
    )


def _verified(result: ToolResult) -> bool:
    return result.ok and result.effect_state != "unknown"


def _build_registry() -> Dict[str, ToolDescriptor]:
    registry: Dict[str, ToolDescriptor] = {}
    for wrapper in TOOL_SCHEMAS:
        function = wrapper.get("function") or {}
        name = str(function.get("name") or "")
        if not name:
            continue
        effect = _effect(name)
        capability = _capability(name)
        # A panel writes nothing but pixels: it lands in a sandboxed frame that
        # cannot reach the network or this app, and taking it down is one call.
        # Asking the user to approve each one would mean a commissioned
        # dashboard stops halfway and waits, which is the opposite of the
        # silent worker it is meant to be.
        needs_approval = effect != "read" and capability != "visual"
        registry[name] = ToolDescriptor(
            name=name,
            capability=capability,
            input_schema=dict(function.get("parameters") or {}),
            effect_class=effect,
            idempotent=effect == "read",
            approval_policy="exact" if needs_approval else "never",
            timeout_sec=600.0 if name == "run_shell" else 120.0,
            concurrency_key=(
                "computer"
                if capability == "computer_use"
                else ("mutation" if needs_approval else "")
            ),
            result_adapter=_adapt,
            verifier=_verified,
        )
    return registry


REGISTRY = _build_registry()


def descriptor(name: str) -> Optional[ToolDescriptor]:
    return REGISTRY.get(name)


def validate_arguments(name: str, arguments: Any) -> Dict[str, Any]:
    """Validate the assembled argument object before approval or execution."""
    item = descriptor(name)
    if item is None:
        raise ValueError(f"unknown tool: {name}")
    if not isinstance(arguments, dict):
        raise ValueError(f"{name} arguments must be an object")
    schema = item.input_schema
    properties = schema.get("properties") or {}
    required = schema.get("required") or []
    missing = [key for key in required if key not in arguments]
    if missing:
        raise ValueError(f"{name} missing required arguments: {', '.join(missing)}")
    unknown = [
        key
        for key in arguments
        if key not in properties and not str(key).startswith("_")
    ]
    if unknown:
        raise ValueError(f"{name} received unknown arguments: {', '.join(unknown)}")
    for key, value in arguments.items():
        rule = properties.get(key)
        if not isinstance(rule, dict):
            continue
        expected = rule.get("type")
        valid = {
            "string": isinstance(value, str),
            "number": isinstance(value, (int, float)) and not isinstance(value, bool),
            "integer": isinstance(value, int) and not isinstance(value, bool),
            "boolean": isinstance(value, bool),
            "object": isinstance(value, dict),
            "array": isinstance(value, list),
        }.get(str(expected), True)
        if not valid:
            raise ValueError(f"{name}.{key} must be {expected}")
        if "enum" in rule and value not in rule["enum"]:
            raise ValueError(f"{name}.{key} has an unsupported value")
        if isinstance(value, (int, float)):
            if "minimum" in rule and value < rule["minimum"]:
                raise ValueError(f"{name}.{key} is below minimum")
            if "maximum" in rule and value > rule["maximum"]:
                raise ValueError(f"{name}.{key} exceeds maximum")
        if isinstance(value, list) and value and "maxItems" in rule:
            if len(value) > int(rule["maxItems"]):
                raise ValueError(f"{name}.{key} has too many items")
    # Keep classification in one place while preserving descriptor metadata.
    classify_tool(name, arguments)
    return arguments


def adapt_result(name: str, raw: Dict[str, Any]) -> ToolResult:
    item = descriptor(name)
    result = (item.result_adapter if item else _adapt)(raw)
    if not result.ok or item is None:
        return result

    artifacts = list(result.artifacts)
    mutations = list(result.mutations)
    evidence = list(result.evidence)
    path = str(result.raw.get("path") or "").strip()

    # Tool implementations predate the structured completion contract and
    # many return only {ok, path}. Adapt those real effects into the harness
    # ledger so the model cannot "forget" a mutation or claim verification it
    # never performed.
    if name in {"write_file", "edit_file"}:
        if path and path not in artifacts:
            artifacts.append(path)
        if not mutations:
            mutations.append(f"{name}: {path or 'workspace file'}")
    elif item.effect_class != "read" and name not in {"finish", "run_shell"}:
        if not mutations:
            mutations.append(f"{name}: completed")
        if not evidence:
            evidence.append(
                {
                    "kind": "tool_receipt",
                    "tool": name,
                    "detail": result.summary,
                }
            )
    elif item.effect_class == "read" and name not in {
        "finish",
        "use_skill",
        "list_skills",
        "spawn_subagent",
    }:
        if not evidence:
            evidence.append(
                {
                    "kind": "tool_result",
                    "tool": name,
                    "detail": path or result.summary,
                }
            )
    elif name == "run_shell" and not evidence:
        evidence.append(
            {
                "kind": "command",
                "tool": name,
                "detail": f"command exited {result.raw.get('code', 0)}",
            }
        )

    return ToolResult(
        ok=result.ok,
        summary=result.summary,
        artifacts=artifacts,
        mutations=mutations,
        evidence=evidence,
        errors=list(result.errors),
        effect_state=(
            "applied" if mutations and result.effect_state == "none" else result.effect_state
        ),
        raw=result.raw,
    )
