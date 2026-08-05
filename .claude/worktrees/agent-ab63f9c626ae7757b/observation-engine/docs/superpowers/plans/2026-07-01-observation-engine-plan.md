# Observation Engine 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 通过 Claude Code Hook 机制 100% 捕获工具调用，写入 JSONL 观测流，并在会话结束时自动轮转归档。

**Architecture:** 两个纯 Python 脚本 + Hook 配置更新。observe.py 从 stdin 读取 Hook JSON 写 JSONL；observations_rotate.py 在超阈值时按月归档旧数据。

**Tech Stack:** Python 3（标准库，零外部依赖），JSONL 存储

## Global Constraints

- 零外部 pip 依赖，纯 Python 标准库
- 所有错误静默处理，绝不抛异常阻塞 Hook 链路
- 存储路径：`~/.claude/observations/`
- 脚本路径：`~/.claude/bin/`
- JSONL 字段：session_id, ts, phase, tool, input, output_summary

---

### Task 1: 创建目录结构

**Files:**
- Create: `~/.claude/bin/` (directory)
- Create: `~/.claude/observations/` (directory)

**Interfaces:**
- Produces: 两个目录供后续 Task 使用

- [ ] **Step 1: 创建目录**

```bash
mkdir -p ~/.claude/bin ~/.claude/observations
```

验证：

```bash
ls -la ~/.claude/bin ~/.claude/observations
```

---

### Task 2: 创建 observe.py

**Files:**
- Create: `~/.claude/bin/observe.py`

**Interfaces:**
- Consumes: `~/.claude/observations/` 目录（Task 1 创建）
- Consumes: `$CLAUDE_SESSION_ID` 环境变量（Claude Code 提供）
- Produces: 写入 `~/.claude/observations/observations.jsonl`

- [ ] **Step 1: 编写 observe.py**

```python
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
```

- [ ] **Step 2: 验证脚本语法**

```bash
python3 -c "import py_compile; py_compile.compile('~/.claude/bin/observe.py', doraise=True)"
```

---

### Task 3: 创建 observations_rotate.py

**Files:**
- Create: `~/.claude/bin/observations_rotate.py`

**Interfaces:**
- Consumes: `~/.claude/observations/observations.jsonl`
- Produces: `~/.claude/observations/observations-YYYY-MM.jsonl`（归档文件）
- 修改: `~/.claude/observations/observations.jsonl`（仅保留 30 天内数据）

- [ ] **Step 1: 编写 observations_rotate.py**

