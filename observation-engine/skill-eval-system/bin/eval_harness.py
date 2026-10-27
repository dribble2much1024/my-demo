#!/usr/bin/env python3
"""Eval Harness -- AI Agent/Skill 测评编排引擎。

Phase 2: 确定性 + Rubric 双评分器 + HTML 报告。

用法:
  python eval_harness.py --suite sample_suite.json              # 运行测评套件
  python eval_harness.py --suite sample_suite.json --trials 3   # 多轮稳定性评估
  python eval_harness.py --suite sample_suite.json --baseline   # 建立基线模式
  python eval_harness.py --suite sample_suite.json --replay <session_id>  # 回放模式
  python eval_harness.py --suite sample_suite.json --rubric     # 启用 LLM 语义评分

架构:
  用例集(JSON) -> Trial 编排 -> observation-engine Trace 解析 -> 评分器 -> 报告
"""

import json
import os
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

# Windows GBK encoding workaround
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# 添加评分器路径
sys.path.insert(0, str(Path(__file__).resolve().parent))
from eval_graders import (
    StepGrader,
    EfficiencyGrader,
    ResultGrader,
    compute_trial_score,
    compute_case_score,
    extract_tool_sequence,
    normalize_step,
)
from eval_rubric import RubricGrader
from eval_reporter import generate_html_report

# ======================================================
# 配置
# ======================================================

DEFAULT_THRESHOLD = 80
DEFAULT_TRIALS = 1
OBSERVATIONS_FILE = Path.home() / ".claude" / "observations" / "observations.jsonl"
EVAL_DIR = Path(__file__).resolve().parent.parent / "eval_results"


