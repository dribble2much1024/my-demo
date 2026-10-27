#!/usr/bin/env python3
"""TencentDB Agent Memory — HTTP 客户端 + 离线降级。

封装 /v3/tools/list 和 /v3/tools/call 的 HTTP 通信，
含重试/超时/认证/离线队列管理。

用法:
  from tdbank_client import TdbankClient, TdbankOffline
  client = TdbankClient("http://localhost:8080", api_key="xxx", team_id="my-team")
  if client.health_check():
      client.push_chat_memory(l0_asset, l1_assets)
  offline = TdbankOffline("~/.claude/tdbank")
  offline.export_session(data, "session-id")
"""

import json
import os
import socket
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# ── HTTP 客户端 ─────────────────────────────────────

class TdbankClient:
    """TencentDB Agent Memory API 客户端。"""

    def __init__(self, base_url: str, api_key: str = "",
                 team_id: str = "default", timeout: int = 30):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.team_id = team_id
        self.timeout = timeout
        self._conn_host = None
        self._conn_is_https = None

    def _parse_url(self):
        if self._conn_host is not None:
            return
        p = urlparse(self.base_url)
        self._conn_host = p.hostname or "localhost"
        self._conn_port = p.port or (443 if p.scheme == "https" else 80)
        self._conn_is_https = p.scheme == "https"
        self._conn_prefix = p.path or ""

    def _request(self, method: str, path: str,
                 body: dict | None = None) -> dict | None:
        """发起 HTTP 请求，返回 JSON 或 None。"""
        self._parse_url()
        full_path = self._conn_prefix + path
        body_bytes = json.dumps(body).encode("utf-8") if body else None

        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        for attempt in range(3):
            try:
                if self._conn_is_https:
                    import ssl
                    ctx = ssl.create_default_context()
                    conn = http.client.HTTPSConnection(
                        self._conn_host, self._conn_port, timeout=self.timeout, context=ctx)
                else:
                    conn = http.client.HTTPConnection(
                        self._conn_host, self._conn_port, timeout=self.timeout)

                conn.request(method, full_path, body=body_bytes, headers=headers)
                resp = conn.getresponse()
                data = resp.read().decode("utf-8")
                conn.close()

                if resp.status < 300:
                    return json.loads(data) if data else {"ok": True}
                else:
                    print(f"[tdbank] HTTP {resp.status}: {data[:200]}")
                    if 400 <= resp.status < 500:
                        return None  # 客户端错误不重试
            except (http.client.HTTPException, ConnectionRefusedError,
                    ConnectionError, socket.timeout, OSError) as e:
                if attempt < 2:
                    time.sleep(2 ** attempt)
                else:
                    print(f"[tdbank] Request failed after 3 attempts: {e}")
        return None

    def health_check(self) -> bool:
        result = self._request("GET", "/v3/tools/list")
        return result is not None

    def tools_list(self) -> dict | None:
        return self._request("GET", "/v3/tools/list")

    def tools_call(self, tool_name: str, params: dict) -> dict | None:
        return self._request("POST", "/v3/tools/call", {
            "tool": tool_name, "params": params})

    def push_chat_memory(self, layer: str, data: dict) -> str | None:
        """推送一层 Chat Memory 资产。返回 asset_id 或 None。"""
        result = self.tools_call("memory-core.chat-memory.store", {
            "team_id": self.team_id,
            "asset": {
                "type": "chat_memory",
                "layer": layer,
                "governance": {
                    "owner": data.get("agent_id", "unknown"),
                    "version": "1.0",
                    "status": "active",
                    "visibility": "team",
                },
                "data": data,
            },
        })
        if result and result.get("success"):
            return result.get("asset_id")
        return None

    def push_skill(self, skill_data: dict) -> str | None:
        """推送 Skill 资产。返回 asset_id 或 None。"""
        result = self.tools_call("memory-core.skill.store", {
            "team_id": self.team_id,
            "asset": {
                "type": "skill",
                "governance": {
                    "owner": skill_data.get("metadata", {}).get("source_session", "unknown"),
                    "version": "1.0",
                    "status": "active",
                    "visibility": "team",
                },
                "data": skill_data,
            },
        })
        if result and result.get("success"):
            return result.get("asset_id")
        return None


# ── 离线文件存储 ───────────────────────────────────

