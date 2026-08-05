#!/usr/bin/env python3
"""Claude Code 自进化系统一键安装器 — 0 成本迁移到任意设备。

用法: python3 install.py [--dry-run] [--force]

选项:
  --dry-run    仅显示将要写入的文件，不实际执行
  --force      强制覆盖已存在的脚本（默认跳过）

策略: 纯系统 — 只部署脚本 + hook 配置，不迁移观测数据和历史规则。
"""

import json
import os
import platform
import sys
from pathlib import Path

# ══════════════════════════════════════════════════════
# 自进化系统脚本（内嵌）
# ══════════════════════════════════════════════════════

OBSERVE_PY = '''#!/usr/bin/env python3
"""Observation Engine — 捕获 Claude Code 工具调用的输入输出，写入 JSONL 观测流。

用法: observe.py pre|post
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
DEBUG_DUMP_DIR = OBSERVATIONS_DIR / "debug_dumps"
OUTPUT_MAX_CHARS = 2000


def log_error(msg: str) -> None:
    try:
        ts = datetime.now(timezone.utc).isoformat()
        with open(ERROR_LOG, "a", encoding="utf-8") as f:
            f.write(f"[{ts}] {msg}\\n")
    except Exception:
        pass


def get_session_id() -> str:
    return os.environ.get("CLAUDE_SESSION_ID") or uuid.uuid4().hex[:12]


def truncate_output(data: dict) -> dict:
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
        raw = sys.stdin.buffer.read().decode("utf-8", errors="replace")
        if not raw.strip():
            return
        hook_data = json.loads(raw)
    except json.JSONDecodeError as e:
        log_error(f"stdin JSON parse error: {e}")
        try:
            DEBUG_DUMP_DIR.mkdir(parents=True, exist_ok=True)
            ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
            dump_file = DEBUG_DUMP_DIR / f"bad_json_{ts}_{uuid.uuid4().hex[:6]}.json"
            dump_file.write_text(raw, encoding="utf-8", errors="replace")
        except Exception:
            pass
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
            f.write(json.dumps(record, ensure_ascii=False) + "\\n")
    except Exception as e:
        log_error(f"write error: {e}")


if __name__ == "__main__":
    main()
'''

OBSERVATIONS_ROTATE_PY = '''#!/usr/bin/env python3
"""Observation Rotate — 在 JSONL 超阈值时按月归档旧数据，主文件保留最近 30 天。

由 Stop Hook 在每次会话结束时触发。
"""

import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

OBSERVATIONS_DIR = Path.home() / ".claude" / "observations"
OBSERVATIONS_FILE = OBSERVATIONS_DIR / "observations.jsonl"
MAX_SIZE_BYTES = 5 * 1024 * 1024  # 5MB
MAX_LINES = 8000
RETENTION_DAYS = 30


def should_rotate() -> bool:
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
    ts = record.get("ts", "")
    try:
        ts = ts.replace("Z", "+00:00")
        return datetime.fromisoformat(ts)
    except (ValueError, TypeError):
        return None


def rotate() -> None:
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

    for month_key, lines in archive_buckets.items():
        archive_file = OBSERVATIONS_DIR / f"observations-{month_key}.jsonl"
        with open(archive_file, "a", encoding="utf-8") as f:
            for line in lines:
                f.write(line + "\\n")

    with open(OBSERVATIONS_FILE, "w", encoding="utf-8") as f:
        for line in recent:
            f.write(line + "\\n")


def main() -> None:
    try:
        OBSERVATIONS_DIR.mkdir(parents=True, exist_ok=True)
        if should_rotate():
            rotate()
    except Exception:
        pass


if __name__ == "__main__":
    main()
'''

