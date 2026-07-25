"""MCP + Composio client (HTTP remote + optional stdio stub)."""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional

from rau.env import get_secret
from rau.memory.store import append_trace
from rau.paths import MCP_CONFIG, ensure_dirs


def load_mcp_config() -> Dict[str, Any]:
    ensure_dirs()
    if MCP_CONFIG.exists():
        return json.loads(MCP_CONFIG.read_text(encoding="utf-8"))
    return {"servers": {}}


class MCPClient:
    def __init__(self):
        self.cfg = load_mcp_config()

    def status(self) -> Dict[str, Any]:
        servers = {}
        for name, scfg in (self.cfg.get("servers") or {}).items():
            env_name = scfg.get("api_key_env") or ""
            servers[name] = {
                "enabled": bool(scfg.get("enabled")),
                "type": scfg.get("type"),
                "url": scfg.get("url"),
                "configured": bool(get_secret(env_name)) if env_name else True,
                "api_key_env": env_name,
            }
        return {"servers": servers}

    def composio_headers(self) -> Dict[str, str]:
        key = get_secret("COMPOSIO_API_KEY")
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
            oauth_url = managed.get("oauth_url")
            result = managed.get("result")
            if not oauth_url and isinstance(result, dict):
                # best-effort dig for a URL in MCP tool payload
                blob = json.dumps(result)
                if "http" in blob:
                    for part in blob.replace('"', " ").replace("'", " ").split():
                        if part.startswith("http") and "composio" in part:
                            oauth_url = part.rstrip(",}")
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
        if not scfg.get("enabled"):
            return {"ok": False, "error": "composio disabled"}
        key = get_secret(scfg.get("api_key_env") or "COMPOSIO_API_KEY")
        if not key:
            return {"ok": False, "error": "COMPOSIO_API_KEY not set", "needs_auth": True}

        url = scfg.get("url") or "https://connect.composio.dev/mcp"
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
            headers=self.composio_headers(),
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                body = json.loads(resp.read().decode("utf-8"))
            append_trace("mcp", {"tool": tool, "ok": True})
            return {"ok": True, "tool": tool, "result": body}
        except urllib.error.HTTPError as e:
            err = e.read().decode("utf-8", errors="replace")
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


MCP = MCPClient()
