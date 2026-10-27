#!/usr/bin/env python3
"""Eval Graders -- 确定性评分器，纯 Python stdlib。

三类评分器:
  StepGrader     -- LCS 步骤对齐，检查工具调用序列
  EfficiencyGrader -- Token / 耗时 / 工具调用次数
  ResultGrader   -- 产物文件 / 响应内容 / 工具调用断言
"""

import json
import re
from collections import Counter
from pathlib import Path
from typing import Any


# ======================================================
# 工具函数
# ======================================================

def longest_common_subsequence(seq_a: list[str], seq_b: list[str]) -> int:
    """返回 LCS 长度（DP 实现）。"""
    if not seq_a or not seq_b:
        return 0
    m, n = len(seq_a), len(seq_b)
    dp = [[0] * (n + 1) for _ in range(2)]
    for i in range(1, m + 1):
        cur, prev = i % 2, (i - 1) % 2
        for j in range(1, n + 1):
            if seq_a[i - 1] == seq_b[j - 1]:
                dp[cur][j] = dp[prev][j - 1] + 1
            else:
                dp[cur][j] = max(dp[prev][j], dp[cur][j - 1])
    return dp[m % 2][n]


def normalize_step(tool_name: str, tool_input: dict) -> str:
    """归一化工具调用为可比较的字符串签名。

    类似腾讯方案的归一化: 时间戳 -> 占位符, 搜索工具忽略查询参数,
    写入工具只保留路径, 终端命令提取脚本名。
    """
    name = tool_name.strip()

    if not isinstance(tool_input, dict):
        return name

    if name in ("Read", "read_file"):
        fp = tool_input.get("file_path", tool_input.get("path", ""))
        return f"Read:{fp}"

    if name in ("Write", "write_file"):
        fp = tool_input.get("file_path", tool_input.get("path", ""))
        return f"Write:{fp}"

    if name in ("Edit", "edit_file"):
        fp = tool_input.get("file_path", tool_input.get("path", ""))
        return f"Edit:{fp}"

    if name in ("Grep", "grep_search"):
        pattern = tool_input.get("pattern", "")
        return f"Grep:{pattern[:80]}"

    if name in ("Glob", "glob_search"):
        pattern = tool_input.get("pattern", "")
        return f"Glob:{pattern[:80]}"

    if name in ("Bash", "bash", "PowerShell"):
        cmd = tool_input.get("command", "")[:100]
        # 提取关键命令名
        cmd_name = cmd.strip().split()[0] if cmd.strip() else "?"
        return f"Bash:{cmd_name}"

    if name in ("mcp__",):
        return f"MCP:{name}"

    # 泛化: 提取 tool name 中有意义的部分
    short = name.split("__")[-1] if "__" in name else name
    return short[:80]


def extract_tool_sequence(trace_records: list[dict]) -> list[dict]:
    """从 observation-engine JSONL 记录中提取工具调用序列。

    返回: [{"tool": "Read", "input": {...}, "normalized": "Read:foo.txt", "ts": "..."}, ...]
    """
    steps = []
    for r in trace_records:
        if r.get("phase") != "pre":
            continue
        tool = r.get("tool", "")
        inp = r.get("input", {})
        steps.append({
            "tool": tool,
            "input": inp,
            "normalized": normalize_step(tool, inp),
            "ts": r.get("ts", ""),
        })
    return steps


# ======================================================
# StepGrader -- LCS 步骤对齐评分
# ======================================================