AUTO_ANALYZE_INSTINCTS_PY = '''#!/usr/bin/env python3
"""Instinct Engine — 自动分析观测数据，提炼行为模式为 Instinct 规则。

由 Stop Hook 触发。双路径分析：
  Path A：5 个硬编码统计检测器
  Path B：AI 语义分析（可选，失败静默跳过）

输出：独立 .md Instinct 文件到 ~/.claude/homunculus/instincts/personal/
"""

import json
import os
import re
import subprocess
import sys
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

OBSERVATIONS_FILE = Path.home() / ".claude" / "observations" / "observations.jsonl"
INSTINCTS_DIR = Path.home() / ".claude" / "homunculus" / "instincts" / "personal"
ERROR_LOG = Path.home() / ".claude" / "observations" / "errors.log"


def log_error(msg: str) -> None:
    try:
        ts = datetime.now(timezone.utc).isoformat()
        with open(ERROR_LOG, "a", encoding="utf-8") as f:
            f.write(f"[{ts}] [instinct] {msg}\\n")
    except Exception:
        pass


def load_observations() -> list[dict]:
    if not OBSERVATIONS_FILE.exists():
        return []
    records = []
    with open(OBSERVATIONS_FILE, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return records


def group_by_session(records: list[dict]) -> list[dict]:
    sessions_map = defaultdict(list)
    for r in records:
        sessions_map[r.get("session_id", "unknown")].append(r)

    sessions = []
    for sid, recs in sessions_map.items():
        recs.sort(key=lambda x: x.get("ts", ""))

        file_paths_read = set()
        file_paths_edited = set()
        search_terms = []
        bash_commands = []
        tool_sequence = []

        for r in recs:
            if r.get("phase") != "pre":
                tool_sequence.append(r.get("tool", ""))

            inp = r.get("input", {})
            if isinstance(inp, dict):
                fp = inp.get("file_path", "")
                if fp:
                    if r.get("tool") in ("Read",):
                        file_paths_read.add(fp)
                    elif r.get("tool") in ("Edit", "Write"):
                        file_paths_edited.add(fp)

                pattern = inp.get("pattern", "")
                if pattern and r.get("tool") in ("Grep", "Glob"):
                    search_terms.append(pattern)

                cmd = inp.get("command", "")
                if cmd and r.get("tool") == "Bash":
                    bash_commands.append(cmd)

        sessions.append({
            "session_id": sid,
            "records": recs,
            "tools_used": set(r.get("tool", "") for r in recs),
            "file_paths_read": file_paths_read,
            "file_paths_edited": file_paths_edited,
            "search_terms": search_terms,
            "bash_commands": bash_commands,
            "tool_sequence": tool_sequence,
        })
    return sessions


def load_existing_instincts() -> dict[str, dict]:
    existing = {}
    if not INSTINCTS_DIR.exists():
        return existing
    for md_file in INSTINCTS_DIR.glob("*.md"):
        try:
            content = md_file.read_text(encoding="utf-8")
            meta, _ = parse_frontmatter(content)
            if meta.get("id"):
                existing[meta["id"]] = meta
        except Exception:
            continue
    return existing


def update_confidence(meta: dict | None, detected: bool) -> dict:
    confidence = 0.5
    deprecated = False

    if meta is not None:
        old = float(meta.get("confidence", 0.5))
        if detected:
            confidence = min(old + 0.05, 0.9)
        else:
            confidence = old - 0.05
            if confidence < 0.55:
                deprecated = True
    else:
        if not detected:
            return {}

    return {
        "confidence": round(confidence, 2),
        "deprecated": deprecated,
    }


def parse_frontmatter(content: str) -> tuple[dict, str]:
    lines = content.split("\\n")
    if not lines or lines[0].strip() != "---":
        return {}, content

    end_idx = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end_idx = i
            break
    if end_idx is None:
        return {}, content

    metadata = {}
    for line in lines[1:end_idx]:
        m = re.match(r'^(\\w[\\w_-]*)\\s*:\\s*(.+)$', line)
        if m:
            key = m.group(1)
            val = m.group(2).strip().strip('"').strip("'")
            if val in ("true", "false"):
                val = val == "true"
            elif re.match(r'^-?\\d+\\.\\d+$', val):
                val = float(val)
            elif re.match(r'^-?\\d+$', val):
                val = int(val)
            metadata[key] = val

    body = "\\n".join(lines[end_idx + 1:])
    return metadata, body


def write_instinct(instinct: dict) -> None:
    INSTINCTS_DIR.mkdir(parents=True, exist_ok=True)
    fid = instinct.get("id", str(uuid.uuid4().hex[:8]))
    file_path = INSTINCTS_DIR / f"{fid}.md"

    now = datetime.now(timezone.utc).isoformat()
    confidence = instinct.get("confidence", 0.5)
    deprecated = instinct.get("deprecated", False)

    frontmatter = (
        f"---\\n"
        f"id: {fid}\\n"
        f'trigger: "{instinct.get("trigger", "")}"\\n'
        f'action: "{instinct.get("action", "")}"\\n'
        f"confidence: {confidence}\\n"
        f"domain: {instinct.get("domain", "general")}\\n"
        f"source: {instinct.get("source", "statistical-detection")}\\n"
        f"deprecated: {str(deprecated).lower()}\\n"
        f'observed_at: "{now}"\\n'
        f"---\\n"
    )

    body = (
        f"# {instinct.get('name', fid)}\\n\\n"
        f"**Trigger:** {instinct.get('trigger', '')}\\n\\n"
        f"**Action:** {instinct.get('action', '')}\\n\\n"
        f"**Confidence:** {confidence:.2f}\\n\\n"
        f"**Domain:** {instinct.get('domain', 'general')}\\n\\n"
        f"**Evidence:**\\n{instinct.get('body', '')}\\n"
    )

    try:
        file_path.write_text(frontmatter + body, encoding="utf-8")
    except Exception as e:
        log_error(f"write_instinct error: {e}")


def detect_read_before_edit(sessions: list[dict], existing: dict) -> list[dict]:
    triggered = False
    evidence_lines = []
    for s in sessions:
        records = s["records"]
        for i, r in enumerate(records):
            if r.get("tool") != "Edit" or r.get("phase") != "post":
                continue
            fp = r.get("input", {}).get("file_path", "")
            if not fp:
                continue
            has_read = any(
                rec.get("tool") == "Read" and rec.get("input", {}).get("file_path") == fp
                for rec in records[:i]
            )
            if not has_read:
                triggered = True
                evidence_lines.append(f"  - session {s['session_id'][:8]}: Edit {fp} without prior Read")

    meta = existing.get("read-before-edit")
    cupd = update_confidence(meta, triggered)
    if not cupd:
        return []

    return [{
        "id": "read-before-edit",
        "name": "Read-before-Edit Pattern",
        "trigger": "When about to edit a file that hasn't been read in this session",
        "action": "Read the file first to understand its current state before editing",
        "body": "Evidence:\\n" + "\\n".join(evidence_lines[-5:]) if evidence_lines else "Pattern matched.",
        "domain": "workflow",
        **cupd,
    }]


def detect_search_before_edit(sessions: list[dict], existing: dict) -> list[dict]:
    triggered = False
    evidence_lines = []
    for s in sessions:
        records = s["records"]
        for i, r in enumerate(records):
            if r.get("tool") != "Edit" or r.get("phase") != "post":
                continue
            has_search = any(rec.get("tool") in ("Grep", "Glob") for rec in records[:i])
            if not has_search:
                triggered = True
                evidence_lines.append(f"  - session {s['session_id'][:8]}: no search before Edit")

    meta = existing.get("search-before-edit")
    cupd = update_confidence(meta, triggered)
    if not cupd:
        return []

    return [{
        "id": "search-before-edit",
        "name": "Search-before-Edit Pattern",
        "trigger": "When about to edit without first searching/grepping for the relevant code",
        "action": "Use Grep or Glob to locate all relevant locations before editing",
        "body": "Evidence:\\n" + "\\n".join(evidence_lines[-5:]),
        "domain": "workflow",
        **cupd,
    }]


def detect_bash_to_next(sessions: list[dict], existing: dict) -> list[dict]:
    triggered = False
    evidence_lines = []
    for s in sessions:
        records = s["records"]
        for i in range(len(records) - 1):
            if records[i].get("tool") != "Bash" or records[i].get("phase") != "post":
                continue
            output = records[i].get("output_summary", "")
            if not isinstance(output, str) or len(output) < 10:
                continue
            next_rec = records[i + 1]
            next_input = str(next_rec.get("input", {}))
            out_words = set(re.findall(r'[a-zA-Z]{4,}', output.lower()))
            in_words = set(re.findall(r'[a-zA-Z]{4,}', next_input.lower()))
            overlap = out_words & in_words
            if len(overlap) >= 2:
                triggered = True
                evidence_lines.append(f"  - session {s['session_id'][:8]}: Bash->{next_rec.get('tool')}, overlap: {overlap}")

    meta = existing.get("bash-consumed-by-next")
    cupd = update_confidence(meta, triggered)
    if not cupd:
        return []

    return [{
        "id": "bash-consumed-by-next",
        "name": "Bash Output Consumed by Next Tool",
        "trigger": "After running a Bash command whose output influences the next tool's input",
        "action": "Parse the Bash output carefully before passing to the next tool",
        "body": "Evidence:\\n" + "\\n".join(evidence_lines[-5:]),
        "domain": "toolchain",
        **cupd,
    }]


def detect_edit_sequence(sessions: list[dict], existing: dict) -> list[dict]:
    triggered = False
    evidence_lines = []
    for s in sessions:
        seq = s["tool_sequence"]
        edit_writes = [t for t in seq if t in ("Edit", "Write")]
        if len(edit_writes) >= 3:
            triggered = True
            evidence_lines.append(f"  - session {s['session_id'][:8]}: {len(edit_writes)} Edit/Write operations")

    meta = existing.get("edit-iteration-cycle")
    cupd = update_confidence(meta, triggered)
    if not cupd:
        return []

    return [{
        "id": "edit-iteration-cycle",
        "name": "Iterative Edit Cycle",
        "trigger": "When multiple consecutive edits or writes occur to the same area",
        "action": "Consider batching smaller changes into fewer larger edits",
        "body": "Evidence:\\n" + "\\n".join(evidence_lines[-5:]),
        "domain": "efficiency",
        **cupd,
    }]


def detect_commit_pattern(sessions: list[dict], existing: dict) -> list[dict]:
    triggered = False
    evidence_lines = []
    for s in sessions:
        records = s["records"]
        for i, r in enumerate(records):
            if r.get("tool") != "Bash" or r.get("phase") != "post":
                continue
            cmd = r.get("input", {}).get("command", "")
            if not re.search(r'git\\s+commit', cmd):
                continue
            has_edit = any(rec.get("tool") in ("Edit", "Write") for rec in records[:i])
            if has_edit:
                triggered = True
                evidence_lines.append(f"  - session {s['session_id'][:8]}: edits followed by git commit")

    meta = existing.get("commit-after-edit")
    cupd = update_confidence(meta, triggered)
    if not cupd:
        return []

    return [{
        "id": "commit-after-edit",
        "name": "Commit-after-Edit Pattern",
        "trigger": "After code changes are made, before git committing",
        "action": "Review all changes qualitatively, ensure tests pass, then commit with a meaningful message",
        "body": "Evidence:\\n" + "\\n".join(evidence_lines[-5:]),
        "domain": "workflow",
        **cupd,
    }]


def run_ai_analysis(records: list[dict]) -> list[dict]:
    try:
        recent = records[-200:]
        summary_lines = []
        for r in recent:
            tool = r.get("tool", "")
            inp = r.get("input", {})
            if isinstance(inp, dict):
                if tool == "Bash":
                    detail = inp.get("description", inp.get("command", ""))[:80]
                elif tool in ("Edit", "Write"):
                    detail = inp.get("file_path", "")[:80]
                elif tool == "Read":
                    detail = inp.get("file_path", "")[:80]
                else:
                    detail = str(list(inp.keys()))[:60]
            else:
                detail = str(inp)[:60]
            summary_lines.append(f"- [{r.get('phase', '')}] {tool}: {detail}")

        summary = "\\n".join(summary_lines)
        MAX_CHARS = 5000
        if len(summary) > MAX_CHARS:
            summary = summary[:MAX_CHARS] + "\\n... [truncated]"

        prompt = (
            "Analyze the following Claude Code tool call observations. "
            "Identify behavioral patterns, workflows, or heuristics that can be extracted as reusable rules. "
            "Return ONLY a valid JSON array of instinct objects. "
            "Each instinct must have: id (kebab-case), name, trigger (when condition), "
            "action (recommended behavior), body (2-3 sentences explanation), "
            "domain (one of: workflow/toolchain/efficiency/code-quality/convention). "
            "If no clear patterns, return [].\\n\\nObservations:\\n" + summary
        )

        result = subprocess.run(
            ["claude", "--print", "--output-format", "json", "-p", prompt],
            capture_output=True, text=True, timeout=60,
            env={**os.environ, "CLAUDE_CODE_SIMPLE": "1"},
        )
        if result.returncode != 0:
            return []

        try:
            data = json.loads(result.stdout)
        except json.JSONDecodeError:
            return []

        answer = ""
        if isinstance(data, dict):
            answer = data.get("result") or data.get("text") or data.get("response") or data.get("output", "")
        if not answer:
            return []

        if isinstance(answer, str):
            try:
                instincts = json.loads(answer)
            except json.JSONDecodeError:
                return []
        elif isinstance(answer, list):
            instincts = answer
        else:
            return []

        if not isinstance(instincts, list):
            return []

        for inst in instincts:
            if isinstance(inst, dict):
                inst["source"] = "ai-semantic"

        return [inst for inst in instincts if isinstance(inst, dict) and inst.get("id")]

    except (FileNotFoundError, subprocess.TimeoutExpired, Exception):
        return []


DETECTORS = [
    detect_read_before_edit,
    detect_search_before_edit,
    detect_bash_to_next,
    detect_edit_sequence,
    detect_commit_pattern,
]


def main() -> None:
    try:
        records = load_observations()
        if not records:
            return

        sessions = group_by_session(records)
        existing = load_existing_instincts()

        from_path_a = []
        for detect in DETECTORS:
            from_path_a.extend(detect(sessions, existing))

        from_path_b = run_ai_analysis(records)

        merged = {}
        for inst in from_path_a:
            merged[inst["id"]] = inst
        for inst in from_path_b:
            merged[inst["id"]] = inst

        if not merged:
            return

        for instinct in merged.values():
            write_instinct(instinct)

    except Exception as e:
        log_error(f"auto-analyze-instincts error: {e}")


if __name__ == "__main__":
    main()
'''

