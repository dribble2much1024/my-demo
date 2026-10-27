#!/usr/bin/env python3
"""Eval Instinct -- 测评退化模式检测器。

从多个测评报告的历史数据中检测退化模式，输出 Instinct 格式的 .md 文件，
可被 auto-evolve.py 聚合进 auto-evolved.md。

检测器:
  1. eval-score-volatility  -- 同一用例得分跨 session 波动大
  2. eval-cost-inflation     -- Token/耗时持续上升趋势
  3. eval-step-drift         -- 步骤序列逐渐偏离基线
  4. eval-failure-cluster    -- 失败集中在特定场景

用法:
  python eval_instinct.py                           # 分析所有历史报告
  python eval_instinct.py --reports-dir eval_results/  # 指定目录
"""

import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

INSTINCTS_DIR = Path.home() / ".claude" / "homunculus" / "instincts" / "personal"
EVAL_RESULTS_DIR = Path(__file__).resolve().parent.parent / "eval_results"


def _iter_reports(reports_dir: Path) -> list[dict]:
    """加载所有历史 JSON 报告。"""
    reports = []
    for json_file in sorted(reports_dir.rglob("report-*.json")):
        try:
            with open(json_file, "r", encoding="utf-8") as f:
                reports.append(json.load(f))
        except (json.JSONDecodeError, IOError):
            continue
    return reports


def _group_cases_across_reports(reports: list[dict]) -> dict[str, list[dict]]:
    """跨报告按 case_id 分组。"""
    groups: dict[str, list[dict]] = defaultdict(list)
    for r in reports:
        for case in r.get("cases", []):
            cid = case.get("case_id", "")
            groups[cid].append({
                "session_id": r.get("session_id", ""),
                "generated_at": r.get("generated_at", ""),
                "case_score": case.get("case_score", 0),
                "trial_scores": case.get("trial_scores", []),
                "all_pass": case.get("all_pass", False),
            })
    return dict(groups)


# ======================================================
# 检测器 1: 得分波动
# ======================================================

def detect_score_volatility(case_groups: dict) -> list[dict]:
    """检测同一用例跨 session 得分波动 >= 30 分的异常。"""
    results = []
    for cid, histories in case_groups.items():
        if len(histories) < 3:
            continue
        scores = [h["case_score"] for h in histories]
        score_range = max(scores) - min(scores)
        if score_range >= 30:
            std = (sum((s - sum(scores) / len(scores)) ** 2
                      for s in scores) / len(scores)) ** 0.5
            results.append({
                "detector": "eval-score-volatility",
                "case_id": cid,
                "sessions": len(histories),
                "score_range": score_range,
                "std_dev": round(std, 1),
                "scores": scores,
            })
    return results


# ======================================================
# 检测器 2: 成本膨胀
# ======================================================

def detect_cost_inflation(reports: list[dict]) -> list[dict]:
    """检测 Token 消耗 / 耗时呈上升趋势的用例。"""
    # 从 trial_details 中的 EfficiencyGrader 数据提取
    cost_trends: dict[str, list[dict]] = defaultdict(list)

    for r in reports:
        for case in r.get("cases", []):
            cid = case.get("case_id", "")
            for td in case.get("trial_details", []):
                for g in td.get("grades", []):
                    if g.get("grader") == "EfficiencyGrader":
                        trial_data = g.get("trial", {})
                        baseline_data = g.get("baseline", {})
                        if trial_data:
                            cost_trends[cid].append({
                                "session": r.get("session_id", "")[:8],
                                "token_count": trial_data.get("token_count", 0),
                                "elapsed_s": trial_data.get("elapsed_s", 0),
                            })

    results = []
    for cid, entries in cost_trends.items():
        if len(entries) < 3:
            continue
        tokens = [e["token_count"] for e in entries if e["token_count"] > 0]
        times = [e["elapsed_s"] for e in entries if e["elapsed_s"] > 0]

        if len(tokens) >= 3:
            # 简单线性趋势: 后半段平均 vs 前半段平均
            mid = len(tokens) // 2
            first_half = sum(tokens[:mid]) / mid
            second_half = sum(tokens[mid:]) / (len(tokens) - mid)
            if first_half > 0 and second_half / first_half > 1.3:
                results.append({
                    "detector": "eval-cost-inflation",
                    "case_id": cid,
                    "metric": "tokens",
                    "first_half_avg": round(first_half),
                    "second_half_avg": round(second_half),
                    "increase": f"{(second_half / first_half - 1) * 100:.0f}%",
                })

        if len(times) >= 3:
            mid = len(times) // 2
            first_half = sum(times[:mid]) / mid
            second_half = sum(times[mid:]) / (len(times) - mid)
            if first_half > 0 and second_half / first_half > 1.3:
                results.append({
                    "detector": "eval-cost-inflation",
                    "case_id": cid,
                    "metric": "latency",
                    "first_half_avg": f"{first_half:.0f}s",
                    "second_half_avg": f"{second_half:.0f}s",
                    "increase": f"{(second_half / first_half - 1) * 100:.0f}%",
                })

    return results


# ======================================================
# 检测器 3: 失败聚类
# ======================================================

