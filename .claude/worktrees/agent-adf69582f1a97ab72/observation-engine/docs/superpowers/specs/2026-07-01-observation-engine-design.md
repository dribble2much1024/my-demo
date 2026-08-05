# Observation Engine — 行为观测层设计

## Overview

为 Claude Code 构建持久化记忆系统的第一步：观测层。
通过 Hook 机制 100% 捕获每次工具调用的输入输出，写入 JSONL 观测流，作为后续提炼层和记忆层的数据基础。

## Architecture

```
Claude Code 工具调用
       ↓
  PreToolUse Hook → observe.py pre  → observations.jsonl
       ↓
  工具执行
       ↓
  PostToolUse Hook → observe.py post → observations.jsonl
       ↓
  [会话结束]
       ↓
  Stop Hook → observations_rotate.py（检查归档）
```

## Directory Structure

```
~/.claude/
├── bin/
│   ├── observe.py              # 观测采集（Hook 入口）
│   └── observations_rotate.py  # 日志轮转 + 归档
├── observations/
│   ├── observations.jsonl      # 活跃日志（<= 30 天）
│   └── observations-YYYY-MM.jsonl  # 按月归档
└── settings.json               # Hook 配置
```

## Components

### observe.py

- **输入：** `pre` 或 `post` 参数；Hook JSON 从 stdin 读取
- **PreToolUse：** 记录 tool_name、tool_input 完整参数，phase=pre
- **PostToolUse：** 记录 tool_name、tool_input、output_summary（截断至 2000 字符），phase=post
- **Session ID：** 优先读 `$CLAUDE_SESSION_ID` 环境变量，fallback 生成 UUID
- **依赖：** 零外部依赖，纯 Python 标准库
- **JSONL 格式：**

```json
{
  "session_id": "<uuid>",
  "ts": "<ISO 8601 with timezone>",
  "phase": "pre|post",
  "tool": "Bash|Edit|Write|Read|...",
  "input": { ... },
  "output_summary": "<post only, max 2000 chars>"
}
```

### observations_rotate.py

- **触发：** Stop Hook，每次会话结束后检查
- **阈值：** 文件 > 5MB 或 > 8000 行
- **归档策略：** 提取 30 天前的条目，按月份分组写入 `observations-YYYY-MM.jsonl`
- **主文件：** 仅保留最近 30 天数据
- **未超阈值：** 跳过，无操作

### Hook Configuration (settings.json)

```json
{
  "hooks": {
    "PreToolUse": [{
      "matcher": "Bash",
      "hooks": [{
        "type": "command",
        "command": "python3 ~/.claude/bin/observe.py pre"
      }]
    }],
    "PostToolUse": [{
      "matcher": ".*",
      "hooks": [{
        "type": "command",
        "command": "python3 ~/.claude/bin/observe.py post"
      }]
    }],
    "Stop": [{
      "hooks": [{
        "type": "command",
        "command": "python3 ~/.claude/bin/observations_rotate.py"
      }]
    }]
  }
}
```

## Error Handling

- stdin 为空或 JSON 解析失败 → 静默写错误日志到 `~/.claude/observations/errors.log`，不阻塞 Hook
- 写入失败（磁盘满等）→ 同上，绝不抛异常
- Python 不可用 → 前置条件，settings.json 确保 `python3` 路径正确

## Exclusions

- 不做实时分析（留给后续的 Instinct Engine）
- 不做数据可视化
- 不做内存/向量/提炼逻辑
- 不依赖第三方 pip 包