class TdbankOffline:
    """离线模式：所有操作降级为本地 JSON 文件。"""

    def __init__(self, base_dir: str = ""):
        if base_dir:
            self.base = Path(base_dir).expanduser().resolve()
        else:
            self.base = Path.home() / ".claude" / "tdbank"
        self.exports_dir = self.base / "exports"
        self.pending_dir = self.base / "pending"
        self.skills_dir = self.base / "skills"

    def _ensure_dirs(self):
        self.exports_dir.mkdir(parents=True, exist_ok=True)
        self.pending_dir.mkdir(parents=True, exist_ok=True)
        self.skills_dir.mkdir(parents=True, exist_ok=True)

    def export_session(self, data: dict, session_id: str,
                       filepath: str = "") -> Path:
        """写本地导出 JSON 文件。"""
        self._ensure_dirs()
        fname = filepath or f"tdbank-session-{session_id}.json"
        path = self.exports_dir / fname
        wrapper = {
            "manifest": {
                "session_id": session_id,
                "exported_at": datetime.now(timezone.utc).isoformat(),
                "version": "1.0",
                "source": "observation-engine",
            },
            "assets": data,
        }
        path.write_text(json.dumps(wrapper, indent=2, ensure_ascii=False),
                        encoding="utf-8")
        return path

    def export_skill(self, skill_data: dict, skill_hash: str) -> Path:
        """写本地 Skill JSON 文件。"""
        self._ensure_dirs()
        path = self.skills_dir / f"tdbank-skill-{skill_hash}.json"
        wrapper = {
            "manifest": {
                "type": "skill",
                "extracted_at": datetime.now(timezone.utc).isoformat(),
                "source": "observation-engine",
            },
            "skill": skill_data,
        }
        path.write_text(json.dumps(wrapper, indent=2, ensure_ascii=False),
                        encoding="utf-8")
        return path

    def queue_pending(self, data: dict, session_id: str) -> Path:
        """放入待推送队列。"""
        self._ensure_dirs()
        path = self.pending_dir / f"tdbank-session-{session_id}.json"
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False),
                        encoding="utf-8")
        return path

    def load_pending(self) -> list[dict]:
        """加载所有待推送数据。"""
        self._ensure_dirs()
        items = []
        for f in sorted(self.pending_dir.glob("*.json")):
            try:
                items.append(json.loads(f.read_text(encoding="utf-8")))
            except (json.JSONDecodeError, IOError):
                pass
        return items

    def flush_pending(self, success_ids: list[str]) -> int:
        """删除已成功推送的 pending 文件。"""
        self._ensure_dirs()
        removed = 0
        for sid in success_ids:
            f = self.pending_dir / f"tdbank-session-{sid}.json"
            if f.exists():
                f.unlink()
                removed += 1
        return removed

    def load_export(self, session_id: str) -> dict | None:
        """加载指定 session 的导出文件。"""
        path = self.exports_dir / f"tdbank-session-{session_id}.json"
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
        return None


# ── 顶层 Facade ────────────────────────────────────

class TdbankFacade:
    """统一门面：自动选择在线/离线路径。"""

    def __init__(self, config: dict):
        self.config = config
        self.online = None
        self.offline = TdbankOffline(config.get("export_dir", ""))

        if config.get("enabled") and not config.get("offline_mode"):
            self.online = TdbankClient(
                base_url=config.get("base_url", "http://localhost:8080"),
                api_key=config.get("api_key", ""),
                team_id=config.get("team_id", "default"),
            )
            if not self.online.health_check():
                print("[tdbank] Server unreachable, falling back to offline")
                self.online = None

    def push_chat_memory(self, layer: str, data: dict) -> str | None:
        self.offline.export_session({layer: data}, data.get("session_id", "unknown"))
        if self.online:
            return self.online.push_chat_memory(layer, data)
        return None

    def push_skill(self, skill_data: dict) -> str | None:
        skill_hash = skill_data.get("name", "unknown")
        self.offline.export_skill(skill_data, skill_hash)
        if self.online:
            return self.online.push_skill(skill_data)
        return None


if __name__ == "__main__":
    print("tdbank_client.py — 导入为模块使用:")
    print("  from tdbank_client import TdbankClient, TdbankOffline, TdbankFacade")
