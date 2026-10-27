#!/usr/bin/env python3
"""Eval → TencentDB 导出流水线。

将测评通过的 session 导出为 TencentDB Agent Memory 格式的资产:
  - Chat Memory L0: 原始会话 (工具调用摘要)
  - Chat Memory L1: Atom 事实/约束/决策
  - Chat Memory L2: 场景摘要
  - Skill: 高分 session 的可复用工具序列 (score >= 90)

用法:
  python eval_tdbank_export.py --report report-xxx.json     # 从报告导出
  python eval_tdbank_export.py --latest                     # 最新 session
  python eval_tdbank_export.py --session <session_id>       # 指定 session
  python eval_tdbank_export.py --offline                    # 强制离线模式
"""

import json
import os
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from eval_tdbank_config import TdbankConfig
from tdbank_client import TdbankFacade

OBSERVATIONS_FILE = Path.home() / ".claude" / "observations" / "observations.jsonl"
EVAL_RESULTS_DIR = SCRIPT_DIR.parent / "eval_results"

# ── L0: 原始会话提取 ───────────────────────────────

def _build_l0(session_id: str, observations: list[dict]) -> dict:
    """从 observations 构建 L0 原始会话记忆。"""
    messages = []
    for rec in observations:
        sid = rec.get("session_id", "")
        if sid and sid != session_id:
            continue

        tool_call = rec.get("tool_call", {})
        tool_result = rec.get("tool_result", {})

        if tool_call:
            name = tool_call.get("name", "unknown")
            params = tool_call.get("params", {})
            # 摘要化参数
            summary = _summarize_params(name, params)
            messages.append({
                "role": "tool_call",
                "tool": name,
                "summary": summary,
                "ts": rec.get("timestamp", ""),
            })

        if tool_result:
            output = tool_result.get("output", "")
            messages.append({
                "role": "tool_result",
                "tool": tool_result.get("name", "unknown"),
                "output_summary": output[:200] if isinstance(output, str) else str(output)[:200],
                "ts": rec.get("timestamp", ""),
            })

    return {
        "asset_type": "chat_memory.L0",
        "source": "observation-engine",
        "session_id": session_id,
        "record_count": len(messages),
        "messages": messages,
    }


def _summarize_params(tool_name: str, params: dict) -> str:
    """将工具参数摘要为可读描述。"""
    if tool_name == "Read":
        fp = params.get("file_path", "")
        return f"Read file: {Path(fp).name if fp else '?'}"
    elif tool_name == "Write":
        fp = params.get("file_path", "")
        return f"Write file: {Path(fp).name if fp else '?'}"
    elif tool_name == "Edit":
        return f"Edit file: {_extract_file_from_edit(params)}"
    elif tool_name == "Bash":
        cmd = params.get("command", "")
        return f"Run: {cmd.split()[0] if cmd else '?'}"
    elif tool_name in ("Grep", "Glob"):
        return f"Search: {params.get('pattern', '')[:80]}"
    else:
        return f"{tool_name}: {str(params)[:100]}"


def _extract_file_from_edit(params: dict) -> str:
    fp = params.get("file_path", "")
    if fp:
        return Path(fp).name
    old = params.get("old_string", "")
    if old and len(old) < 80:
        return old.strip()[:40]
    return "?"


# ── L1: Atom 提取 ──────────────────────────────────

def _build_l1(session_id: str, observations: list[dict]) -> dict:
    """从 observations 提取 L1 Atom（事实/约束/决策）。"""
    atoms = []
    seen_files = set()
    seen_commands = set()

    for rec in observations:
        sid = rec.get("session_id", "")
        if sid and sid != session_id:
            continue

        tc = rec.get("tool_call", {})
        tr = rec.get("tool_result", {})

        # 事实: 文件读取
        if tc.get("name") in ("Read", "Write", "Edit"):
            fp = tc.get("params", {}).get("file_path", "")
            if fp and fp not in seen_files:
                seen_files.add(fp)
                atoms.append({
                    "type": "fact",
                    "category": "file_access",
                    "content": f"Accessed file: {fp}",
                    "evidence": [{"tool": tc["name"], "file": fp, "ts": rec.get("timestamp", "")}],
                    "confidence": 0.95,
                })

        # 事实: 搜索模式
        if tc.get("name") in ("Grep", "Glob"):
            pattern = tc.get("params", {}).get("pattern", "")
            if pattern:
                atoms.append({
                    "type": "fact",
                    "category": "search",
                    "content": f"Searched for pattern: {pattern[:100]}",
                    "evidence": [{"tool": tc["name"], "pattern": pattern[:100], "ts": rec.get("timestamp", "")}],
                    "confidence": 0.85,
                })

        # 决策: Bash 命令
        if tc.get("name") == "Bash":
            cmd = tc.get("params", {}).get("command", "")
            cmd_word = cmd.split()[0] if cmd else "?"
            if cmd_word not in seen_commands:
                seen_commands.add(cmd_word)
                atoms.append({
                    "type": "decision",
                    "category": "command",
                    "content": f"Executed command: {cmd[:200]}",
                    "evidence": [{"tool": "Bash", "command_word": cmd_word, "ts": rec.get("timestamp", "")}],
                    "confidence": 0.90,
                })

        # 错误检测: 约束
        if tr and tr.get("success") is False:
            atoms.append({
                "type": "constraint",
                "category": "error",
                "content": f"Tool call failed: {tc.get('name', '?')} — {str(tr.get('output', ''))[:200]}",
                "evidence": [{"tool": tc.get("name", "?"), "ts": rec.get("timestamp", "")}],
                "confidence": 0.95,
            })

    return {
        "asset_type": "chat_memory.L1",
        "source": "observation-engine",
        "session_id": session_id,
        "atom_count": len(atoms),
        "atoms": atoms,
    }