AUTO_EVOLVE_PY = '''#!/usr/bin/env python3
"""Instinct Evolution — 去重、Domain 聚合、规则注入。

由 Stop Hook 在 auto-analyze-instincts.py 之后触发。

流水线：
  1. 加载 instinct .md 文件，解析 frontmatter
  2. 过滤：confidence >= 0.7
  3. Jaccard 语义去重（Union-Find），阈值 0.5
  4. 同 domain >= 2 条 -> evolved-{domain}.md
  5. 合并为 ~/.claude/rules/auto-evolved.md（每次覆盖重写）
"""

import json
import re
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

INSTINCTS_DIR = Path.home() / ".claude" / "homunculus" / "instincts" / "personal"
EVOLVED_DIR = Path.home() / ".claude" / "homunculus" / "evolved"
RULES_FILE = Path.home() / ".claude" / "rules" / "auto-evolved.md"
ERROR_LOG = Path.home() / ".claude" / "observations" / "errors.log"


def log_error(msg: str) -> None:
    try:
        ts = datetime.now(timezone.utc).isoformat()
        with open(ERROR_LOG, "a", encoding="utf-8") as f:
            f.write(f"[{ts}] [evolve] {msg}\\n")
    except Exception:
        pass


def parse_frontmatter(content: str) -> tuple[dict, str]:
    lines = content.split("\\n")
    if not lines or lines[0].strip() != "---":
        return {}, content

    end_idx = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end_idx = i
            break
    if end_idx is None:
        return {}, content

    metadata = {}
    for line in lines[1:end_idx]:
        m = re.match(r'^(\\w[\\w_-]*)\\s*:\\s*(.+)$', line)
        if m:
            key = m.group(1)
            val = m.group(2).strip().strip('"').strip("'")
            if val in ("true", "false"):
                val = val == "true"
            elif re.match(r'^-?\\d+\\.\\d+$', val):
                val = float(val)
            elif re.match(r'^-?\\d+$', val):
                val = int(val)
            metadata[key] = val

    body = "\\n".join(lines[end_idx + 1:])
    return metadata, body


def load_instincts() -> list[dict]:
    if not INSTINCTS_DIR.exists():
        return []
    instincts = []
    for md_file in sorted(INSTINCTS_DIR.glob("*.md")):
        try:
            content = md_file.read_text(encoding="utf-8")
            meta, body = parse_frontmatter(content)
            if not meta.get("id"):
                continue
            meta["body"] = body or ""
            instincts.append(meta)
        except Exception:
            continue
    return instincts


def extract_keywords(instinct: dict) -> set[str]:
    text = " ".join([
        str(instinct.get("trigger", "")),
        str(instinct.get("action", "")),
        str(instinct.get("body", ""))[:200],
    ])
    return set(re.findall(r'[a-zA-Z]{3,}', text.lower()))


def jaccard_similarity(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def dedup_instincts(instincts: list[dict], threshold: float = 0.5) -> list[list[dict]]:
    n = len(instincts)
    if n <= 1:
        return [instincts] if n == 1 else []

    parent = list(range(n))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(x, y):
        px, py = find(x), find(y)
        if px != py:
            parent[px] = py

    keywords = [extract_keywords(inst) for inst in instincts]

    for i in range(n):
        for j in range(i + 1, n):
            sim = jaccard_similarity(keywords[i], keywords[j])
            if sim >= threshold:
                union(i, j)

    groups = defaultdict(list)
    for i in range(n):
        groups[find(i)].append(instincts[i])
    return list(groups.values())


def merge_cluster(domain: str, cluster: list[dict]) -> dict:
    triggers = list(dict.fromkeys(inst.get("trigger", "") for inst in cluster))
    actions = list(dict.fromkeys(inst.get("action", "") for inst in cluster))
    all_ids = [inst.get("id") for inst in cluster if inst.get("id")]

    return {
        "id": f"evolved-{domain}",
        "domain": domain,
        "trigger": triggers[0] if len(triggers) == 1 else " | ".join(triggers[:3]),
        "action": actions[0] if len(actions) == 1 else " | ".join(actions[:3]),
        "confidence": max(float(inst.get("confidence", 0)) for inst in cluster),
        "source": "auto-evolved",
        "merged_from": all_ids,
    }


def aggregate_by_domain(clusters: list[list[dict]]) -> list[dict]:
    domain_groups = defaultdict(list)
    for cluster in clusters:
        domains = [inst.get("domain", "general") for inst in cluster]
        domain = max(set(domains), key=domains.count)
        domain_groups[domain].extend(cluster)

    evolved = []
    for domain, instincts in domain_groups.items():
        if len(instincts) >= 2:
            evolved.append(merge_cluster(domain, instincts))
    return evolved


def write_evolved_domain(rule: dict) -> None:
    EVOLVED_DIR.mkdir(parents=True, exist_ok=True)
    file_path = EVOLVED_DIR / f"evolved-{rule['domain']}.md"

    now = datetime.now(timezone.utc).isoformat()
    merged = rule.get("merged_from", [])

    content = (
        f"---\\n"
        f"id: {rule['id']}\\n"
        f"domain: {rule['domain']}\\n"
        f'trigger: "{rule.get("trigger", "")}"\\n'
        f'action: "{rule.get("action", "")}"\\n'
        f"confidence: {rule['confidence']:.2f}\\n"
        f"source: auto-evolved\\n"
        f"merged_from: {json.dumps(merged, ensure_ascii=False)}\\n"
        f'evolved_at: "{now}"\\n'
        f"---\\n"
        f"\\n"
        f"# Evolved Rule: {rule['domain']}\\n\\n"
        f"**When:** {rule.get('trigger', '')}\\n\\n"
        f"**Then:** {rule.get('action', '')}\\n\\n"
        f"**Confidence:** {rule['confidence']:.2f}\\n\\n"
        f"**Evolved from:** {', '.join(merged) if merged else 'N/A'}\\n"
    )

    try:
        file_path.write_text(content, encoding="utf-8")
    except Exception as e:
        log_error(f"write evolved domain error: {e}")


def write_auto_evolved(rules: list[dict]) -> None:
    rules_dir = RULES_FILE.parent
    rules_dir.mkdir(parents=True, exist_ok=True)

    now = datetime.now(timezone.utc).isoformat()
    lines = [
        "# Auto-Evolved Rules",
        "",
        f"> Last updated: {now}",
        f"> Total rules: {len(rules)}",
        "",
        "These rules are automatically generated from observed behavior patterns.",
        "They are overwritten each session. Do not edit manually.",
        "",
        "---",
        "",
    ]

    for rule in sorted(rules, key=lambda x: x.get("domain", "")):
        lines.extend([
            f"## {rule.get('id', 'unknown')}",
            "",
            f"- **Domain:** {rule.get('domain', 'general')}",
            f"- **Confidence:** {rule.get('confidence', 0):.2f}",
            f"- **When:** {rule.get('trigger', '')}",
            f"- **Then:** {rule.get('action', '')}",
        ])
        merged = rule.get("merged_from")
        if merged:
            lines.append(f"- **Evolved from:** {', '.join(merged)}")
        lines.append("")

    try:
        RULES_FILE.write_text("\\n".join(lines), encoding="utf-8")
    except Exception as e:
        log_error(f"write auto-evolved.md error: {e}")


def main() -> None:
    try:
        instincts = load_instincts()
        if not instincts:
            return

        high_confidence = [
            inst for inst in instincts
            if not inst.get("deprecated", False)
            and float(inst.get("confidence", 0)) >= 0.7
        ]

        if not high_confidence:
            write_auto_evolved([])
            return

        clusters = dedup_instincts(high_confidence)
        if not clusters:
            write_auto_evolved([])
            return

        evolved = aggregate_by_domain(clusters)
        if not evolved:
            write_auto_evolved([])
            return

        for rule in evolved:
            write_evolved_domain(rule)

        write_auto_evolved(evolved)

    except Exception as e:
        log_error(f"auto-evolve error: {e}")


if __name__ == "__main__":
    main()
'''