def detect_failure_cluster(case_groups: dict) -> list[dict]:
    """检测失败集中在特定 scenario 的异常。"""
    # 按 scenario 聚合（从 case_id 前缀近似推断）
    scenario_patterns = defaultdict(lambda: {"total": 0, "fails": 0, "cases": []})

    for cid, histories in case_groups.items():
        if not histories:
            continue
        # 从 case_id 推断 scenario: trigger-*, logic-*, output-*, error-*, boundary-*
        prefix = cid.split("-")[0] if "-" in cid else "unknown"
        fail_count = sum(1 for h in histories if not h["all_pass"])
        scenario_patterns[prefix]["total"] += len(histories)
        scenario_patterns[prefix]["fails"] += fail_count
        scenario_patterns[prefix]["cases"].append(cid)

    results = []
    for scenario, data in scenario_patterns.items():
        if data["total"] >= 5:
            fail_rate = data["fails"] / data["total"]
            if fail_rate >= 0.3:
                results.append({
                    "detector": "eval-failure-cluster",
                    "scenario": scenario,
                    "total_runs": data["total"],
                    "failures": data["fails"],
                    "fail_rate": f"{fail_rate:.0%}",
                    "affected_cases": data["cases"][:5],
                })

    return results


# ======================================================
# 生成 Instinct 文件
# ======================================================

def _md_frontmatter(detector_id: str, confidence: float = 0.55) -> str:
    return f"""---
name: {detector_id}
description: Auto-detected eval degradation pattern
type: observation
confidence: {confidence}
domain: eval-quality
detected_at: {datetime.now(timezone.utc).isoformat()}
source: eval_instinct.py
---

"""


def generate_instincts(detections: list[dict]) -> list[Path]:
    """将检测结果写入 Instinct .md 文件。"""
    INSTINCTS_DIR.mkdir(parents=True, exist_ok=True)
    written = []

    for d in detections:
        detector = d["detector"]
        md_path = INSTINCTS_DIR / f"{detector}.md"

        if detector == "eval-score-volatility":
            body = f"""# eval-score-volatility

## Evidence
Case **{d['case_id']}** shows score volatility across {d['sessions']} sessions:
- Score range: {d['score_range']} points
- Std deviation: {d['std_dev']}
- Scores: {d['scores']}

## Pattern
When the same test case produces wildly different scores across sessions,
the agent's behavior is unstable for that task.

## Action
- Review the case prompt for ambiguity
- Check if the volatility is model-version-specific
- Add more deterministic checks to reduce reliance on LLM variability
"""

        elif detector == "eval-cost-inflation":
            body = f"""# eval-cost-inflation

## Evidence
Case **{d['case_id']}** shows {d['metric']} inflation:
- First half avg: {d['first_half_avg']}
- Second half avg: {d['second_half_avg']}
- Increase: {d['increase']}

## Pattern
Token or latency trending upward suggests the agent is becoming
less efficient at this task over time.

## Action
- Check if tool call count is increasing
- Verify the context isn't bloating with stale data
- Consider resetting the conversation pattern for this case
"""

        elif detector == "eval-failure-cluster":
            cases_str = ", ".join(d.get("affected_cases", [])[:5])
            body = f"""# eval-failure-cluster

## Evidence
Scenario **{d['scenario']}** has a high failure rate:
- Fail rate: {d['fail_rate']} ({d['failures']}/{d['total_runs']})
- Affected cases: {cases_str}

## Pattern
Failures clustering in one scenario category suggest a systemic
issue rather than isolated case problems.

## Action
- Review the scenario's common tool chain for regressions
- Check if the skill's prompt or logic changed recently
- Increase test coverage in this scenario
"""

        else:
            body = f"# {detector}\n\nAuto-detected pattern.\n"

        content = _md_frontmatter(detector) + body
        with open(md_path, "w", encoding="utf-8") as f:
            f.write(content)
        written.append(md_path)

    return written


# ======================================================
# Main
# ======================================================

def main():
    import argparse
    parser = argparse.ArgumentParser(description="Eval Instinct Detector")
    parser.add_argument("--reports-dir", type=str,
                        help="测评报告目录 (默认: eval_results/)")
    args = parser.parse_args()

    reports_dir = Path(args.reports_dir) if args.reports_dir else EVAL_RESULTS_DIR

    print(f"[eval-instinct] Scanning: {reports_dir}")
    reports = _iter_reports(reports_dir)
    if not reports:
        print("[eval-instinct] No reports found, skipping")
        return

    print(f"[eval-instinct] Loaded {len(reports)} reports")

    case_groups = _group_cases_across_reports(reports)

    detections = []
    detections += detect_score_volatility(case_groups)
    detections += detect_cost_inflation(reports)
    detections += detect_failure_cluster(case_groups)

    if not detections:
        print("[eval-instinct] No degradation patterns detected")
        return

    print(f"[eval-instinct] Detected {len(detections)} pattern(s):")
    for d in detections:
        print(f"  - {d['detector']}: {d.get('case_id', d.get('scenario', '?'))}")

    written = generate_instincts(detections)
    for w in written:
        print(f"  -> {w}")


if __name__ == "__main__":
    main()
