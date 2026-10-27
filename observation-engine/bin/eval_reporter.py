#!/usr/bin/env python3
"""HTML Report Generator -- 生成自包含测评报告。

参考腾讯 TPerf 全量测评报告布局:
  顶部汇总 -> 用例列表(可展开) -> 单用例评分明细 -> 模型对比
"""

import json
from datetime import datetime, timezone
from pathlib import Path


def _escape_html(text: str) -> str:
    return (text.replace("&", "&amp;")
                .replace("<", "&lt;")
                .replace(">", "&gt;")
                .replace('"', "&quot;"))


def _score_color(score: float | str, threshold: int = 80) -> str:
    if isinstance(score, str):
        try:
            score = float(score.rstrip("%"))
        except (ValueError, TypeError):
            return "#94a3b8"
    if score >= threshold:
        return "#22c55e"
    elif score >= threshold * 0.7:
        return "#f59e0b"
    else:
        return "#ef4444"


def _progress_bar(score: float, max_score: float = 100,
                   threshold: int = 80) -> str:
    pct = min(100, score / max_score * 100)
    color = _score_color(score, threshold)
    return (
        f'<div style="background:#e5e7eb;border-radius:4px;height:8px;'
        f'width:100%;margin:4px 0;">'
        f'<div style="background:{color};border-radius:4px;height:8px;'
        f'width:{pct:.0f}%;"></div></div>'
    )


def generate_html_report(report: dict, output_path: Path) -> Path:
    """生成自包含 HTML 测评报告。"""
    s = report["summary"]
    cases = report.get("cases", [])

    # 分数分布直方图数据
    score_bins = {"0-20": 0, "21-40": 0, "41-60": 0,
                  "61-80": 0, "81-100": 0}
    for c in cases:
        sc = c.get("case_score", 0)
        if sc <= 20: score_bins["0-20"] += 1
        elif sc <= 40: score_bins["21-40"] += 1
        elif sc <= 60: score_bins["41-60"] += 1
        elif sc <= 80: score_bins["61-80"] += 1
        else: score_bins["81-100"] += 1

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Eval Report — {_escape_html(report['suite'])}</title>
<style>
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
       background: #f8fafc; color: #1e293b; line-height: 1.6; padding: 24px; }}