class EvalHarness:
    """测评编排引擎。"""

    def __init__(self, suite_path: str, trials: int = DEFAULT_TRIALS,
                 threshold: int = DEFAULT_THRESHOLD,
                 replay_session: str | None = None,
                 baseline_mode: bool = False,
                 rubric_mode: bool = False):
        self.suite_path = Path(suite_path)
        self.suite = self._load_suite()
        self.trials = trials
        self.threshold = threshold
        self.replay_session = replay_session
        self.baseline_mode = baseline_mode
        self.rubric_mode = rubric_mode

        self.step_grader = StepGrader()
        self.eff_grader = EfficiencyGrader()
        self.result_grader = ResultGrader()
        self.rubric_grader = RubricGrader() if rubric_mode else None

        self.results: list[dict] = []
        self.session_id = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")

    # --- 加载 ---

    def _load_suite(self) -> dict:
        """加载 JSON 用例集。"""
        with open(self.suite_path, "r", encoding="utf-8") as f:
            return json.load(f)

    # -- Trace 解析 -------------------------------------

    def _load_observations(self) -> list[dict]:
        """加载 observation-engine JSONL 记录。"""
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

    def _filter_session(self, records: list[dict],
                         session_id: str | None = None) -> list[dict]:
        """筛选指定 session 的记录。"""
        if session_id:
            return [r for r in records if r.get("session_id") == session_id]
        # 按 session_id 分组，取最新的
        sessions: dict[str, list[dict]] = {}
        for r in records:
            sid = r.get("session_id", "")
            sessions.setdefault(sid, []).append(r)
        if not sessions:
            return []
        latest = max(sessions.keys(),
                      key=lambda s: sessions[s][-1].get("ts", ""))
        return sessions[latest]

    def _build_trial_output(self, records: list[dict],
                             response: str = "") -> dict:
        """从 Trace 记录构建 trial_output 结构。"""
        steps = extract_tool_sequence(records)

        # 统计工具调用次数
        tool_calls = len(steps)

        # 估算 token（粗略: 每字符 ~0.25 token）
        total_chars = sum(
            len(json.dumps(r.get("input", {})))
            + len(str(r.get("output_summary", "")))
            for r in records
        )
        estimated_tokens = total_chars // 4

        # 计算耗时（从第一条到最后一条记录的时间差）
        timestamps = [r.get("ts", "") for r in records if r.get("ts")]
        elapsed_s = 0
        if len(timestamps) >= 2:
            try:
                t0 = datetime.fromisoformat(timestamps[0].replace("Z", "+00:00"))
                t1 = datetime.fromisoformat(timestamps[-1].replace("Z", "+00:00"))
                elapsed_s = (t1 - t0).total_seconds()
            except (ValueError, TypeError):
                pass

        # 检测创建的文件
        files_created = self._detect_files_created(records)

        return {
            "response": response,
            "tool_calls": tool_calls,
            "token_count": estimated_tokens,
            "elapsed_s": elapsed_s,
            "trace_records": records,
            "steps": steps,
            "files_created": files_created,
            "file_contents": {},
        }

    def _detect_files_created(self, records: list[dict]) -> list[str]:
        """从 Trace 中检测 Write 工具创建的文件。"""
        files = []
        for r in records:
            if r.get("phase") != "pre":
                continue
            tool = r.get("tool", "")
            if tool in ("Write", "write_file"):
                inp = r.get("input", {})
                fp = inp.get("file_path", inp.get("path", ""))
                if fp:
                    files.append(fp)
        return files

    # -- 基线管理 --------------------------------------

    def _get_baseline_path(self, case_id: str) -> Path:
        """获取用例基线存储路径。"""
        suite_name = self.suite_path.stem
        base = EVAL_DIR / "baselines" / suite_name / case_id
        base.mkdir(parents=True, exist_ok=True)
        return base / "baseline.json"

    def _save_baseline(self, case_id: str, trial_output: dict) -> None:
        """保存基线快照。"""
        path = self._get_baseline_path(case_id)
        baseline = {
            "case_id": case_id,
            "saved_at": datetime.now(timezone.utc).isoformat(),
            "elapsed_s": trial_output.get("elapsed_s", 0),
            "token_count": trial_output.get("token_count", 0),
            "tool_calls": trial_output.get("tool_calls", 0),
            "steps": [
                {"tool": s["tool"], "normalized": s["normalized"]}
                for s in trial_output.get("steps", [])
            ],
            "files_created": trial_output.get("files_created", []),
            "response": trial_output.get("response", ""),
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(baseline, f, ensure_ascii=False, indent=2)
        print(f"  [baseline] saved -> {path}")

    def _load_baseline(self, case_id: str) -> dict | None:
        """加载基线快照。"""
        path = self._get_baseline_path(case_id)
        if not path.exists():
            return None
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    # -- 执行 ------------------------------------------

    def _execute_case(self, case: dict) -> dict:
        """执行单个用例（通过 Claude Code CLI 或 replay 模式）。"""
        prompt = case.get("prompt", "")

        if self.replay_session:
            return self._replay_execute(case)
        else:
            return self._live_execute(prompt)

    def _replay_execute(self, case: dict) -> dict:
        """回放模式：从已有 observations.jsonl 中提取指定 session 的 Trace。"""
        records = self._load_observations()
        session_records = self._filter_session(records, self.replay_session)

        if not session_records:
            print(f"  [!] No records found for session={self.replay_session}")
            return self._empty_trial_output()

        print(f"  [replay] session={self.replay_session}, records={len(session_records)}")
        return self._build_trial_output(session_records)

    def _live_execute(self, prompt: str) -> dict:
        """执行模式：调用 Claude Code CLI。

        通过 --print --output-format json 获取结构化响应。
        Trace 从 observations.jsonl 中捕获（取执行后新增的记录）。
        """
        print(f"  [execute] prompt={prompt[:100]}...")

        # 记录执行前的 observations 行数
        before_count = self._count_observations()

        response = ""
        try:
            result = subprocess.run(
                ["claude", "--print", "--output-format", "json",
                 "-p", prompt],
                capture_output=True, text=True, timeout=300,
                encoding="utf-8", errors="replace",
            )
            response = result.stdout.strip()
            if result.stderr:
                print(f"  [stderr] {result.stderr[:200]}")
        except FileNotFoundError:
            print("  [!] claude CLI not found -- falling back to empty trace")
            return self._empty_trial_output()
        except subprocess.TimeoutExpired:
            print("  [!] claude CLI timed out (300s)")
            return self._empty_trial_output()

        # 读取执行后新增的 observations
        after_count = self._count_observations()
        records = self._load_observations()
        new_records = records[-max(1, after_count - before_count):]

        trial = self._build_trial_output(new_records, response)
        return trial

    def _count_observations(self) -> int:
        """统计 observations.jsonl 行数。"""
        if not OBSERVATIONS_FILE.exists():
            return 0
        try:
            with open(OBSERVATIONS_FILE, "r", encoding="utf-8") as f:
                return sum(1 for _ in f)
        except Exception:
            return 0

    def _empty_trial_output(self) -> dict:
        return {
            "response": "",
            "tool_calls": 0,
            "token_count": 0,
            "elapsed_s": 0,
            "trace_records": [],
            "steps": [],
            "files_created": [],
            "file_contents": {},
        }

    # -- 评分 ------------------------------------------

    def _grade_trial(self, case: dict, trial_output: dict,
                      baseline: dict | None = None) -> dict:
        """对单次 Trial 执行全部评分器。"""
        grades = []

        # 1. 步骤评分 (LCS 对齐)
        if baseline:
            baseline_steps = [s.get("normalized", "") for s in baseline.get("steps", [])]
            trial_steps = [s["normalized"] for s in trial_output.get("steps", [])]
            grades.append(self.step_grader.grade(baseline_steps, trial_steps))
        else:
            grades.append({
                "grader": "StepGrader", "score": 10, "max_score": 10,
                "deduction": 0, "issues": ["no_baseline -- skipped"],
            })

        # 2. 效率评分
        if baseline:
            grades.append(self.eff_grader.grade(
                {"elapsed_s": baseline.get("elapsed_s", 0),
                 "token_count": baseline.get("token_count", 0),
                 "tool_calls": baseline.get("tool_calls", 0)},
                {"elapsed_s": trial_output.get("elapsed_s", 0),
                 "token_count": trial_output.get("token_count", 0),
                 "tool_calls": trial_output.get("tool_calls", 0)},
            ))
        else:
            grades.append({
                "grader": "EfficiencyGrader", "score": 10, "max_score": 10,
                "deduction": 0, "issues": ["no_baseline -- skipped"],
            })

        # 3. 结果评分 (确定性规则)
        expected = case.get("expected_behavior", case.get("expected", {}))
        result_grade = self.result_grader.grade(expected, trial_output)
        grades.append(result_grade)

        # 4. Rubric 评分 (LLM-as-Judge, 可选)
        if self.rubric_grader:
            rubric_grade = self.rubric_grader.grade(case, trial_output, baseline)
            grades.append(rubric_grade)

        # 关键判定: 检查是否有 critical 标记的规则失败
        critical_failure = False
        if expected.get("critical_checks"):
            for check in expected["critical_checks"]:
                if not self._eval_critical(check, trial_output):
                    critical_failure = True
                    break

        # Rubric 检测到的幻觉也视为 critical
        if self.rubric_grader:
            for g in grades:
                if g.get("grader") == "RubricGrader" and g.get("hallucination_detected"):
                    critical_failure = True
                    break

        return compute_trial_score(grades, critical_failure)

    def _eval_critical(self, check: dict, trial: dict) -> bool:
        """评估关键判定规则。"""
        ct = check.get("type", "")
        if ct == "result_matches_baseline":
            # 结果必须与基线一致
            return True  # Phase 1: 不做严格的结果匹配
        if ct == "no_hallucination":
            # 不编造不存在的内容
            forbidden = check.get("forbidden", [])
            response = trial.get("response", "").lower()
            return not any(kw.lower() in response for kw in forbidden)
        return True

    # -- 运行 ------------------------------------------

    def run(self) -> dict:
        """运行完整测评套件。"""
        suite_name = self.suite.get("name", self.suite_path.stem)
        cases = self.suite.get("cases", [])

        print(f"\n{'='*60}")
        print(f"Eval Harness -- {suite_name}")
        print(f"Cases: {len(cases)} | Trials: {self.trials} | "
              f"Threshold: {self.threshold}")
        print(f"Mode: {'BASELINE' if self.baseline_mode else 'EVALUATION'}")
        print(f"{'='*60}\n")

        for ci, case in enumerate(cases):
            case_id = case.get("id", f"case-{ci:03d}")
            case_name = case.get("name", case_id)
            print(f"[{ci+1}/{len(cases)}] {case_id}: {case_name}")

            baseline = self._load_baseline(case_id)
            if baseline is None:
                print(f"  [!] no baseline for {case_id} -- "
                      f"run with --baseline first")

            trial_scores = []
            trial_details = []

            for t in range(self.trials):
                if self.trials > 1:
                    print(f"  Trial {t+1}/{self.trials}...")

                trial_output = self._execute_case(case)

                # 基线模式: 保存并退出
                if self.baseline_mode and t == 0:
                    self._save_baseline(case_id, trial_output)
                    break

                trial_result = self._grade_trial(case, trial_output, baseline)
                trial_scores.append(trial_result["trial_score"])
                trial_details.append({
                    "trial_index": t,
                    "score": trial_result["trial_score"],
                    "status": trial_result["status"],
                    "grades": trial_result["grades"],
                })

                if self.trials > 1:
                    print(f"    score={trial_result['trial_score']} "
                          f"({trial_result['status']})")

            case_result = compute_case_score(trial_scores, self.threshold)
            case_result["case_id"] = case_id
            case_result["case_name"] = case_name
            case_result["trial_details"] = trial_details

            self.results.append(case_result)

            status_icon = "[PASS]" if case_result["all_pass"] else "[FAIL]"
            print(f"  => {status_icon} | case={case_result['case_score']} | "
                  f"trials={case_result['trial_scores']}\n")

        report = self._generate_report()
        self._save_report(report)
        self._print_summary(report)
        return report

    # -- 报告 ------------------------------------------

    def _generate_report(self) -> dict:
        """生成测评报告。"""
        cases = self.results
        n = len(cases)
        passed = sum(1 for c in cases if c["all_pass"])
        scores = [c["case_score"] for c in cases]
        avg = sum(scores) / n if n > 0 else 0

        return {
            "suite": self.suite.get("name", "unnamed"),
            "session_id": self.session_id,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "threshold": self.threshold,
            "trials_per_case": self.trials,
            "summary": {
                "total_cases": n,
                "passed": passed,
                "failed": n - passed,
                "pass_rate": f"{passed/n*100:.1f}%" if n > 0 else "N/A",
                "avg_score": round(avg, 1),
                "min_score": min(scores) if scores else 0,
                "max_score": max(scores) if scores else 0,
            },
            "cases": cases,
            "_cases_raw": self.suite.get("cases", []),
        }

    def _save_report(self, report: dict) -> Path:
        """保存 JSON + HTML 报告。"""
        suite_name = self.suite_path.stem
        out_dir = EVAL_DIR / suite_name
        out_dir.mkdir(parents=True, exist_ok=True)
        json_path = out_dir / f"report-{self.session_id}.json"
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        print(f"JSON report -> {json_path}")

        html_path = out_dir / f"report-{self.session_id}.html"
        generate_html_report(report, html_path)
        print(f"HTML report -> {html_path}")

        return json_path

    def _print_summary(self, report: dict) -> None:
        """打印摘要。"""
        s = report["summary"]
        print(f"\n{'='*60}")
        print(f"RESULTS: {report['suite']}")
        print(f"{'='*60}")
        print(f"  Pass rate:  {s['pass_rate']} ({s['passed']}/{s['total_cases']})")
        print(f"  Avg score:  {s['avg_score']}")
        print(f"  Range:      {s['min_score']} - {s['max_score']}")
        print(f"  Threshold:  {report['threshold']}")

        if s["failed"] > 0:
            print(f"\n  FAILURES:")
            for c in report["cases"]:
                if not c["all_pass"]:
                    print(f"    X {c['case_id']}: {c['case_name']} "
                          f"-> {c['case_score']}")

        print(f"{'='*60}\n")


# ======================================================
# CLI
# ======================================================

def main():
    import argparse
    parser = argparse.ArgumentParser(
        description="AI Agent/Skill Eval Harness")
    parser.add_argument("--suite", required=True,
                        help="测评用例集 JSON 文件路径")
    parser.add_argument("--trials", type=int, default=DEFAULT_TRIALS,
                        help=f"每用例执行轮数 (默认 {DEFAULT_TRIALS})")
    parser.add_argument("--threshold", type=int, default=DEFAULT_THRESHOLD,
                        help=f"达标线分数 (默认 {DEFAULT_THRESHOLD})")
    parser.add_argument("--baseline", action="store_true",
                        help="基线建立模式: 执行 1 次并保存为基线")
    parser.add_argument("--replay", type=str, default=None,
                        help="回放模式: 使用指定 session_id 的已有 Trace")
    parser.add_argument("--rubric", action="store_true",
                        help="启用 LLM-as-Judge 语义评分 (需 claude CLI)")
    args = parser.parse_args()

    harness = EvalHarness(
        suite_path=args.suite,
        trials=1 if args.baseline else args.trials,
        threshold=args.threshold,
        replay_session=args.replay,
        baseline_mode=args.baseline,
        rubric_mode=args.rubric,
    )
    harness.run()


if __name__ == "__main__":
    main()
