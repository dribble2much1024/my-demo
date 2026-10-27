#!/usr/bin/env python3
"""Eval Bad Case -- 失败用例自动发现与转化。

从最新测评报告中:
  1. 识别失败用例
  2. 提取失败特征 (缺失关键词 / 工具调用偏差 / 效率问题)
  3. 自动生成能力测评用例 JSON

生成的用例追加到能力测评集，供下次测评验证。

用法:
  python eval_badcase.py                              # 扫描最新报告
  python eval_badcase.py --report report-xxx.json     # 指定报告
  python eval_badcase.py --output new_cases.json      # 输出到指定文件
"""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

EVAL_RESULTS_DIR = Path(__file__).resolve().parent.parent / "eval_results"
EVAL_CASES_DIR = Path(__file__).resolve().parent.parent / "eval_cases"


def _find_latest_report() -> Path | None:
    """找到最新的 JSON 测评报告。"""
    json_files = sorted(EVAL_RESULTS_DIR.rglob("report-*.json"),
                         reverse=True)
    for f in json_files:
        # 跳过 baseline 文件
        if "baseline" not in str(f):
            return f
    return None


def _extract_failure_signature(case: dict) -> dict | None:
    """从失败用例中提取失败特征签名。

    返回可转为用例定义的签名结构。
    """
    cid = case.get("case_id", "unknown")
    cname = case.get("case_name", cid)
    trial_scores = case.get("trial_scores", [])
    trial_details = case.get("trial_details", [])

    if not trial_details:
        return None

    # 聚合所有 Trial 中所有 Grader 的 issues
    all_issues: dict[str, list[str]] = {}
    failing_checks: list[str] = []

    for td in trial_details:
        for g in td.get("grades", []):
            gname = g.get("grader", "Unknown")
            issues = g.get("issues", [])
            for issue in issues:
                all_issues.setdefault(gname, [])
                if issue not in all_issues[gname]:
                    all_issues[gname].append(issue)

            # 收集 ResultGrader 中的具体失败项
            if gname == "ResultGrader":
                for issue in issues:
                    if issue.startswith("response_missing_keyword:"):
                        kw = issue.split(":", 1)[1].strip()
                        failing_checks.append(kw)
                    elif issue.startswith("file_missing:"):
                        fp = issue.split(":", 1)[1].strip()
                        failing_checks.append(f"file:{fp}")
                    elif issue.startswith("tool_call_missing:"):
                        tc = issue.split(":", 1)[1].strip()
                        failing_checks.append(f"tool:{tc}")

    if not all_issues:
        return None

    # 构建 Bad Case 用例定义
    bc_id = f"badcase-{cid}"
    bc_name = f"BadCase: {cname}"

    # 提取原始 prompt（从 trial 数据中难以获取，用描述代替）
    prompt_hint = f"Auto-generated from failed case {cid}. "
    prompt_hint += f"Issues: {'; '.join(failing_checks[:3])}" if failing_checks else ""

    new_case = {
        "id": bc_id,
        "name": bc_name,
        "description": f"从失败用例 {cid} 自动生成的增强测试",
        "scenario": "error_handling",
        "source_case": cid,
        "source_session": case.get("trial_details", [{}])[0].get(
            "session_id", ""),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "prompt": prompt_hint,
        "expected_behavior": {
            "response_contains": failing_checks if failing_checks else [],
            "max_tool_calls": 10,
        },
        "rubric": {
            "observation_points": [
                f"是否避免了之前失败的问题: {'; '.join(failing_checks[:3])}",
                "推理过程是否清晰",
                "是否存在与之前相同的失败模式",
            ],
        },
        "tags": ["auto-generated", "badcase"],
    }

    return new_case


def _merge_into_suite(new_cases: list[dict],
                       suite_path: Path | None = None) -> Path:
    """将 Bad Case 合并到能力测评集。"""
    if suite_path is None:
        # 默认: 创建或追加到 badcase_capability.json
        suite_path = EVAL_CASES_DIR / "badcase_capability.json"

    if suite_path.exists():
        with open(suite_path, "r", encoding="utf-8") as f:
            suite = json.load(f)
    else:
        suite = {
            "name": "badcase-capability-suite",
            "description": "从测评失败自动生成的能力测评集",
            "version": "1.0.0",
            "threshold": 80,
            "trials": 1,
            "cases": [],
        }

    existing_ids = {c["id"] for c in suite["cases"]}
    added = 0
    for nc in new_cases:
        if nc["id"] not in existing_ids:
            suite["cases"].append(nc)
            existing_ids.add(nc["id"])
            added += 1

    with open(suite_path, "w", encoding="utf-8") as f:
        json.dump(suite, f, ensure_ascii=False, indent=2)

    if added > 0:
        print(f"[badcase] Added {added} new cases to {suite_path}")

    return suite_path


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Bad Case Auto-Discovery")
    parser.add_argument("--report", type=str,
                        help="指定测评报告 JSON (默认: 最新)")
    parser.add_argument("--output", type=str,
                        help="输出用例文件路径 (默认: badcase_capability.json)")
    args = parser.parse_args()

    # 加载报告
    if args.report:
        report_path = Path(args.report)
    else:
        report_path = _find_latest_report()

    if not report_path or not report_path.exists():
        print("[badcase] No report found, skipping")
        return

    print(f"[badcase] Loading: {report_path}")
    with open(report_path, "r", encoding="utf-8") as f:
        report = json.load(f)

    cases = report.get("cases", [])
    failed_cases = [c for c in cases if not c.get("all_pass", False)]

    if not failed_cases:
        print(f"[badcase] All {len(cases)} cases passed, no bad cases")
        return

    print(f"[badcase] Found {len(failed_cases)} failed case(s):")
    for c in failed_cases:
        print(f"  X {c['case_id']}: {c['case_name']} -> {c.get('case_score', 0)}")

    # 提取失败签名
    new_cases = []
    for fc in failed_cases:
        sig = _extract_failure_signature(fc)
        if sig:
            new_cases.append(sig)
            print(f"  -> generated: {sig['id']}")

    if not new_cases:
        print("[badcase] Could not extract failure signatures")
        return

    # 合并到用例集
    output = Path(args.output) if args.output else None
    suite_path = _merge_into_suite(new_cases, output)

    print(f"[badcase] Done. Suite: {suite_path}")
    print(f"[badcase] Run: py eval_harness.py --suite {suite_path} --trials 3 "
          f"to validate bad cases are fixed")


if __name__ == "__main__":
    main()
