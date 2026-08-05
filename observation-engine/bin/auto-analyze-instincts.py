#!/usr/bin/env python3
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

# ── 路径 ──────────────────────────────────────────────

OBSERVATIONS_FILE = Path.home() / ".claude" / "observations" / "observations.jsonl"
INSTINCTS_DIR = Path.home() / ".claude" / "homunculus" / "instincts" / "personal"
ERROR_LOG = Path.home() / ".claude" / "observations" / "errors.log"

# ── 日志 ──────────────────────────────────────────────

def log_error(msg: str) -> None:
    try:
        ts = datetime.now(timezone.utc).isoformat()
        with open(ERROR_LOG, "a", encoding="utf-8") as f:
            f.write(f"[{ts}] [instinct] {msg}\n")
    except Exception:
        pass

# ── 观测数据加载 ──────────────────────────────────────

def load_observations() -> list[dict]:
    """读取 observations.jsonl，返回所有记录。"""
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
    """按 session_id 分组，组内按 ts 排序，扩展统计字段。"""
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

# ── 置信度管理 ────────────────────────────────────────

def load_existing_instincts() -> dict[str, dict]:
    """读取已有的 instinct .md 文件，返回 {id: {metadata}}。"""
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
    """更新置信度。首次 0.5，检测 +0.05（上限 0.9），未检测 -0.05。"""
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
            return {}  # 首次未检测，跳过

    return {
        "confidence": round(confidence, 2),
        "deprecated": deprecated,
    }

# ── Frontmatter 解析 ──────────────────────────────────

def parse_frontmatter(content: str) -> tuple[dict, str]:
    """解析 YAML frontmatter（--- 分隔），纯 stdlib。"""
    lines = content.split("\n")
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
        m = re.match(r'^(\w[\w_-]*)\s*:\s*(.+)$', line)
        if m:
            key = m.group(1)
            val = m.group(2).strip().strip('"').strip("'")
            if val in ("true", "false"):
                val = val == "true"
            elif re.match(r'^-?\d+\.\d+$', val):
                val = float(val)
            elif re.match(r'^-?\d+$', val):
                val = int(val)
            metadata[key] = val

    body = "\n".join(lines[end_idx + 1:])
    return metadata, body

# ── Instinct 写入 ─────────────────────────────────────

def write_instinct(instinct: dict) -> None:
    """将一条 instinct 写入 .md 文件。"""
    INSTINCTS_DIR.mkdir(parents=True, exist_ok=True)
    fid = instinct.get("id", str(uuid.uuid4().hex[:8]))
    file_path = INSTINCTS_DIR / f"{fid}.md"

    now = datetime.now(timezone.utc).isoformat()
    confidence = instinct.get("confidence", 0.5)
    deprecated = instinct.get("deprecated", False)

    frontmatter = (
        f"---\n"
        f"id: {fid}\n"
        f'trigger: "{instinct.get("trigger", "")}"\n'
        f'action: "{instinct.get("action", "")}"\n'
        f"confidence: {confidence}\n"
        f"domain: {instinct.get("domain", "general")}\n"
        f"source: {instinct.get("source", "statistical-detection")}\n"
        f"deprecated: {str(deprecated).lower()}\n"
        f'observed_at: "{now}"\n'
        f"---\n"
    )

    body = (
        f"# {instinct.get('name', fid)}\n\n"
        f"**Trigger:** {instinct.get('trigger', '')}\n\n"
        f"**Action:** {instinct.get('action', '')}\n\n"
        f"**Confidence:** {confidence:.2f}\n\n"
        f"**Domain:** {instinct.get('domain', 'general')}\n\n"
        f"**Evidence:**\n{instinct.get('body', '')}\n"
    )

    try:
        file_path.write_text(frontmatter + body, encoding="utf-8")
    except Exception as e:
        log_error(f"write_instinct error: {e}")

# ══════════════════════════════════════════════════════
# 路径 A：5 个统计检测器
# ══════════════════════════════════════════════════════