class StepGrader:
    """使用 LCS 对齐基线与 Trial 的操作步骤序列。

    扣分规则（每项 -2 分，上限 -10）:
      - 步骤不一致 / 多余 / 缺少 / 顺序错误
    """

    MAX_DEDUCTION = 10
    PER_ISSUE = 2

    def grade(self, baseline_steps: list[str],
              trial_steps: list[str]) -> dict:
        """比较两个归一化步骤序列。"""
        n_base, n_trial = len(baseline_steps), len(trial_steps)
        lcs_len = longest_common_subsequence(baseline_steps, trial_steps)

        issues = []
        deduction = 0

        # 多余步骤 (trial 有但不在 LCS 中的)
        extra = n_trial - lcs_len
        if extra > 0:
            deduction += min(extra, 3) * self.PER_ISSUE
            issues.append(f"extra_steps: +{extra}")

        # 缺少步骤 (baseline 有但不在 LCS 中的)
        missing = n_base - lcs_len
        if missing > 0:
            deduction += min(missing, 3) * self.PER_ISSUE
            issues.append(f"missing_steps: -{missing}")

        # 顺序错误 -- LCS 中元素的相对顺序
        if lcs_len > 0 and n_base > 0 and n_trial > 0:
            mismatch = self._count_order_mismatches(baseline_steps, trial_steps)
            if mismatch > 0:
                ded = min(mismatch, 2) * self.PER_ISSUE
                deduction += ded
                issues.append(f"order_mismatches: {mismatch}")

        deduction = min(deduction, self.MAX_DEDUCTION)
        score = max(0, self.MAX_DEDUCTION - deduction)

        return {
            "grader": "StepGrader",
            "score": score,
            "max_score": self.MAX_DEDUCTION,
            "deduction": deduction,
            "baseline_steps": n_base,
            "trial_steps": n_trial,
            "lcs_length": lcs_len,
            "issues": issues,
        }

    def _count_order_mismatches(self, baseline: list[str],
                                 trial: list[str]) -> int:
        """统计两个序列中共有元素的相对顺序差异。"""
        # 对 baseline 中每个元素在 trial 中的位置索引
        tri_pos = {v: i for i, v in enumerate(trial)}
        order = []
        for v in baseline:
            if v in tri_pos:
                order.append(tri_pos[v])
        # 计算逆序对
        inversions = 0
        for i in range(len(order)):
            for j in range(i + 1, len(order)):
                if order[i] > order[j]:
                    inversions += 1
        return inversions


# ======================================================
# EfficiencyGrader -- 效率评分
# ======================================================

class EfficiencyGrader:
    """耗时/Token/工具调用次数 对比评分。

    扣分规则（两项合计上限 -10）:
      - 耗时以基线为基准，每超标 10% 扣 1 分
      - Token 以基线为基准，每超标 10% 扣 1 分
    """

    MAX_DEDUCTION = 10

    def grade(self, baseline: dict, trial: dict) -> dict:
        """
        baseline / trial:
          {"elapsed_s": 120, "token_count": 5000, "tool_calls": 8}
        """
        issues = []
        deduction = 0

        # 耗时对比
        base_t = baseline.get("elapsed_s", 0)
        tri_t = trial.get("elapsed_s", 0)
        if base_t > 0 and tri_t > base_t:
            excess = (tri_t - base_t) / base_t
            ded = min(int(excess * 10), 5)
            if ded > 0:
                deduction += ded
                issues.append(f"time_excess: {excess:.0%} (+{tri_t - base_t:.0f}s)")

        # Token 对比
        base_tok = baseline.get("token_count", 0)
        tri_tok = trial.get("token_count", 0)
        if base_tok > 0 and tri_tok > base_tok:
            excess = (tri_tok - base_tok) / base_tok
            ded = min(int(excess * 10), 5)
            if ded > 0:
                deduction += ded
                issues.append(f"token_excess: {excess:.0%} (+{tri_tok - base_tok})")

        # 工具调用次数
        base_calls = baseline.get("tool_calls", 0)
        tri_calls = trial.get("tool_calls", 0)
        if base_calls > 0 and tri_calls > base_calls * 1.5:
            deduction += 2
            issues.append(f"tool_call_excess: {tri_calls} vs baseline {base_calls}")

        deduction = min(deduction, self.MAX_DEDUCTION)
        score = max(0, self.MAX_DEDUCTION - deduction)

        return {
            "grader": "EfficiencyGrader",
            "score": score,
            "max_score": self.MAX_DEDUCTION,
            "deduction": deduction,
            "baseline": baseline,
            "trial": trial,
            "issues": issues,
        }


# ======================================================
# ResultGrader -- 产物 / 响应内容 / 工具调用断言
# ======================================================