# ── L2: 场景摘要 ───────────────────────────────────

def _build_l2(session_id: str, observations: list[dict],
              eval_result: dict | None = None) -> dict:
    """从工具链分析推断场景摘要。"""
    # 统计工具分布
    tool_counts = defaultdict(int)
    for rec in observations:
        sid = rec.get("session_id", "")
        if sid and sid != session_id:
            continue
        tc = rec.get("tool_call", {})
        if tc:
            tool_counts[tc.get("name", "unknown")] += 1

    # 推断场景
    scenario = _infer_scenario(tool_counts)

    # 聚合评分信息
    score_info = {}
    if eval_result:
        score_info = {
            "eval_score": eval_result.get("case_score", 0),
            "pass_rate": eval_result.get("summary", {}).get("pass_rate", "N/A"),
            "trials": eval_result.get("summary", {}).get("total_cases", 0),
        }

    return {
        "asset_type": "chat_memory.L2",
        "source": "observation-engine",
        "session_id": session_id,
        "scenario": scenario,
        "tool_distribution": dict(tool_counts),
        "eval_summary": score_info,
    }


def _infer_scenario(tool_counts: dict) -> str:
    """根据工具使用模式推断场景类型。"""
    has_read = tool_counts.get("Read", 0) > 0
    has_write = tool_counts.get("Write", 0) > 0
    has_edit = tool_counts.get("Edit", 0) > 0
    has_bash = tool_counts.get("Bash", 0) > 0
    has_grep = tool_counts.get("Grep", 0) > 0
    total = sum(tool_counts.values())

    if has_write or has_edit:
        if has_bash:
            return "code-implementation"
        return "document-editing"
    elif has_read and has_grep and total >= 5:
        return "codebase-exploration"
    elif has_bash and total <= 3:
        return "quick-operation"
    elif has_grep:
        return "code-search"
    else:
        return "general-task"


# ── Skill 提取 ─────────────────────────────────────

def _build_skill(session_id: str, observations: list[dict],
                 score: int) -> dict | None:
    """从高分 session 提取可复用 Skill。"""
    if score < 90:
        return None

    # 提取工具调用序列
    steps = []
    for rec in observations:
        sid = rec.get("session_id", "")
        if sid and sid != session_id:
            continue
        tc = rec.get("tool_call", {})
        if tc:
            name = tc.get("name", "unknown")
            params = tc.get("params", {})
            steps.append({
                "tool": name,
                "params": _summarize_params(name, params),
                "purpose": _infer_purpose(name, params),
            })

    if len(steps) < 2:
        return None

    # 推断 Skill 名称和边界
    tool_names = list(set(s["tool"] for s in steps))
    skill_name = f"{_infer_scenario(dict((t, 1) for t in tool_names))}-skill"

    return {
        "name": skill_name,
        "description": f"Auto-extracted skill from session {session_id} (score: {score})",
        "boundaries": {
            "preconditions": ["Claude CLI available", "Project directory exists"],
            "postconditions": [f"Completed {len(steps)} tool calls"],
        },
        "steps": steps,
        "validation": {
            "checks": [f"At least {len(steps) // 2} tool calls succeeded"],
            "anti_patterns": ["Editing before reading"],
        },
        "metadata": {
            "source_session": session_id,
            "eval_score": score,
            "extracted_at": datetime.now(timezone.utc).isoformat(),
            "tool_count": len(steps),
        },
    }


def _infer_purpose(tool_name: str, params: dict) -> str:
    """推断单个工具调用步骤的目的。"""
    if tool_name == "Read":
        return "Understand current state of the file"
    elif tool_name == "Write":
        fp = params.get("file_path", "")
        return f"Create new file: {Path(fp).name if fp else '?'}"
    elif tool_name == "Edit":
        return "Modify existing code"
    elif tool_name == "Bash":
        cmd = params.get("command", "")
        if "git" in cmd:
            return "Version control operation"
        if "test" in cmd or "pytest" in cmd:
            return "Run tests"
        return f"Execute: {cmd.split()[0] if cmd else '?'}"
    elif tool_name == "Grep":
        return "Search codebase for pattern"
    elif tool_name == "Glob":
        return "Discover files by pattern"
    return "Perform operation"


# ── 主导出流程 ─────────────────────────────────────