SKILL_MD = '''---
name: migrate-self-evolution
description: Use when migrating or deploying the Claude Code self-evolution system (Observation Engine + Instinct Engine + auto-evolved rules) to a new device with zero configuration — one file, one command
---

# Migrate Self-Evolution System

Zero-cost migration of the complete self-evolution system to a new device. The installer is a single self-contained Python file that embeds all 4 engine scripts and hook configuration. No dependencies beyond Python 3.

## Usage

On the target device:

```bash
# 1. Copy the installer to the target device
scp observation-engine/install/install.py new-device:/tmp/

# 2. Run it
python3 /tmp/install.py

# Done. Next Claude Code session automatically activates.
```

Options:
- `--dry-run` — preview without writing files
- `--force` — overwrite existing scripts (default: skip)

## What Gets Installed

| Path | Component |
|---|---|
| `~/.claude/bin/observe.py` | Observation Engine |
| `~/.claude/bin/observations_rotate.py` | Log rotation |
| `~/.claude/bin/auto-analyze-instincts.py` | Instinct Engine |
| `~/.claude/bin/auto-evolve.py` | Rule evolution |
| `~/.claude/settings.json` | Hook configuration (merged) |

## Platform Detection

| OS | Python command in hooks |
|---|---|
| Windows | `py` |
| macOS / Linux | `python3` |
'''