def detect_pattern_1(sessions: list[dict], existing: dict) -> list[dict]:
    """Read-before-Edit: Edit 之前有 Read 同一文件。"""
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
            # 检查之前是否有 Read 同一文件
            has_read = any(
                rec.get("tool") == "Read" and rec.get("input", {}).get("file_path") == fp
                for rec in records[:i]
            )
            if not has_read:
                triggered = True
                evidence_lines.append(
                    f"  - session {s['session_id'][:8]}: Edit {fp} without prior Read"
                )

    meta = existing.get("read-before-edit")
    cupd = update_confidence(meta, triggered)
    if not cupd:
        return []

    instinct = {
        "id": "read-before-edit",
        "name": "Read-before-Edit Pattern",
        "trigger": "When about to edit a file that hasn't been read in this session",
        "action": "Read the file first to understand its current state before editing",
        "body": "Across sessions, editing files without reading them first was observed. This can lead to overwriting recent changes or editing stale content.\n\nEvidence:\n" + "\n".join(evidence_lines[-5:]) if evidence_lines else "Pattern matched.",
        "domain": "workflow",
        **cupd,
    }
    return [instinct]


def detect_pattern_2(sessions: list[dict], existing: dict) -> list[dict]:
    """Search-before-Edit: Edit 之前有 Grep/Glob。"""
    triggered = False
    evidence_lines = []
    for s in sessions:
        records = s["records"]
        for i, r in enumerate(records):
            if r.get("tool") != "Edit" or r.get("phase") != "post":
                continue
            has_search = any(
                rec.get("tool") in ("Grep", "Glob")
                for rec in records[:i]
            )
            if not has_search:
                triggered = True
                evidence_lines.append(
                    f"  - session {s['session_id'][:8]}: no search before Edit"
                )

    meta = existing.get("search-before-edit")
    cupd = update_confidence(meta, triggered)
    if not cupd:
        return []

    instinct = {
        "id": "search-before-edit",
        "name": "Search-before-Edit Pattern",
        "trigger": "When about to edit without first searching/grepping for the relevant code",
        "action": "Use Grep or Glob to locate all relevant locations before editing",
        "body": "Occasionally editing files without searching for all relevant code locations was observed. Searching first helps find all related occurrences.\n\nEvidence:\n" + "\n".join(evidence_lines[-5:]),
        "domain": "workflow",
        **cupd,
    }
    return [instinct]


def detect_pattern_3(sessions: list[dict], existing: dict) -> list[dict]:
    """Bash-followed-by-other: Bash 输出被下个工具消费。"""
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
            # 检查下个工具的 input 是否包含 Bash 输出中的关键词
            out_words = set(re.findall(r'[a-zA-Z]{4,}', output.lower()))
            in_words = set(re.findall(r'[a-zA-Z]{4,}', next_input.lower()))
            overlap = out_words & in_words
            if len(overlap) >= 2:
                triggered = True
                evidence_lines.append(
                    f"  - session {s['session_id'][:8]}: Bash→{next_rec.get('tool')}, overlap: {overlap}"
                )

    meta = existing.get("bash-consumed-by-next")
    cupd = update_confidence(meta, triggered)
    if not cupd:
        return []

    instinct = {
        "id": "bash-consumed-by-next",
        "name": "Bash Output Consumed by Next Tool",
        "trigger": "After running a Bash command whose output influences the next tool's input",
        "action": "Parse the Bash output carefully before passing to the next tool; consider storing in variables",
        "body": "Bash command outputs frequently feed into subsequent tool calls. This indicates a tight feedback loop between shell and code operations.\n\nEvidence:\n" + "\n".join(evidence_lines[-5:]),
        "domain": "toolchain",
        **cupd,
    }
    return [instinct]


def detect_pattern_4(sessions: list[dict], existing: dict) -> list[dict]:
    """Edit-sequence: 连续 Edit/Write 迭代模式。"""
    triggered = False
    evidence_lines = []
    for s in sessions:
        seq = s["tool_sequence"]
        # 检查连续 >=3 个 Edit/Write
        edit_writes = [t for t in seq if t in ("Edit", "Write")]
        if len(edit_writes) >= 3:
            triggered = True
            evidence_lines.append(
                f"  - session {s['session_id'][:8]}: {len(edit_writes)} Edit/Write operations"
            )

    meta = existing.get("edit-iteration-cycle")
    cupd = update_confidence(meta, triggered)
    if not cupd:
        return []

    instinct = {
        "id": "edit-iteration-cycle",
        "name": "Iterative Edit Cycle",
        "trigger": "When multiple consecutive edits or writes occur to the same area",
        "action": "Consider batching smaller changes into fewer larger edits, or verifying each edit's result before the next",
        "body": "Sessions with many consecutive edit/write operations indicate an iterative refinement pattern. This is efficient but benefits from verification between iterations.\n\nEvidence:\n" + "\n".join(evidence_lines[-5:]),
        "domain": "efficiency",
        **cupd,
    }
    return [instinct]