def export_session(report: dict, session_id: str = "",
                   config: dict | None = None) -> dict | None:
    """主导出流水线：测评报告 → TencentDB 记忆资产。

    返回导出摘要或 None（质量门禁未通过时）。
    """
    if config is None:
        cfg = TdbankConfig()
        config = cfg.load()

    # Step 1: 提取 session_id
    if not session_id:
        session_id = report.get("session_id", "")

    if not session_id:
        print("[tdbank] No session_id found, skipping")
        return None

    # Step 2: 质量门禁
    threshold = config.get("quality_threshold", 80)
    summary = report.get("summary", {})
    pass_rate_str = summary.get("pass_rate", "0%")
    try:
        pass_rate = float(pass_rate_str.rstrip("%"))
    except (ValueError, AttributeError):
        pass_rate = 0

    if pass_rate < threshold:
        print(f"[tdbank] Pass rate {pass_rate}% < {threshold}%, skipping")
        return None

    # Step 3: 加载 observations
    observations = _load_session_observations(session_id)
    if not observations:
        print(f"[tdbank] No observations for session {session_id}")
        return None

    print(f"[tdbank] Exporting session {session_id} "
          f"(pass_rate={pass_rate}%, {len(observations)} records)")

    # Step 4-7: 构建资产
    l0 = _build_l0(session_id, observations)
    l1 = _build_l1(session_id, observations)
    l2 = _build_l2(session_id, observations, report)

    # Step 8: Skill (仅高分)
    best_score = _best_case_score(report)
    skill = _build_skill(session_id, observations, best_score)

    assets = {"L0": l0, "L1": l1, "L2": l2}
    if skill:
        assets["skill"] = skill
        print(f"[tdbank] Extracted skill: {skill['name']}")

    # Step 9: 写本地 + 推送 API
    facade = TdbankFacade(config)
    results = {}

    for layer, data in assets.items():
        if layer == "skill":
            aid = facade.push_skill(data)
        else:
            aid = facade.push_chat_memory(layer, data)
        results[layer] = aid or "offline"

    # 汇总
    export_summary = {
        "session_id": session_id,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "pass_rate": pass_rate,
        "best_score": best_score,
        "assets_exported": results,
        "records_processed": len(observations),
        "skill_extracted": skill is not None,
    }

    print(f"[tdbank] Export complete: {json.dumps(export_summary, indent=2)}")
    return export_summary


def _load_session_observations(session_id: str) -> list[dict]:
    """从 observations.jsonl 加载指定 session 的记录。"""
    if not OBSERVATIONS_FILE.exists():
        return []

    records = []
    try:
        with open(OBSERVATIONS_FILE, "r", encoding="utf-8") as f:
            for line in f:
                try:
                    rec = json.loads(line.strip())
                    if rec.get("session_id") == session_id:
                        records.append(rec)
                except json.JSONDecodeError:
                    continue
    except IOError:
        pass

    return records


def _best_case_score(report: dict) -> int:
    """获取 report 中的最高 case 分数。"""
    cases = report.get("cases", [])
    if not cases:
        return 0
    return max(c.get("case_score", 0) for c in cases)


def _find_latest_report() -> Path | None:
    """找到最新的 JSON 测评报告。"""
    json_files = sorted(EVAL_RESULTS_DIR.rglob("report-*.json"), reverse=True)
    for f in json_files:
        if "baseline" not in str(f):
            return f
    return None


# ── CLI ────────────────────────────────────────────

def main():
    import argparse
    parser = argparse.ArgumentParser(
        description="Eval → TencentDB 导出流水线")
    parser.add_argument("--report", type=str, help="测评报告 JSON 路径")
    parser.add_argument("--session", type=str, help="指定 session_id")
    parser.add_argument("--latest", action="store_true", help="导出最新 session")
    parser.add_argument("--offline", action="store_true", help="强制离线模式")
    args = parser.parse_args()

    cfg = TdbankConfig()
    config = cfg.load()

    if args.offline:
        config["offline_mode"] = True
        config["enabled"] = False

    # 加载报告
    report = None
    if args.report:
        rp = Path(args.report)
        if rp.exists():
            report = json.loads(rp.read_text(encoding="utf-8"))
    elif args.session:
        report = {"session_id": args.session,
                  "summary": {"pass_rate": "100%"},
                  "cases": [{"case_score": 100}]}
    elif args.latest:
        rp = _find_latest_report()
        if rp:
            print(f"[tdbank] Loading: {rp}")
            report = json.loads(rp.read_text(encoding="utf-8"))
        else:
            print("[tdbank] No reports found")
            return

    if not report:
        print("[tdbank] No report/session specified, use --report, --session, or --latest")
        return

    session_id = args.session or report.get("session_id", "")
    result = export_session(report, session_id, config)

    if result:
        offline = Path(config["export_dir"])
        print(f"\n[tdbank] Local exports -> {offline}")
        print(f"[tdbank] To push to TencentDB: set TDBANK_ENABLED=true and TDBANK_BASE_URL")


if __name__ == "__main__":
    main()