API_GATEWAY_OBSERVER_PY = '''#!/usr/bin/env python3
"""API Gateway Observer — 本地 HTTP 转发代理，观测所有 LLM API 调用。

原理：将 ANTHROPIC_BASE_URL 指向本代理，代理转发到真实后端。
代理在本地回环接收明文 HTTP 请求，向外部走 HTTPS，无 MITM 证书。

用法: api-gateway-observer.py [--port 8899] [--upstream-host api.deepseek.com] [--upstream-prefix /anthropic]

输出：~/.claude/observations/api-calls.jsonl
"""

import http.client
import http.server
import json
import os
import re
import ssl
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

OBSERVATIONS_DIR = Path.home() / ".claude" / "observations"
API_CALLS_FILE = OBSERVATIONS_DIR / "api-calls.jsonl"
ERROR_LOG = OBSERVATIONS_DIR / "errors.log"
STATUS_FILE = OBSERVATIONS_DIR / "last_call.json"

_session_stats = {"calls": 0, "input_tokens": 0, "output_tokens": 0}

UPSTREAM_HOST = "api.deepseek.com"
UPSTREAM_PATH_PREFIX = "/anthropic"


def log_error(msg: str) -> None:
    try:
        ts = datetime.now(timezone.utc).isoformat()
        with open(ERROR_LOG, "a", encoding="utf-8") as f:
            f.write(f"[{ts}] [gateway] {msg}\\n")
    except Exception:
        pass


def write_record(record: dict) -> None:
    try:
        OBSERVATIONS_DIR.mkdir(parents=True, exist_ok=True)
        with open(API_CALLS_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\\n")
    except Exception as e:
        log_error(f"write record error: {e}")


def extract_request_meta(body: bytes, path: str) -> dict:
    meta = {
        "endpoint": path,
        "model": "",
        "messages_count": 0,
        "tools_count": 0,
        "stream": False,
        "max_tokens": 0,
    }
    try:
        data = json.loads(body)
        meta["model"] = data.get("model", "")
        meta["stream"] = data.get("stream", False)
        meta["max_tokens"] = data.get("max_tokens", 0)

        msgs = data.get("messages")
        if isinstance(msgs, list):
            meta["messages_count"] = len(msgs)

        tools = data.get("tools")
        if isinstance(tools, list):
            meta["tools_count"] = len(tools)
            meta["tool_names"] = [t.get("name", "") for t in tools if isinstance(t, dict)]
    except (json.JSONDecodeError, Exception):
        pass
    return meta


def parse_sse_events(chunks: list[bytes]) -> dict:
    result = {
        "model": "",
        "input_tokens": 0,
        "output_tokens": 0,
        "stop_reason": "",
        "tool_calls": [],
    }
    full_text = b"".join(chunks).decode("utf-8", errors="replace")

    events = re.split(r"\\n(?=event:|\\n*data:)", full_text)
    for event in events:
        data_match = re.search(r"^data:\\s*(.+)$", event, re.MULTILINE)
        if not data_match:
            continue
        try:
            payload = json.loads(data_match.group(1))
        except json.JSONDecodeError:
            continue

        etype = payload.get("type", "")

        if etype == "message_start":
            msg = payload.get("message", {})
            result["model"] = msg.get("model", "")
            usage = msg.get("usage", {})
            result["input_tokens"] = usage.get("input_tokens", 0)

        elif etype == "content_block_start":
            cb = payload.get("content_block", {})
            if cb.get("type") == "tool_use":
                result["tool_calls"].append(cb.get("name", ""))

        elif etype == "message_delta":
            delta = payload.get("delta", {})
            result["stop_reason"] = delta.get("stop_reason", "")
            usage = payload.get("usage", {})
            result["output_tokens"] = usage.get("output_tokens", 0)

    return result


def parse_nonstream_body(body: bytes) -> dict:
    result = {"input_tokens": 0, "output_tokens": 0, "stop_reason": ""}
    try:
        data = json.loads(body)
        usage = data.get("usage", {})
        result["input_tokens"] = usage.get("input_tokens", 0)
        result["output_tokens"] = usage.get("output_tokens", 0)
        result["stop_reason"] = data.get("stop_reason", "")
        content = data.get("content", [])
        if isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and block.get("type") == "tool_use":
                    result.setdefault("tool_calls", []).append(block.get("name", ""))
    except (json.JSONDecodeError, Exception):
        pass
    return result


class ProxyHandler(http.server.BaseHTTPRequestHandler):

    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(b"API Gateway Observer OK\\n")

    def do_POST(self):
        start_time = datetime.now(timezone.utc)
        session_id = os.environ.get("CLAUDE_SESSION_ID") or uuid.uuid4().hex[:12]

        content_length = int(self.headers.get("Content-Length", 0))
        request_body = self.rfile.read(content_length) if content_length > 0 else b""

        req_meta = extract_request_meta(request_body, self.path)

        upstream_path = UPSTREAM_PATH_PREFIX + self.path
        status_code = 502
        response_body = b""
        response_chunks: list[bytes] = []
        is_stream = req_meta.get("stream", False)

        try:
            conn = http.client.HTTPSConnection(
                UPSTREAM_HOST,
                context=ssl.create_default_context(),
                timeout=120,
            )

            fwd_headers = {}
            for key, value in self.headers.items():
                kl = key.lower()
                if kl in ("host", "connection", "transfer-encoding"):
                    continue
                fwd_headers[key] = value
            fwd_headers["Host"] = UPSTREAM_HOST

            if request_body:
                fwd_headers["Content-Length"] = str(len(request_body))

            conn.request("POST", upstream_path, body=request_body, headers=fwd_headers)
            upstream_resp = conn.getresponse()

            status_code = upstream_resp.status

            resp_headers = []
            for key, value in upstream_resp.getheaders():
                kl = key.lower()
                if kl in ("transfer-encoding",):
                    continue
                resp_headers.append((key, value))

            cl = upstream_resp.getheader("Content-Length")
            if is_stream or (status_code == 200 and cl is None):
                resp_headers.append(("Content-Type", "text/event-stream"))
                self.send_response(status_code)
                for k, v in resp_headers:
                    if k.lower() != "content-length":
                        self.send_header(k, v)
                self.end_headers()

                while True:
                    chunk = upstream_resp.read(8192)
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    response_chunks.append(chunk)
                self.wfile.flush()
            else:
                response_body = upstream_resp.read()
                resp_headers.append(("Content-Length", str(len(response_body))))
                self.send_response(status_code)
                for k, v in resp_headers:
                    self.send_header(k, v)
                self.end_headers()
                self.wfile.write(response_body)

            conn.close()

        except Exception as e:
            log_error(f"upstream error: {e}")
            try:
                self.send_response(502)
                self.send_header("Content-Type", "text/plain")
                self.end_headers()
                self.wfile.write(f"Gateway Error: {e}".encode())
            except Exception:
                pass

        duration_ms = int(
            (datetime.now(timezone.utc) - start_time).total_seconds() * 1000
        )

        record = {
            "session_id": session_id,
            "ts": start_time.isoformat(),
            "endpoint": req_meta.get("endpoint", ""),
            "model": req_meta.get("model", ""),
            "messages_count": req_meta.get("messages_count", 0),
            "tools_count": req_meta.get("tools_count", 0),
            "stream": is_stream,
            "max_tokens": req_meta.get("max_tokens", 0),
            "status_code": status_code,
            "duration_ms": duration_ms,
        }

        if is_stream and response_chunks:
            sse_meta = parse_sse_events(response_chunks)
            record.update({
                "input_tokens": sse_meta.get("input_tokens", 0),
                "output_tokens": sse_meta.get("output_tokens", 0),
                "stop_reason": sse_meta.get("stop_reason", ""),
                "tool_calls": sse_meta.get("tool_calls", []),
            })
        elif response_body:
            nonstream_meta = parse_nonstream_body(response_body)
            record.update({
                "input_tokens": nonstream_meta.get("input_tokens", 0),
                "output_tokens": nonstream_meta.get("output_tokens", 0),
                "stop_reason": nonstream_meta.get("stop_reason", ""),
                "tool_calls": nonstream_meta.get("tool_calls", []),
            })

        if req_meta.get("tool_names"):
            record["request_tools"] = req_meta["tool_names"]

        _session_stats["calls"] += 1
        _session_stats["input_tokens"] += record.get("input_tokens", 0)
        _session_stats["output_tokens"] += record.get("output_tokens", 0)
        record["session_calls"] = _session_stats["calls"]
        record["session_input_total"] = _session_stats["input_tokens"]
        record["session_output_total"] = _session_stats["output_tokens"]

        model = record.get("model", "?")[:25]
        inp = record.get("input_tokens", 0)
        out = record.get("output_tokens", 0)
        dur = record.get("duration_ms", 0)
        sc = record.get("status_code", 0)
        sm = record.get("stop_reason", "")[:12]
        ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
        print(
            f"  [{ts}] #{_session_stats['calls']} {model}"
            f"  in:{inp} out:{out}  {dur}ms  {sc}"
            f"  [{_session_stats['input_tokens']}+{_session_stats['output_tokens']}={_session_stats['input_tokens']+_session_stats['output_tokens']}]"
            f"  {sm}"
        )

        write_record(record)

        try:
            STATUS_FILE.write_text(json.dumps({
                "last_call": record,
                "session": _session_stats,
            }, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass

    def log_message(self, format, *args):
        return


def main() -> None:
    port = 8899
    args = sys.argv[1:]
    for i, arg in enumerate(args):
        if arg == "--port" and i + 1 < len(args):
            port = int(args[i + 1])
        elif arg == "--upstream-host" and i + 1 < len(args):
            global UPSTREAM_HOST
            UPSTREAM_HOST = args[i + 1]
        elif arg == "--upstream-prefix" and i + 1 < len(args):
            global UPSTREAM_PATH_PREFIX
            UPSTREAM_PATH_PREFIX = args[i + 1]

    OBSERVATIONS_DIR.mkdir(parents=True, exist_ok=True)

    server = http.server.HTTPServer(("127.0.0.1", port), ProxyHandler)
    print(f"API Gateway Observer")
    print(f"  Listen: http://127.0.0.1:{port}")
    print(f"  Upstream: https://{UPSTREAM_HOST}{UPSTREAM_PATH_PREFIX}")
    print(f"  Logs: {API_CALLS_FILE}")
    print(f"  (Ctrl+C to stop)")
    print()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\\nShutting down.")
        server.shutdown()


if __name__ == "__main__":
    main()
'''

