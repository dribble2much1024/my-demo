#!/usr/bin/env python3
"""Eval CI Gate -- 测评门禁脚本。

集成到 Claude Code Stop hook 或 CI 流水线:
  Stop hook: py observation-engine/bin/eval_ci.py --quick
  CI 流水线: py observation-engine/bin/eval_ci.py --suite regression.json

返回值:
  0 = 全部通过
  1 = 有失败用例
  2 = 测评执行异常（跳过门禁，不阻塞）
"""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from eval_harness import EvalHarness, OBSERVATIONS_FILE

EVAL_CASES_DIR = SCRIPT_DIR.parent / "eval_cases"
EVAL_RESULTS_DIR = SCRIPT_DIR.parent / "eval_results"

# Quick 模式: 每个场景只跑 1 个关键用例
QUICK_CASE_IDS = [
    "trigger-pos-01",
    "trigger-neg-01",
    "logic-read-01",
    "output-pos-01",
    "error-input-01",
]


def _build_quick_suite(cases: list[dict]) -> list[dict]:
    """从完整用例集中提取 quick 模式的关键用例。"""
    case_map = {c["id"]: c for c in cases}
    quick_cases = []
    for cid in QUICK_CASE_IDS:
        if cid in case_map:
            quick_cases.append(case_map[cid])
    return quick_cases


def _latest_session() -> str | None:
    """获取最近一次 Claude Code 会话的 session_id。"""
    if not OBSERVATIONS_FILE.exists():
        return None
    try:
        with open(OBSERVATIONS_FILE, "r", encoding="utf-8") as f:
            last_line = None
            for line in f:
                if line.strip():
                    last_line = line.strip()
            if last_line:
                return json.loads(last_line).get("session_id")
    except Exception:
        pass
    return None


def run_ci(suite_path: str, quick: bool = False,
           replay_session: str | None = None) -> int:
    """运行 CI 门禁测评，返回退出码。"""
    suite_file = Path(suite_path)

    if not suite_file.exists():
        print(f"[eval-ci] Suite not found: {suite_path}, skipping")
        return 0  # 没有套件时不阻塞

    try:
        harness = EvalHarness(
            suite_path=str(suite_file),
            trials=1 if quick else 3,
            threshold=80,
            replay_session=replay_session,
            baseline_mode=False,
            rubric_mode=False,  # CI 模式关闭 Rubric 以提速
        )

        # Quick 模式: 只跑关键用例
        if quick:
            all_cases = harness.suite.get("cases", [])
            harness.suite["cases"] = _build_quick_suite(all_cases)
            harness.suite["name"] = harness.suite.get("name", "") + " [QUICK]"

        report = harness.run()
        summary = report["summary"]

        # 门禁判定
        passed = summary["passed"]
        total = summary["total_cases"]
        pass_rate_str = summary["pass_rate"]

        if total == 0:
            print(f"[eval-ci] No cases to run, passing")
            return 0

        if passed == total:
            print(f"[eval-ci] GATE PASS: {pass_rate_str} ({passed}/{total})")
            return 0
        else:
            failures = total - passed
            print(f"[eval-ci] GATE FAIL: {failures} case(s) below threshold "
                  f"({pass_rate_str}, {passed}/{total})")
            # 打印失败详情
            for case in report.get("cases", []):
                if not case.get("all_pass"):
                    print(f"  X {case['case_id']}: {case['case_name']} "
                          f"-> {case['case_score']}")
            return 1

    except Exception as e:
        print(f"[eval-ci] ERROR (non-blocking): {e}")
        return 2  # 执行异常不阻塞


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Eval CI Gate")
    parser.add_argument("--suite", type=str,
                        help="回归套件路径 (默认: sample_suite.json)")
    parser.add_argument("--quick", action="store_true",
                        help="快速模式: 只跑 5 个关键用例")
    parser.add_argument("--replay-session", type=str,
                        help="指定回放 session (默认: 自动取最新)")
    args = parser.parse_args()

    suite = args.suite
    if not suite:
        # 默认: 查找 eval_cases 下第一个 *_regression*.json
        regression_files = list(EVAL_CASES_DIR.glob("*_regression*.json"))
        if regression_files:
            suite = str(regression_files[0])
        else:
            suite = str(EVAL_CASES_DIR / "sample_suite.json")

    replay = args.replay_session or _latest_session()

    if args.quick:
        print(f"[eval-ci] Quick mode: {len(QUICK_CASE_IDS)} key cases")
    print(f"[eval-ci] Suite: {suite}")
    if replay:
        print(f"[eval-ci] Replay session: {replay}")

    exit_code = run_ci(suite, quick=args.quick, replay_session=replay)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