```python
#!/usr/bin/env python3
"""Observation Rotate — 在 JSONL 超阈值时按月归档旧数据，主文件保留最近 30 天。

由 Stop Hook 在每次会话结束时触发。
"""

import json
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path

OBSERVATIONS_DIR = Path.home() / ".claude" / "observations"
OBSERVATIONS_FILE = OBSERVATIONS_DIR / "observations.jsonl"
MAX_SIZE_BYTES = 5 * 1024 * 1024  # 5MB
MAX_LINES = 8000
RETENTION_DAYS = 30


def should_rotate() -> bool:
    """检查是否需要轮转。"""
    if not OBSERVATIONS_FILE.exists():
        return False

    file_size = OBSERVATIONS_FILE.stat().st_size
    if file_size > MAX_SIZE_BYTES:
        return True

    line_count = 0
    with open(OBSERVATIONS_FILE, "r", encoding="utf-8") as f:
        for _ in f:
            line_count += 1
            if line_count > MAX_LINES:
                return True
    return False


def parse_ts(record: dict) -> datetime | None:
    """从记录中提取时间戳。"""
    ts = record.get("ts", "")
    try:
        # ISO 8601: "2026-07-01T15:30:00+00:00" or "2026-07-01T15:30:00Z"
        ts = ts.replace("Z", "+00:00")
        return datetime.fromisoformat(ts)
    except (ValueError, TypeError):
        return None


def rotate() -> None:
    """将 30 天前的记录按月归档，主文件只保留最近 30 天。"""
    if not OBSERVATIONS_FILE.exists():
        return

    cutoff = datetime.now(timezone.utc) - timedelta(days=RETENTION_DAYS)
    recent: list[str] = []
    archive_buckets: dict[str, list[str]] = {}

    with open(OBSERVATIONS_FILE, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
                ts = parse_ts(record)
                if ts is None or ts < cutoff:
                    month_key = (
                        ts.strftime("%Y-%m")
                        if ts
                        else datetime.now(timezone.utc).strftime("%Y-%m")
                    )
                    archive_buckets.setdefault(month_key, []).append(line)
                else:
                    recent.append(line)
            except json.JSONDecodeError:
                recent.append(line)

    # 写入归档文件
    for month_key, lines in archive_buckets.items():
        archive_file = OBSERVATIONS_DIR / f"observations-{month_key}.jsonl"
        with open(archive_file, "a", encoding="utf-8") as f:
            for line in lines:
                f.write(line + "\n")

    # 覆盖写回主文件（仅最近 30 天）
    with open(OBSERVATIONS_FILE, "w", encoding="utf-8") as f:
        for line in recent:
            f.write(line + "\n")


def main() -> None:
    try:
        OBSERVATIONS_DIR.mkdir(parents=True, exist_ok=True)
        if should_rotate():
            rotate()
    except Exception:
        pass  # 静默处理，不阻塞 Stop Hook


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: 验证脚本语法**

```bash
python3 -c "import py_compile; py_compile.compile('~/.claude/bin/observations_rotate.py', doraise=True)"
```

---

### Task 4: 更新 settings.json Hook 配置

**Files:**
- Modify: `~/.claude/settings.json`

**Interfaces:**
- Consumes: `~/.claude/bin/observe.py`（Task 2）
- Consumes: `~/.claude/bin/observations_rotate.py`（Task 3）
- Produces: 正确的 Hook command 路径

- [ ] **Step 1: 更新 Hook 命令路径**

将 `~/.claude/hooks/observe.sh` 替换为 `python3 ~/.claude/bin/observe.py`，Stop Hook 中追加 `python3 ~/.claude/bin/observations_rotate.py`。

在 `~/.claude/settings.json` 的 `hooks` 块中做以下三处替换：

1. `"command": "~/.claude/hooks/observe.sh pre"` → `"command": "python3 ~/.claude/bin/observe.py pre"`
2. `"command": "~/.claude/hooks/observe.sh post"` → `"command": "python3 ~/.claude/bin/observe.py post"`
3. `"command": "~/.claude/bin/auto-analyze-instincts.py && ~/.claude/bin/auto-evolve.py"` → `"command": "python3 ~/.claude/bin/observations_rotate.py"`

- [ ] **Step 2: 验证 JSON 格式**

```bash
python3 -c "import json; json.load(open('~/.claude/settings.json')); print('OK')"
```

---

### Task 5: 端到端验证

- [ ] **Step 1: 模拟 PreToolUse Hook 调用**

```bash
echo '{"tool_name":"Bash","tool_input":{"command":"echo hello"}}' | python3 ~/.claude/bin/observe.py pre
cat ~/.claude/observations/observations.jsonl | tail -1 | python3 -m json.tool
```

预期：输出一条 phase=pre 的 JSON 记录，包含 session_id, ts, tool=Bash, input.command="echo hello"

- [ ] **Step 2: 模拟 PostToolUse Hook 调用**

```bash
echo '{"tool_name":"Bash","tool_input":{"command":"echo hello"},"tool_output":"hello\\n"}' | python3 ~/.claude/bin/observe.py post
cat ~/.claude/observations/observations.jsonl | tail -1 | python3 -m json.tool
```

预期：输出一条 phase=post 的 JSON 记录，包含 output_summary

- [ ] **Step 3: 验证错误容错**

```bash
echo '' | python3 ~/.claude/bin/observe.py post && echo "NO CRASH"
echo 'not valid json' | python3 ~/.claude/bin/observe.py post && echo "NO CRASH"
python3 ~/.claude/bin/observations_rotate.py && echo "NO CRASH"
```

预期：三条命令都输出 `NO CRASH`，无异常

- [ ] **Step 4: 清理测试数据**

```bash
rm -f ~/.claude/observations/observations.jsonl ~/.claude/observations/errors.log
```