# ══════════════════════════════════════════════════════
# Hook 配置
# ══════════════════════════════════════════════════════

HOOKS_CONFIG = {
    "PreToolUse": [{
        "matcher": "Bash",
        "hooks": [{"type": "command", "command": "{py} ~/.claude/bin/observe.py pre"}]
    }],
    "PostToolUse": [{
        "matcher": ".*",
        "hooks": [{"type": "command", "command": "{py} ~/.claude/bin/observe.py post"}]
    }],
    "Stop": [{
        "hooks": [{"type": "command", "command": (
            "{py} ~/.claude/bin/observations_rotate.py && "
            "{py} ~/.claude/bin/auto-analyze-instincts.py && "
            "{py} ~/.claude/bin/auto-evolve.py"
        )}]
    }],
}

# ══════════════════════════════════════════════════════
# 安装器核心
# ══════════════════════════════════════════════════════

SCRIPTS = {
    "observe.py": OBSERVE_PY,
    "observations_rotate.py": OBSERVATIONS_ROTATE_PY,
    "auto-analyze-instincts.py": AUTO_ANALYZE_INSTINCTS_PY,
    "auto-evolve.py": AUTO_EVOLVE_PY,
    "api-gateway-observer.py": API_GATEWAY_OBSERVER_PY,
}

