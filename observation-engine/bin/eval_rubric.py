#!/usr/bin/env python3
"""Rubric Grader -- LLM-as-Judge 模型评分器。

调用 Claude CLI 对 Agent 输出进行语义评分。
参考: Anthropic model-based grader + 腾讯 Rubric 评分器方案。

核心维度:
  process_score  -- 推理过程质量 (0-100)
  result_score   -- 结果质量/准确性 (0-100)
  is_false_positive -- 是否虚假成功(结果对但过程错)
"""

import json
import os
import subprocess
from pathlib import Path

ERROR_LOG = Path.home() / ".claude" / "observations" / "errors.log"


def _log_error(msg: str) -> None:
    try:
        from datetime import datetime, timezone
        ts = datetime.now(timezone.utc).isoformat()
        with open(ERROR_LOG, "a", encoding="utf-8") as f:
            f.write(f"[{ts}] [rubric] {msg}\n")
    except Exception:
        pass


def _build_scoring_prompt(case: dict, trial_output: dict,
                           baseline: dict | None = None) -> str:
    """构建结构化评分 prompt。"""
    prompt_parts = [
        "You are an expert evaluator for AI agent outputs. "
        "Score the agent's response against the provided rubric.",
        "",
        "## Task Description",
        f"Name: {case.get('name', 'unnamed')}",
        f"Scenario: {case.get('scenario', 'general')}",
        f"Prompt: {case.get('prompt', '')[:500]}",
    ]

    if baseline:
        prompt_parts += [
            "",
            "## Reference Answer (Baseline)",
            f"Response: {baseline.get('response', '')[:1000]}",
            f"Step count: {baseline.get('tool_calls', 'N/A')}",
        ]

    prompt_parts += [
        "",
        "## Agent's Response to Evaluate",
        f"Response: {trial_output.get('response', '')[:2000]}",
        f"Tool calls made: {trial_output.get('tool_calls', 0)}",
        f"Elapsed time: {trial_output.get('elapsed_s', 0):.0f}s",
    ]

    # 加载 rubric 定义
    rubric = case.get("rubric", {})
    observation_points = rubric.get("observation_points", [
        "Did the agent correctly understand and address the user's request?",
        "Was the reasoning process logical and well-structured?",
        "Did the agent avoid hallucination or fabricating information?",
        "Was the response complete and covered all key points?",
    ])

    prompt_parts += [
        "",
        "## Scoring Rubric",
        "Evaluate the following dimensions:",
    ]
    for i, point in enumerate(observation_points, 1):
        prompt_parts.append(f"{i}. {point}")

    prompt_parts += [
        "",
        "## Output Format",
        "Return ONLY a valid JSON object (no markdown, no explanation):",
        "{",
        '  "process_score": <0-100, quality of reasoning and tool use>,',
        '  "result_score": <0-100, correctness and completeness of the answer>,',
        '  "is_false_positive": <true/false, result is correct but reasoning/steps are wrong>,',
        '  "hallucination_detected": <true/false, agent fabricated facts or data>,',
        '  "strengths": "<1-2 sentences on what was done well>",',
        '  "weaknesses": "<1-2 sentences on what needs improvement>"',
        "}",
        "",
        "Before scoring, briefly consider: does the agent's response actually address "
        "the user's request? Is there any made-up information? Would a human expert "
        "accept this answer?",
    ]

    return "\n".join(prompt_parts)


class RubricGrader:
    """LLM-as-Judge 评分器。

    调用 Claude CLI 对 Agent 输出进行语义质量评估。
    失败时静默退化，返回默认空评分。
    """

    MAX_DEDUCTION = 40
    TIMEOUT = 90

    def grade(self, case: dict, trial_output: dict,
              baseline: dict | None = None) -> dict:
        """对单次 Trial 执行语义评分。"""
        prompt = _build_scoring_prompt(case, trial_output, baseline)

        try:
            result = subprocess.run(
                ["claude", "--print", "--output-format", "json",
                 "-p", prompt],
                capture_output=True, text=True, timeout=self.TIMEOUT,
                encoding="utf-8", errors="replace",
                env={**os.environ, "CLAUDE_CODE_SIMPLE": "1"},
            )

            if result.returncode != 0:
                _log_error(f"CLI error (rc={result.returncode}): "
                           f"{result.stderr[:200]}")
                return self._empty_grade("CLI error")

            parsed = self._parse_response(result.stdout)
            return self._to_grade_format(parsed)

        except FileNotFoundError:
            _log_error("claude CLI not found")
            return self._empty_grade("claude CLI not found")
        except subprocess.TimeoutExpired:
            _log_error("Rubric grader timed out")
            return self._empty_grade("timeout")
        except Exception as e:
            _log_error(f"Rubric grader error: {e}")
            return self._empty_grade(str(e)[:100])

    def _parse_response(self, stdout: str) -> dict:
        """解析 Claude CLI 返回的结构化 JSON。"""
        try:
            data = json.loads(stdout)
        except json.JSONDecodeError:
            # 尝试从文本中提取 JSON
            import re
            match = re.search(r'\{[^}]+\}', stdout, re.DOTALL)
            if match:
                try:
                    data = json.loads(match.group(0))
                except json.JSONDecodeError:
                    return {}
            else:
                return {}

        # 处理 claude --print 的各种返回格式
        if isinstance(data, dict):
            answer = (data.get("result") or data.get("text")
                      or data.get("response") or data.get("output", ""))
        else:
            answer = str(data)

        if isinstance(answer, str):
            try:
                return json.loads(answer)
            except json.JSONDecodeError:
                return {}
        return answer if isinstance(answer, dict) else {}

    def _to_grade_format(self, parsed: dict) -> dict:
        """将 LLM 返回转为标准评分格式。"""
        process_score = max(0, min(100, parsed.get("process_score", 70)))
        result_score = max(0, min(100, parsed.get("result_score", 70)))
        avg_score = (process_score + result_score) / 2

        # 转换为 40 分制下的扣分
        deduction = round((100 - avg_score) / 100 * self.MAX_DEDUCTION)
        deduction = min(deduction, self.MAX_DEDUCTION)
        score = max(0, self.MAX_DEDUCTION - deduction)

        return {
            "grader": "RubricGrader",
            "score": score,
            "max_score": self.MAX_DEDUCTION,
            "deduction": deduction,
            "process_score": process_score,
            "result_score": result_score,
            "is_false_positive": parsed.get("is_false_positive", False),
            "hallucination_detected": parsed.get("hallucination_detected", False),
            "strengths": parsed.get("strengths", ""),
            "weaknesses": parsed.get("weaknesses", ""),
            "issues": [
                f"process={process_score}",
                f"result={result_score}",
            ] + ([
                "FALSE_POSITIVE: result ok but process wrong",
            ] if parsed.get("is_false_positive") else []) + ([
                "HALLUCINATION: fabricated content detected",
            ] if parsed.get("hallucination_detected") else []),
        }

    def _empty_grade(self, reason: str = "skipped") -> dict:
        return {
            "grader": "RubricGrader",
            "score": self.MAX_DEDUCTION,
            "max_score": self.MAX_DEDUCTION,
            "deduction": 0,
            "process_score": 0,
            "result_score": 0,
            "is_false_positive": False,
            "hallucination_detected": False,
            "strengths": "",
            "weaknesses": "",
            "issues": [f"skipped -- {reason}"],
        }
