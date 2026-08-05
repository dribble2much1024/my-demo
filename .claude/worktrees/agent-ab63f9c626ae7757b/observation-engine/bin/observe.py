#!/usr/bin/env python3
"""Observation Engine — 捕获 Claude Code 工具调用的输入输出，写入 JSONL 观测流。

用法: python3 observe.py pre|post
Hook JSON 从 stdin 读取。
"""

import json
import sys
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

OBSERVATIONS_DIR = Path.home() / ".claude" / "observations"
OBSERVATIONS_FILE = OBSERVATIONS_DIR / "observations.jsonl"
ERROR_LOG = OBSERVATIONS_DIR / "errors.log"
OUTPUT_MAX_CHARS = 2000


def log_error(msg: str) -> None:
    """静默记录错误，不阻塞 Hook。"""
    try:
        ts = datetime.now(timezone.utc).isoformat()
        with open(ERROR_LOG, "a", encoding="utf-8") as f:
            f.write(f"[{ts}] {msg}\n")
    except Exception:
        pass


def get_session_id() -> str:
    return os.environ.get("CLAUDE_SESSION_ID") or uuid.uuid4().hex[:12]


def truncate_output(data: dict) -> dict:
    """截断过长的工具输出，防止 JSONL 膨胀。"""
    if not isinstance(data, dict):
        return data
    result = {}
    for k, v in data.items():
        if isinstance(v, str) and len(v) > OUTPUT_MAX_CHARS:
            result[k] = v[:OUTPUT_MAX_CHARS] + "...[truncated]"
        elif isinstance(v, dict):
            result[k] = truncate_output(v)
        elif isinstance(v, list):
            result[k] = [
                (truncate_output(item) if isinstance(item, dict) else item)
                for item in v
            ]
        else:
            result[k] = v
    return result


def build_record(phase: str, hook_data: dict) -> dict | None:
    """从 Hook JSON 构造观测记录。"""
    try:
        tool_name = hook_data.get("tool_name", "")
        tool_input = hook_data.get("tool_input", {})

        record = {
            "session_id": get_session_id(),
            "ts": datetime.now(timezone.utc).isoformat(),
            "phase": phase,
            "tool": tool_name,
            "input": tool_input if isinstance(tool_input, dict) else {},
        }

        if phase == "post":
            output = hook_data.get("tool_output") or hook_data.get("output")
            if output is not None:
                if isinstance(output, str):
                    record["output_summary"] = output[:OUTPUT_MAX_CHARS]
                elif isinstance(output, dict):
                    record["output_summary"] = truncate_output(output)
                else:
                    record["output_summary"] = str(output)[:OUTPUT_MAX_CHARS]

        return record
    except Exception as e:
        log_error(f"build_record error: {e}")
        return None


def main() -> None:
    if len(sys.argv) < 2 or sys.argv[1] not in ("pre", "post"):
        log_error(f"invalid or missing phase argument: {sys.argv[1:]}")
        sys.exit(0)

    phase = sys.argv[1]

    try:
        raw = sys.stdin.read()
        if not raw.strip():
            return
        hook_data = json.loads(raw)
    except json.JSONDecodeError as e:
        log_error(f"stdin JSON parse error: {e}")
        return
    except Exception as e:
        log_error(f"stdin read error: {e}")
        return

    record = build_record(phase, hook_data)
    if record is None:
        return

    try:
        OBSERVATIONS_DIR.mkdir(parents=True, exist_ok=True)
        with open(OBSERVATIONS_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception as e:
        log_error(f"write error: {e}")


if __name__ == "__main__":
    main()
