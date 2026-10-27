#!/usr/bin/env python3
"""TencentDB Agent Memory — 配置管理。

配置加载优先级（从高到低）:
  1. 环境变量: TDBANK_BASE_URL, TDBANK_API_KEY, TDBANK_TEAM_ID, TDBANK_ENABLED
  2. ~/.claude/tdbank/config.json
  3. 项目本地 observation-engine/tdbank_config.json
  4. 内置默认值

用法:
  from eval_tdbank_config import TdbankConfig
  cfg = TdbankConfig()
  cfg.load()
  if cfg.get("enabled"):
      ...
"""

import json
import os
import sys
from pathlib import Path

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

DEFAULT_CONFIG = {
    "base_url": "http://localhost:8080",
    "api_key": "",
    "team_id": "default",
    "agent_id": os.environ.get("COMPUTERNAME", os.environ.get("HOSTNAME", "agent-001")),
    "enabled": False,
    "quality_threshold": 80,
    "skill_threshold": 90,
    "offline_mode": True,
    "auto_sync": False,
    "sync_skills": False,
    "export_dir": str(Path.home() / ".claude" / "tdbank" / "exports"),
    "pending_dir": str(Path.home() / ".claude" / "tdbank" / "pending"),
    "skills_dir": str(Path.home() / ".claude" / "tdbank" / "skills"),
}

ENV_MAP = {
    "TDBANK_BASE_URL": "base_url",
    "TDBANK_API_KEY": "api_key",
    "TDBANK_TEAM_ID": "team_id",
    "TDBANK_AGENT_ID": "agent_id",
    "TDBANK_ENABLED": "enabled",
    "TDBANK_QUALITY_THRESHOLD": "quality_threshold",
    "TDBANK_SKILL_THRESHOLD": "skill_threshold",
    "TDBANK_OFFLINE_MODE": "offline_mode",
    "TDBANK_AUTO_SYNC": "auto_sync",
    "TDBANK_SYNC_SKILLS": "sync_skills",
}


class TdbankConfig:
    """TencentDB 集成配置，支持多源加载与优先级合并。"""

    def __init__(self, config_paths: list[str] | None = None):
        self._data = dict(DEFAULT_CONFIG)
        self._loaded = False
        self._config_paths = config_paths or [
            str(Path.home() / ".claude" / "tdbank" / "config.json"),
            str(Path(__file__).resolve().parent.parent / "tdbank_config.json"),
        ]

    def load(self) -> dict:
        """加载配置（多层合并），返回最终配置字典。"""
        # 1. JSON 文件（先低优先级，后高优先级覆盖）
        for cpath in self._config_paths:
            self._load_from_json(Path(cpath))

        # 2. 环境变量（最高优先级）
        self._load_from_env()

        # 类型转换
        self._coerce_types()
        self._loaded = True
        return self._data

    def _load_from_json(self, path: Path):
        if not path.exists():
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            for k, v in data.items():
                if k in DEFAULT_CONFIG:
                    self._data[k] = v
        except (json.JSONDecodeError, IOError):
            pass

    def _load_from_env(self):
        for env_var, config_key in ENV_MAP.items():
            val = os.environ.get(env_var)
            if val is not None:
                self._data[config_key] = val

    def _coerce_types(self):
        """将字符串值转换为正确的类型。"""
        bool_keys = ["enabled", "offline_mode", "auto_sync", "sync_skills"]
        int_keys = ["quality_threshold", "skill_threshold"]

        for k in bool_keys:
            v = self._data.get(k)
            if isinstance(v, str):
                self._data[k] = v.lower() in ("1", "true", "yes", "on")

        for k in int_keys:
            v = self._data.get(k)
            if isinstance(v, str):
                try:
                    self._data[k] = int(v)
                except ValueError:
                    pass

    def get(self, key: str, default=None):
        if not self._loaded:
            self.load()
        return self._data.get(key, default)

    def to_dict(self) -> dict:
        if not self._loaded:
            self.load()
        return dict(self._data)

    def validate(self) -> list[str]:
        """验证配置完整性，返回缺失项列表。"""
        if not self._loaded:
            self.load()
        missing = []
        if self._data.get("enabled") and not self._data.get("offline_mode"):
            if not self._data.get("base_url"):
                missing.append("base_url (TDBANK_BASE_URL)")
        return missing

    def save(self, path: str = "") -> Path:
        """保存当前配置到 JSON 文件。"""
        if not self._loaded:
            self.load()
        target = Path(path) if path else Path(self._config_paths[0])
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(self._data, indent=2, ensure_ascii=False),
            encoding="utf-8")
        return target


if __name__ == "__main__":
    cfg = TdbankConfig()
    cfg.load()
    print(json.dumps(cfg.to_dict(), indent=2, ensure_ascii=False))
