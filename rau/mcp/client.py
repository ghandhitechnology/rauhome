"""MCP + Composio client (HTTP remote + optional stdio stub)."""
from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional

from rau.env import get_secret
from rau.memory.store import append_trace
from rau.paths import MCP_CONFIG, ensure_dirs

MCP_TIMEOUT_SEC = 60
MAX_MCP_RESPONSE_BYTES = 4 * 1024 * 1024


def load_mcp_config() -> Dict[str, Any]:
    ensure_dirs()
    if MCP_CONFIG.exists():
        try:
            loaded = json.loads(MCP_CONFIG.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {"servers": {}, "error": "invalid MCP config"}
        if not isinstance(loaded, dict) or not isinstance(
            loaded.get("servers", {}), dict
        ):
            return {"servers": {}, "error": "invalid MCP config"}
        return loaded
    return {"servers": {}}


class MCPClient:
    def __init__(self):
        self.cfg = load_mcp_config()

    def status(self) -> Dict[str, Any]:
        servers = {}
        for name, scfg in (self.cfg.get("servers") or {}).items():
            if not isinstance(scfg, dict):
                servers[str(name)] = {
                    "enabled": False,
                    "configured": False,
                    "error": "invalid server config",
                }
                continue
            raw_env = scfg.get("api_key_env") or ""
            env_name = raw_env if isinstance(raw_env, str) else ""
            servers[name] = {
                "enabled": bool(scfg.get("enabled")),
                "type": scfg.get("type"),
                "url": scfg.get("url"),
                "configured": bool(get_secret(env_name)) if env_name else True,
                "api_key_env": env_name,
            }
        return {"servers": servers}

    def composio_headers(self, key: Optional[str] = None) -> Dict[str, str]:
        key = key if key is not None else get_secret("COMPOSIO_API_KEY")
        headers = {"Content-Type": "application/json"}
        if key:
            headers["x-api-key"] = key
        return headers

    def composio_search(self, query: str) -> Dict[str, Any]:
        return self._composio_tool("COMPOSIO_SEARCH_TOOLS", {"query": query})

    def composio_execute(self, tools: List[Dict[str, Any]]) -> Dict[str, Any]:
        return self._composio_tool(
            "COMPOSIO_MULTI_EXECUTE_TOOL",
            {"tools": tools},
        )

    def composio_manage_connections(self, action: str = "list") -> Dict[str, Any]:
        return self._composio_tool(
            "COMPOSIO_MANAGE_CONNECTIONS",
            {"action": action},
        )

    def composio_connect(self) -> Dict[str, Any]:
        """Start / resume Composio app OAuth connections for the user."""
        connect_url = "https://connect.composio.dev"
        app_url = "https://app.composio.dev"
        key = get_secret("COMPOSIO_API_KEY")
        if not key:
            return {
                "ok": False,
                "needs_key": True,
                "error": "COMPOSIO_API_KEY not set",
                "open_url": app_url,
                "connect_url": connect_url,
                "hint": "Save your Composio API key first, then open Connect to authorize apps.",
            }

        managed = self.composio_manage_connections("list")
        oauth_url = None
        if isinstance(managed, dict):
            candidate = managed.get("oauth_url")
            oauth_url = candidate if self._safe_composio_url(candidate) else None
            result = managed.get("result")
            if not oauth_url and isinstance(result, dict):
                # best-effort dig for a URL in MCP tool payload
                blob = json.dumps(result)
                if "http" in blob:
                    for part in blob.replace('"', " ").replace("'", " ").split():
                        candidate = part.rstrip(",}")
                        if self._safe_composio_url(candidate):
                            oauth_url = candidate
                            break

        return {
            "ok": True,
            "needs_key": False,
            "open_url": oauth_url or connect_url,
            "connect_url": connect_url,
            "app_url": app_url,
            "manage": managed,
        }

    def _composio_tool(self, tool: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        scfg = (self.cfg.get("servers") or {}).get("composio") or {}
        if not isinstance(scfg, dict):
            return {"ok": False, "error": "invalid composio server config"}
        if not scfg.get("enabled"):
            return {"ok": False, "error": "composio disabled"}
        raw_env = scfg.get("api_key_env") or "COMPOSIO_API_KEY"
        if not isinstance(raw_env, str):
            return {"ok": False, "error": "invalid composio api_key_env"}
        key = get_secret(raw_env)
        if not key:
            return {"ok": False, "error": "COMPOSIO_API_KEY not set", "needs_auth": True}

        url = scfg.get("url") or "https://connect.composio.dev/mcp"
        if not self._safe_endpoint(url):
            return {"ok": False, "tool": tool, "error": "unsafe MCP endpoint URL"}
        # Composio MCP uses JSON-RPC style tools/call when available.
        # Fallback: return a structured stub the agent can narrate if endpoint differs.
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": tool, "arguments": arguments},
        }
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            headers=self.composio_headers(key),
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=MCP_TIMEOUT_SEC) as resp:
                raw = resp.read(MAX_MCP_RESPONSE_BYTES + 1)
            if len(raw) > MAX_MCP_RESPONSE_BYTES:
                raise RuntimeError(
                    f"MCP response exceeds {MAX_MCP_RESPONSE_BYTES} bytes"
                )
            body = json.loads(raw.decode("utf-8"))
            if not isinstance(body, dict):
                raise RuntimeError("MCP response must be a JSON object")
            rpc_error = body.get("error")
            if rpc_error:
                message = (
                    rpc_error.get("message")
                    if isinstance(rpc_error, dict)
                    else str(rpc_error)
                )
                append_trace(
                    "mcp", {"tool": tool, "ok": False, "error": str(message)[:500]}
                )
                return {
                    "ok": False,
                    "tool": tool,
                    "error": f"MCP error: {message or 'unknown error'}",
                }
            append_trace("mcp", {"tool": tool, "ok": True})
            return {"ok": True, "tool": tool, "result": body}
        except urllib.error.HTTPError as e:
            err = e.read(4000).decode("utf-8", errors="replace")
            append_trace("mcp", {"tool": tool, "ok": False, "error": err[:500]})
            # Soft-fail with guidance rather than crashing the being
            return {
                "ok": False,
                "tool": tool,
                "error": f"HTTP {e.code}: {err[:500]}",
                "hint": "Complete Composio OAuth at https://connect.composio.dev if needed.",
                "oauth_url": "https://connect.composio.dev",
            }
        except Exception as e:
            append_trace("mcp", {"tool": tool, "ok": False, "error": str(e)})
            return {
                "ok": False,
                "tool": tool,
                "error": str(e),
                "oauth_url": "https://connect.composio.dev",
            }

    @staticmethod
    def _safe_endpoint(url: Any) -> bool:
        if not isinstance(url, str):
            return False
        parsed = urllib.parse.urlparse(url)
        if parsed.username or parsed.password or parsed.fragment:
            return False
        if parsed.scheme == "https" and bool(parsed.hostname):
            return True
        return parsed.scheme == "http" and parsed.hostname in {
            "127.0.0.1",
            "::1",
            "localhost",
        }

    @staticmethod
    def _safe_composio_url(url: Any) -> bool:
        if not isinstance(url, str):
            return False
        parsed = urllib.parse.urlparse(url)
        host = (parsed.hostname or "").lower()
        return (
            not parsed.username
            and not parsed.password
            and not parsed.fragment
            and parsed.scheme == "https"
            and (
                host == "composio.dev" or host.endswith(".composio.dev")
            )
        )


MCP = MCPClient()