class ResultGrader:
    """确定性规则检查器。

    支持规则:
      - file_exists: [path, ...]
      - response_contains: [keyword, ...]
      - response_not_contains: [keyword, ...]
      - tool_call: [{"name": "...", "contains": "..."}]
      - max_tool_calls: N
      - file_content_contains: {"path": "...", "keyword": "..."}
    """

    MAX_DEDUCTION = 40  # 结果层面扣分上限

    def grade(self, expected: dict, trial_output: dict) -> dict:
        """
        expected: 用例定义的 expected_behavior
        trial_output:
          {"response": "...", "files_created": ["path", ...],
           "trace_records": [...], "tool_calls": N,
           "file_contents": {"path": "content"}}
        """
        issues = []
        checks_passed = 0
        checks_total = 0

        # file_exists
        for fp in expected.get("file_exists", []):
            checks_total += 1
            files_list = trial_output.get("files_created", [])
            if any(fp in f for f in files_list):
                checks_passed += 1
            else:
                issues.append(f"file_missing: {fp}")

        # response_contains
        for kw in expected.get("response_contains", []):
            checks_total += 1
            response = trial_output.get("response", "")
            if kw.lower() in response.lower():
                checks_passed += 1
            else:
                issues.append(f"response_missing_keyword: {kw}")

        # response_not_contains
        for kw in expected.get("response_not_contains", []):
            checks_total += 1
            response = trial_output.get("response", "")
            if kw.lower() not in response.lower():
                checks_passed += 1
            else:
                issues.append(f"response_contains_forbidden: {kw}")

        # tool_call 断言
        for tc in expected.get("tool_call", []):
            checks_total += 1
            if self._check_tool_call(tc, trial_output.get("trace_records", [])):
                checks_passed += 1
            else:
                issues.append(f"tool_call_missing: {tc}")

        # max_tool_calls
        if "max_tool_calls" in expected:
            checks_total += 1
            actual = trial_output.get("tool_calls", 0)
            if actual <= expected["max_tool_calls"]:
                checks_passed += 1
            else:
                issues.append(f"max_tool_calls_exceeded: {actual} > {expected['max_tool_calls']}")

        # file_content_contains
        for fcc in expected.get("file_content_contains", []):
            checks_total += 1
            fp = fcc.get("path", "")
            kw = fcc.get("keyword", "")
            content = trial_output.get("file_contents", {}).get(fp, "")
            if kw.lower() in content.lower():
                checks_passed += 1
            else:
                issues.append(f"file_content_missing_keyword: {fp} / {kw}")

        if checks_total == 0:
            deduction = 0
        else:
            failed = checks_total - checks_passed
            deduction = min(failed * 5, self.MAX_DEDUCTION)

        score = max(0, self.MAX_DEDUCTION - deduction)

        return {
            "grader": "ResultGrader",
            "score": score,
            "max_score": self.MAX_DEDUCTION,
            "deduction": deduction,
            "checks_passed": checks_passed,
            "checks_total": checks_total,
            "issues": issues,
        }

    def _check_tool_call(self, expected: dict, trace: list[dict]) -> bool:
        """检查 Trace 中是否包含匹配的工具调用。"""
        name = expected.get("name", "")
        contains = expected.get("contains", "")
        for r in trace:
            if r.get("phase") != "pre":
                continue
            tool = r.get("tool", "")
            inp = json.dumps(r.get("input", {}))
            if name and name not in tool:
                continue
            if contains and contains not in inp:
                continue
            return True
        return False


# ======================================================
# 综合评分
# ======================================================

RESULT_CRITICAL = 80  # 关键判定扣分阈值（对应腾讯方案的 key_judgment）


def compute_trial_score(grades: list[dict],
                         critical_failure: bool = False) -> dict:
    """从各评分器结果计算单次 Trial 综合得分。

    负分制, 初始 100 分。关键判定失败直接扣 80 分。
    """
    if critical_failure:
        trial_score = 20
        status = "CRITICAL_FAIL"
    else:
        total_deduction = sum(g.get("deduction", 0) for g in grades)
        trial_score = max(0, 100 - total_deduction)
        status = "PASS" if trial_score >= 80 else "FAIL"

    return {
        "trial_score": trial_score,
        "status": status,
        "grades": grades,
    }


def compute_case_score(trial_scores: list[int],
                        threshold: int = 80) -> dict:
    """从多轮 Trial 计算用例综合得分。

    pass^k 逻辑: 任一 Trial 不达标 -> 用例 0 分。
    """
    n = len(trial_scores)
    all_pass = all(s >= threshold for s in trial_scores)
    avg = sum(trial_scores) / n if n > 0 else 0

    return {
        "case_score": round(avg, 1) if all_pass else 0,
        "all_pass": all_pass,
        "trials": n,
        "trial_scores": trial_scores,
        "avg_trial_score": round(avg, 1),
        "threshold": threshold,
    }