.container {{ max-width: 1100px; margin: 0 auto; }}
h1 {{ font-size: 24px; margin-bottom: 4px; }}
h2 {{ font-size: 18px; margin: 24px 0 12px; color: #334155; }}
h3 {{ font-size: 14px; color: #64748b; margin-bottom: 20px; font-weight: 400; }}

/* Summary Cards */
.summary {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
            gap: 12px; margin-bottom: 24px; }}
.card {{ background: #fff; border-radius: 8px; padding: 16px 20px;
         box-shadow: 0 1px 3px rgba(0,0,0,.06); text-align: center; }}
.card .value {{ font-size: 28px; font-weight: 700; }}
.card .label {{ font-size: 12px; color: #64748b; margin-top: 4px;
                text-transform: uppercase; letter-spacing: .5px; }}

/* Case List */
.case {{ background: #fff; border-radius: 8px; margin-bottom: 10px;
         box-shadow: 0 1px 3px rgba(0,0,0,.06); overflow: hidden; }}
.case-header {{ display: flex; align-items: center; padding: 14px 20px;
                cursor: pointer; user-select: none; gap: 12px; }}
.case-header:hover {{ background: #f1f5f9; }}
.case-id {{ font-family: monospace; font-size: 13px; color: #64748b;
           min-width: 120px; }}
.case-name {{ flex: 1; font-weight: 500; font-size: 14px; }}
.case-score {{ font-weight: 700; font-size: 16px; min-width: 50px; text-align: right; }}
.case-status {{ font-size: 12px; padding: 2px 8px; border-radius: 10px;
                font-weight: 600; min-width: 56px; text-align: center; }}
.status-pass {{ background: #dcfce7; color: #16a34a; }}
.status-fail {{ background: #fef2f2; color: #dc2626; }}

.case-body {{ display: none; padding: 0 20px 20px; border-top: 1px solid #f1f5f9; }}
.case.open .case-body {{ display: block; }}

/* Trial Detail */
.trial {{ background: #f8fafc; border-radius: 6px; padding: 12px 16px;
          margin-bottom: 8px; }}
.trial-header {{ display: flex; justify-content: space-between;
                 align-items: center; margin-bottom: 8px; }}
.trial-id {{ font-size: 13px; font-weight: 600; color: #475569; }}
.trial-score {{ font-size: 18px; font-weight: 700; }}
.grade-row {{ display: flex; justify-content: space-between; align-items: center;
              padding: 4px 0; font-size: 13px; }}
.grade-name {{ color: #64748b; min-width: 140px; }}
.grade-bar {{ flex: 1; margin: 0 12px; }}
.grade-value {{ font-weight: 600; min-width: 60px; text-align: right; }}
.issues {{ font-size: 12px; color: #94a3b8; margin-top: 6px; }}

/* Histogram */
.histogram {{ display: flex; gap: 4px; align-items: flex-end; height: 100px;
              padding: 8px 0; }}
.hist-bar {{ flex: 1; text-align: center; }}
.hist-fill {{ border-radius: 4px 4px 0 0; min-height: 4px; transition: height .3s; }}
.hist-label {{ font-size: 10px; color: #94a3b8; margin-top: 4px; }}
.hist-count {{ font-size: 11px; font-weight: 600; color: #475569; }}

/* Footer */
.footer {{ text-align: center; color: #94a3b8; font-size: 12px;
           margin-top: 32px; padding-top: 16px; border-top: 1px solid #e2e8f0; }}

/* Collapse arrow */
.arrow {{ transition: transform .2s; color: #94a3b8; font-size: 12px; }}
.case.open .arrow {{ transform: rotate(90deg); }}

/* Badge */
.badge {{ display: inline-block; padding: 2px 8px; border-radius: 10px;
          font-size: 11px; font-weight: 600; margin-right: 4px; }}
.badge-trigger {{ background: #dbeafe; color: #2563eb; }}
.badge-logic {{ background: #fef3c7; color: #d97706; }}
.badge-output {{ background: #d1fae5; color: #059669; }}
.badge-error {{ background: #fee2e2; color: #dc2626; }}
.badge-boundary {{ background: #e0e7ff; color: #4f46e5; }}
</style>
</head>
<body>
<div class="container">

<h1>{_escape_html(report['suite'])} — Eval Report</h1>
<h3>Generated: {report.get('generated_at', '')[:19]} | Threshold: {report['threshold']} |
Trials per case: {report['trials_per_case']}</h3>

<div class="summary">
  <div class="card">
    <div class="value" style="color:{_score_color(s['pass_rate'].rstrip('%').replace('.0',''))}">{s['pass_rate']}</div>
    <div class="label">Pass Rate ({s['passed']}/{s['total_cases']})</div>
  </div>
  <div class="card">
    <div class="value" style="color:{_score_color(s['avg_score'], 80)}">{s['avg_score']}</div>
    <div class="label">Avg Score</div>
  </div>
  <div class="card">
    <div class="value">{s['min_score']} - {s['max_score']}</div>
    <div class="label">Score Range</div>
  </div>
  <div class="card">
    <div class="value">{s['total_cases']}</div>
    <div class="label">Total Cases</div>
  </div>
</div>

<h2>Score Distribution</h2>
<div class="card" style="padding:16px 20px;">
  <div class="histogram">
"""

    max_bin = max(score_bins.values()) or 1
    for label, count in score_bins.items():
        h_pct = count / max_bin * 100
        color = "#ef4444" if label in ("0-20", "21-40") else \
                "#f59e0b" if label in ("41-60",) else "#22c55e"
        html += f"""    <div class="hist-bar">
      <div class="hist-count">{count}</div>
      <div class="hist-fill" style="height:{max(4, h_pct)}px;background:{color};"></div>
      <div class="hist-label">{label}</div>
    </div>
"""

    html += """  </div>
</div>

<h2>Cases</h2>
"""

    scenario_class = {
        "trigger": "badge-trigger",
        "core_logic": "badge-logic",
        "output_quality": "badge-output",
        "error_handling": "badge-error",
        "boundary": "badge-boundary",
    }

    for ci, case in enumerate(cases):
        cid = _escape_html(case.get("case_id", f"case-{ci}"))
        cname = _escape_html(case.get("case_name", cid))
        cscore = case.get("case_score", 0)
        all_pass = case.get("all_pass", False)
        trial_scores = case.get("trial_scores", [])
        trial_details = case.get("trial_details", [])

        # 查找 scenario
        scenario = ""
        for orig_case in report.get("_cases_raw", []):
            if orig_case.get("id") == case.get("case_id"):
                scenario = orig_case.get("scenario", "")
                break

        status_class = "status-pass" if all_pass else "status-fail"
        status_text = "PASS" if all_pass else "FAIL"
        score_color = _score_color(cscore, report.get("threshold", 80))
        badge_cls = scenario_class.get(scenario, "")

        html += f"""<div class="case" onclick="this.classList.toggle('open')">
  <div class="case-header">
    <span class="arrow">&#9654;</span>
    <span class="case-id">{cid}</span>
    <span class="case-name">{cname}</span>
    {f'<span class="badge {badge_cls}">{scenario}</span>' if scenario else ''}
    <span class="{status_class} case-status">{status_text}</span>
    <span class="case-score" style="color:{score_color}">{cscore}</span>
  </div>
  <div class="case-body">
    <div style="margin-bottom:10px;">
      <strong>Trial Scores:</strong> {', '.join(str(s) for s in trial_scores)}
    </div>
"""

        for td in trial_details:
            ti = td.get("trial_index", 0)
            tscore = td["score"]
            tstatus = td.get("status", "?")
            grades = td.get("grades", [])

            html += f"""    <div class="trial">
      <div class="trial-header">
        <span class="trial-id">Trial {ti + 1}</span>
        <span class="trial-score" style="color:{_score_color(tscore, report.get('threshold', 80))}">
          {tscore} <span style="font-size:12px;color:#94a3b8;">({tstatus})</span>
        </span>
      </div>
"""
            for g in grades:
                gname = g.get("grader", "Unknown")
                gscore = g.get("score", 0)
                gmax = g.get("max_score", 10)
                gded = g.get("deduction", 0)
                gissues = g.get("issues", [])

                html += f"""      <div class="grade-row">
        <span class="grade-name">{gname}</span>
        <span class="grade-bar">{_progress_bar(gscore, gmax, report.get('threshold', 80))}</span>
        <span class="grade-value">{gscore}/{gmax} <span style="font-size:11px;color:#94a3b8;">(-{gded})</span></span>
      </div>
"""
                if gissues:
                    issues_str = ", ".join(gissues[:5])
                    html += f"""      <div class="issues">Issues: {_escape_html(issues_str)}</div>
"""

            # Rubric 额外维度
            for g in grades:
                if g.get("grader") == "RubricGrader":
                    ps = g.get("process_score", 0)
                    rs = g.get("result_score", 0)
                    fp = g.get("is_false_positive", False)
                    hal = g.get("hallucination_detected", False)
                    html += f"""      <div class="issues">
        Process: {ps}/100 | Result: {rs}/100 | False Positive: {fp} | Hallucination: {hal}
      </div>
"""

            html += "    </div>\n"

        html += "  </div>\n</div>\n"

    html += f"""<div class="footer">
  Eval Harness v1.0 | Report generated {datetime.now(timezone.utc).isoformat()[:19]}Z |
  {s['total_cases']} cases | {report['trials_per_case']} trials/case
</div>

</div>
<script>
// Click handler for expand/collapse
document.querySelectorAll('.case-header').forEach(h => {{
  h.addEventListener('click', function(e) {{
    this.parentElement.classList.toggle('open');
  }});
}});
</script>
</body>
</html>"""

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)

    return output_path


def add_html_report(json_report: dict, json_path: Path) -> Path:
    """便捷函数: 从 JSON 报告路径生成 HTML 报告。"""
    html_path = json_path.with_suffix(".html")
    return generate_html_report(json_report, html_path)