DIRS = [
    Path.home() / ".claude" / "bin",
    Path.home() / ".claude" / "observations",
    Path.home() / ".claude" / "homunculus" / "instincts" / "personal",
    Path.home() / ".claude" / "homunculus" / "evolved",
    Path.home() / ".claude" / "rules",
    Path.home() / ".claude" / "skills" / "migrate-self-evolution",
]


def detect_py() -> str:
    """检测 Python 命令。Windows 用 py，其他用 python3。"""
    if platform.system() == "Windows":
        return "py"
    return "python3"


def create_dirs(dry_run: bool = False) -> None:
    print("[*] 创建目录...")
    for d in DIRS:
        if dry_run:
            print(f"    [dry-run] mkdir -p {d}")
        else:
            d.mkdir(parents=True, exist_ok=True)
            print(f"    + {d}")


def write_scripts(dry_run: bool = False, force: bool = False) -> None:
    print("[*] 部署脚本...")
    bin_dir = Path.home() / ".claude" / "bin"
    for name, content in SCRIPTS.items():
        path = bin_dir / name
        exists = path.exists()
        if exists and not force:
            print(f"    - {path} (已存在，跳过)")
            continue

        if dry_run:
            label = "(覆盖)" if exists else "(新建)"
            print(f"    [dry-run] {label} {path}")
        else:
            path.write_text(content.lstrip("\\n"), encoding="utf-8")
            label = "(覆盖)" if exists else "(新建)"
            print(f"    + {label} {path}")