def detect_pattern_5(sessions: list[dict], existing: dict) -> list[dict]:
    """Commit-pattern: Edit/Write → git commit。"""
    triggered = False
    evidence_lines = []
    for s in sessions:
        records = s["records"]
        for i, r in enumerate(records):
            if r.get("tool") != "Bash" or r.get("phase") != "post":
                continue
            cmd = r.get("input", {}).get("command", "")
            if not re.search(r'git\s+commit', cmd):
                continue
            # 检查之前的 Edit/Write
            has_edit = any(
                rec.get("tool") in ("Edit", "Write")
                for rec in records[:i]
            )
            if has_edit:
                triggered = True
                evidence_lines.append(
                    f"  - session {s['session_id'][:8]}: edits followed by git commit"
                )

    meta = existing.get("commit-after-edit")
    cupd = update_confidence(meta, triggered)
    if not cupd:
        return []

    instinct = {
        "id": "commit-after-edit",
        "name": "Commit-after-Edit Pattern",
        "trigger": "After code changes are made, before git committing",
        "action": "Review all changes qualitatively (not just git diff), ensure tests pass, then commit with a meaningful message",
        "body": "Code edits followed by git commits is a common workflow that ensures changes are tracked properly.\n\nEvidence:\n" + "\n".join(evidence_lines[-5:]),
        "domain": "workflow",
        **cupd,
    }
    return [instinct]

# ══════════════════════════════════════════════════════
# 路径 B：AI 语义分析
# ══════════════════════════════════════════════════════

def run_ai_analysis(records: list[dict]) -> list[dict]:
    """调用 Claude CLI 进行语义分析。失败静默返回 []。"""
    try:
        # 取最近 200 条记录
        recent = records[-200:]
        summary_lines = []
        for r in recent:
            tool = r.get("tool", "")
            phase = r.get("phase", "")
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
            summary_lines.append(f"- [{phase}] {tool}: {detail}")

        summary = "\n".join(summary_lines)
        # 截断防止提示过长
        MAX_CHARS = 5000
        if len(summary) > MAX_CHARS:
            summary = summary[:MAX_CHARS] + "\n... [truncated]"

        prompt = (
            "Analyze the following Claude Code tool call observations. "
            "Identify behavioral patterns, workflows, or heuristics that can be extracted as reusable rules. "
            "Return ONLY a valid JSON array of instinct objects. "
            "Each instinct must have: id (kebab-case), name, trigger (when condition), "
            "action (recommended behavior), body (2-3 sentences explanation), "
            f"domain (one of: workflow/toolchain/efficiency/code-quality/convention). "
            "If no clear patterns, return []."
            "\n\nObservations:\n" + summary
        )

        result = subprocess.run(
            ["claude", "--print", "--output-format", "json", "-p", prompt],
            capture_output=True, text=True, timeout=60,
            env={**os.environ, "CLAUDE_CODE_SIMPLE": "1"},
        )
        if result.returncode != 0:
            log_error(f"AI analysis CLI error (rc={result.returncode}): {result.stderr[:200]}")
            return []

        # 解析 claude --print --output-format json 的返回
        try:
            data = json.loads(result.stdout)
        except json.JSONDecodeError:
            return []

        answer = ""
        if isinstance(data, dict):
            # 尝试常见的返回格式
            answer = data.get("result") or data.get("text") or data.get("response") or data.get("output", "")
        if not answer and isinstance(data, str):
            answer = data
        if not answer:
            return []

        # answer 本身可能是 JSON 字符串
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

        # 为每个 instinct 补充 source 字段
        for inst in instincts:
            if not isinstance(inst, dict):
                continue
            inst["source"] = "ai-semantic"

        return [inst for inst in instincts if isinstance(inst, dict) and inst.get("id")]

    except FileNotFoundError:
        return []
    except subprocess.TimeoutExpired:
        log_error("AI analysis timed out")
        return []
    except Exception as e:
        log_error(f"AI analysis error: {e}")
        return []

# ══════════════════════════════════════════════════════
# Main
# ══════════════════════════════════════════════════════

def main() -> None:
    try:
        records = load_observations()
        if not records:
            return

        sessions = group_by_session(records)
        existing = load_existing_instincts()

        # 路径 A
        detectors = [
            detect_pattern_1,
            detect_pattern_2,
            detect_pattern_3,
            detect_pattern_4,
            detect_pattern_5,
        ]
        from_path_a = []
        for detect in detectors:
            from_path_a.extend(detect(sessions, existing))

        # 路径 B
        from_path_b = run_ai_analysis(records)

        # 合并：路径 B 覆盖路径 A 的相同 id
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
