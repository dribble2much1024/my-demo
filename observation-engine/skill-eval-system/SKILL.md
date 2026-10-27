---
name: eval-system
description: Use when deploying the Agent evaluation harness (eval_harness + CI gate + instinct detectors + badcase auto-discovery) to a new agent, or when the user asks to install/迁移/部署 测评系统
---

# Eval System — Agent 测评系统

一键安装的 AI Agent 测评框架。包含确定性评分、LLM-as-Judge、CI 门禁、退化检测、BadCase 自动发现五层体系。

## Usage

在目标设备上：

```bash
# 1. 复制整个 skill 目录到目标设备
scp -r observation-engine/skill-eval-system new-device:/tmp/

# 2. 运行安装脚本
python3 /tmp/skill-eval-system/install.py

# 3. 带历史数据迁移
python3 /tmp/skill-eval-system/install.py --with-history /path/to/old/observation-engine

# Done. 下次 Claude Code session 结束时自动触发测评。
```

选项：
- `--dry-run` — 预览所有操作，不写入文件
- `--force` — 覆盖已有脚本（默认：跳过）
- `--with-history <路径>` — 迁移历史数据（observations.jsonl、eval_results/、baselines/、instincts/）
- `--skill-dir <路径>` — 指定 skill 源码目录（默认为脚本同目录）

## What Gets Installed

| 路径 | 组件 |
|---|---|
| `~/.claude/bin/eval_harness.py` | 测评编排器 — 加载用例、执行评分、生成报告 |
| `~/.claude/bin/eval_graders.py` | 确定性评分器 — Step/Efficiency/Result 三维度 |
| `~/.claude/bin/eval_rubric.py` | LLM-as-Judge — RubricGrader 语义评分 |
| `~/.claude/bin/eval_reporter.py` | HTML 报告生成器 — 自包含仪表盘 |
| `~/.claude/bin/eval_ci.py` | CI 门禁 — 快速关键用例检查 |
| `~/.claude/bin/eval_badcase.py` | BadCase 发现 — 失败用例自动转化 |
| `~/.claude/bin/eval_instinct.py` | 退化检测 — 得分波动/成本膨胀/失败聚类 |
| `~/.claude/eval_cases/` | 用例集目录 — sample_suite.json + badcase_capability.json |
| `~/.claude/settings.json` | Hook 配置（合并 Stop hook，不覆盖） |

## Architecture

```
observations.jsonl (Hook 自动捕获)
        │
        ▼
eval_harness.py ──── 加载用例 + 解析 Trace + 执行评分
        │
        ├─► eval_graders.py  (Step / Efficiency / Result)
        ├─► eval_rubric.py   (LLM-as-Judge)
        └─► eval_reporter.py (HTML Report)
        │
        ▼
eval_results/  ──── JSON + HTML 报告
        │
        ├─► eval_ci.py       (CI 门禁, Stop hook 触发)
        ├─► eval_badcase.py  (失败→BadCase 转化)
        └─► eval_instinct.py (退化模式检测 → Instinct .md)
                │
                ▼
        ~/.claude/homunculus/instincts/personal/
                │
                ▼
        auto-evolve.py (聚合 → auto-evolved.md)
```

## 快速命令

```bash
# 运行完整测评
python3 ~/.claude/bin/eval_harness.py --suite ~/.claude/eval-cases/sample_suite.json

# 启用 Rubric (LLM-as-Judge)
python3 ~/.claude/bin/eval_harness.py --suite ... --rubric

# Replay 模式 (基于已有 observations.jsonl)
python3 ~/.claude/bin/eval_harness.py --replay

# CI 快速检查
python3 ~/.claude/bin/eval_ci.py --quick

# 退化检测
python3 ~/.claude/bin/eval_instinct.py

# BadCase 扫描
python3 ~/.claude/bin/eval_badcase.py
```

## 用例格式

```json
{
  "id": "trigger-pos-01",
  "name": "正向触发: 读取文件分析",
  "description": "验证 agent 能正确触发文件读取操作",
  "scenario": "trigger",
  "prompt": "请读取 observation-engine 目录下的观察数据并分析最近的工具调用模式",
  "expected_behavior": {
    "response_contains": ["observation", "JSONL", "session_id"],
    "max_tool_calls": 8,
    "required_tools": ["Read", "Grep"]
  },
  "rubric": {
    "observation_points": ["推理过程是否清晰", "分析是否具体"]
  }
}
```

## 依赖

- Python 3.10+（标准库，无第三方依赖）
- Claude CLI（仅 RubricGrader 需要 `claude` 命令）

## 平台适配

| OS | Python 命令 (hooks 中) |
|---|---|
| Windows | `py` |
| macOS / Linux | `python3` |