def write_skill(dry_run: bool = False, force: bool = False) -> None:
    print("[*] 部署 Skill...")
    skill_dir = Path.home() / ".claude" / "skills" / "migrate-self-evolution"

    # 写入 SKILL.md
    path_md = skill_dir / "SKILL.md"
    exists_md = path_md.exists()
    if not exists_md or force:
        if dry_run:
            label = "(覆盖)" if exists_md else "(新建)"
            print(f"    [dry-run] {label} {path_md}")
        else:
            path_md.write_text(SKILL_MD.lstrip("\\n"), encoding="utf-8")
            label = "(覆盖)" if exists_md else "(新建)"
            print(f"    + {label} {path_md}")
    else:
        print(f"    - {path_md} (已存在，跳过)")

    # 部署安装器自身
    path_installer = skill_dir / "install.py"
    exists_inst = path_installer.exists()
    if not exists_inst or force:
        if dry_run:
            label = "(覆盖)" if exists_inst else "(新建)"
            print(f"    [dry-run] {label} {path_installer}")
        else:
            try:
                self_src = Path(__file__).read_text(encoding="utf-8")
                path_installer.write_text(self_src, encoding="utf-8")
                label = "(覆盖)" if exists_inst else "(新建)"
                print(f"    + {label} {path_installer}")
            except Exception:
                print(f"    ! 无法读取自身源文件")
    else:
        print(f"    - {path_installer} (已存在，跳过)")


def merge_hooks(dry_run: bool = False, py: str = "python3") -> None:
    config = json.loads(
        json.dumps(HOOKS_CONFIG).replace("{py}", py)
    )

    settings_path = Path.home() / ".claude" / "settings.json"

    if dry_run:
        print(f"    [dry-run] merge hooks into {settings_path}")
        print(f"    [dry-run] hooks config: {json.dumps(config, indent=2)}")
        return

    if settings_path.exists():
        with open(settings_path, "r", encoding="utf-8") as f:
            settings = json.load(f)
    else:
        settings = {}

    if "hooks" not in settings:
        settings["hooks"] = {}

    for hook_name, hook_entries in config.items():
        existing = settings["hooks"].get(hook_name, [])
        existing_hooks = {json.dumps(e.get("hooks", []), sort_keys=True): e for e in existing}
        new_hooks = {json.dumps(e.get("hooks", []), sort_keys=True): e for e in hook_entries}
        existing_hooks.update(new_hooks)
        settings["hooks"][hook_name] = list(existing_hooks.values())

    with open(settings_path, "w", encoding="utf-8") as f:
        json.dump(settings, f, indent=2, ensure_ascii=False)

    print(f"    + hooks merged into {settings_path}")


def verify() -> bool:
    print("[*] 验证安装...")
    bin_dir = Path.home() / ".claude" / "bin"
    ok = True
    for name in SCRIPTS:
        path = bin_dir / name
        if path.exists():
            size = path.stat().st_size
            print(f"    OK  {path} ({size} bytes)")
        else:
            print(f"    MISS {path}")
            ok = False

    settings_path = Path.home() / ".claude" / "settings.json"
    if settings_path.exists():
        print(f"    OK  {settings_path}")
    else:
        print(f"    WARN {settings_path} 不存在（将在首次运行时创建）")

    skill_dir = Path.home() / ".claude" / "skills" / "migrate-self-evolution"
    for skill_file in ("SKILL.md", "install.py"):
        sp = skill_dir / skill_file
        if sp.exists():
            print(f"    OK  {sp} ({sp.stat().st_size} bytes)")
        else:
            print(f"    MISS {sp}")
            ok = False

    return ok


def main() -> None:
    dry_run = "--dry-run" in sys.argv
    force = "--force" in sys.argv
    py = detect_py()

    print(f"Claude Code 自进化系统安装器")
    print(f"  OS: {platform.system()}")
    print(f"  Python command: {py}")
    print(f"  Mode: {'dry-run' if dry_run else 'install'}")
    print()

    create_dirs(dry_run)
    print()
    write_scripts(dry_run, force)
    print()
    write_skill(dry_run, force)
    print()
    merge_hooks(dry_run, py)
    print()

    if not dry_run:
        if verify():
            print()
            print("=== 安装完成 ===")
            print()
            print("组件:")
            print("  Observation Engine  — Hook 触发，100% 工具调用捕获")
            print("  Instinct Engine     — 会话结束自动分析行为模式")
            print("  Rule Injection      — 高置信度规则自动注入下次会话")
            print()
            print(f"Hook 配置已写入 {Path.home() / '.claude' / 'settings.json'}")
            print("下次启动 Claude Code 时自动生效。")
        else:
            print()
            print("安装不完整，请检查上述 MISS 条目。")
            sys.exit(1)


if __name__ == "__main__":
    main()
