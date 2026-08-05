---
title: 让 Claude Code 拥有自我进化和记忆系统
source: 得物技术
author: 晴天
date: 2026-06-10
url: https://mp.weixin.qq.com/s/PGT49KORSVZYpJxykWnwOw
---

# 让 Claude Code 拥有自我进化和记忆系统｜得物技术

## 架构总览

三个子系统协作形成自学习闭环：

```
工具调用 → 行为观测层 → 模式提炼层 → 记忆注入层 → 影响下次会话
```

## 行为观测层 (Observation Engine)

### Hook 机制

- PreToolUse: matcher="Bash" — 只捕获 Bash 意图
- PostToolUse: matcher=".*" — 100% 后置采集
- Stop: 会话结束时触发分析和提炼

### Observation 数据格式

```json
{
  "session_id": "abc123",
  "ts": "2026-05-26T10:30:00Z",
  "phase": "post",
  "tool": "Edit",
  "input": { "file_path": "/src/app.ts", ... },
  "bash_desc": null
}
```

### 数据分片

`observations_rotate.py` 在文件超 5MB 或 8000 行时自动按月归档，主文件保留最近 30 天。

## 模式提炼层 (Instinct Engine)

双路径并行分析：

### 路径 A：统计模式检测

5 种硬编码检测器，识别高频工具调用序列：

- 首次发现: confidence = 0.5
- 重复验证: confidence += 0.05（上限 0.9）
- 长期未触发: confidence -= 0.05（低于 0.55 标记 deprecated）

### 路径 B：AI 语义分析

调用本地 Claude CLI（`claude --print --model claude-haiku-4-5-20251001 -p`）进行语义理解，返回 JSON 数组。

### Instinct 数据模型

存储为独立 Markdown 文件，位置: `~/.claude/homunculus/instincts/personal/`

```yaml
---
id: read-before-edit-pattern
trigger: "when about to edit a file that hasn't been read in this session"
confidence: 0.78
domain: workflow
source: session-observation
deprecated: false
observed_at: "2026-05-20"
---
```

### 语义去重 (auto-evolve.py)

Jaccard 相似度 + Union-Find 合并，sim_threshold=0.5。
"只提取英文关键词"——跨语言（中/英）通过技术词汇识别同一意图。

### Domain 聚合与规则注入

去重后按 domain 分组（每组 >= 2 条），生成 `evolved-*.md`，最终合并为 `~/.claude/rules/auto-evolved.md`。Claude Code 启动时自动加载 `~/.claude/rules/` 下所有 `.md` 文件。

## 记忆注入层 (Memory Engine)

### 记忆类型体系

| 类型 | 用途 | TTL |
|---|---|---|
| feedback | 用户偏好与习惯 | 90天 |
| project | 项目上下文、技术栈 | 90天 |
| user | 用户画像 | 60天 |
| concept | 技术概念 | 90天 |
| bug | 已解决的 Bug | 90天 |
| decision | 技术决策 | 90天 |

### 记忆文件格式

每个 Markdown 文件含 YAML frontmatter:

```yaml
---
name: feedback-commit-timing
description: 改完代码不主动提交，等用户验证确认后再 commit/push
metadata:
  type: feedback
---
```

### 记忆召回链路（四阶段）

1. **SessionStart Hook** → 触发 `inject_memory_context.py`
2. **查询构造**：以 `$PWD`（项目名）+ 最近 3 条 git commit message 为输入
3. **向量检索**：余弦相似度 → Top-5 记忆
4. **上下文注入**：结构化 Markdown 注入系统提示

```markdown
# 🧠 项目记忆（自动注入，请优先参考）

[feedback] 改完代码不主动提交...
> Why: 自动提交会打断验证节奏，回滚成本高

[project] 当前项目使用 Vitest 做单元测试...
> How to apply: 新功能先在 tests/ 写测试用例，再实现
```

### Embedding 技术选型

- 本地 nomic-embed-text + qdrant 向量库
- 推理速度 ~10ms/条（M 系列芯片）
- 原因：Claude 无独立 Embedding API + 隐私保护

### 向量写入流程

```python
# 构造嵌入文本 = 标题 + 描述 + 正文摘要(200字)
text = f"{memory['name']}{memory['description']}{memory['body'][:200]}"
vector = embed_local(text)  # nomic-embed-text
qdrant_client.upsert(collection_name="memories", points=[...])
```

## 数据流完整路径

```
1. 工具调用触发
2. PreToolUse Hook → observe.sh → observations.jsonl
3. 工具执行
4. PostToolUse Hook → observe.sh → observations.jsonl
5. 会话结束，Stop Hook 触发
6. auto-analyze-instincts.py (统计 + AI 语义)
7. 写入 ~/.claude/homunculus/instincts/personal/*.md
8. auto-evolve.py (去重 → 聚合 → 写入 rules/auto-evolved.md)
9. 下次会话启动: 自动加载 rules/ + SessionStart → inject_memory_context.py
```

## 防膨胀设计

| 层级 | 策略 |
|---|---|
| Observations | 超 5MB/8000 行按月归档 |
| Instinct | 低置信度 (<0.55) 标记 deprecated |
| Memory raw | 按类型 TTL (60-90天) |
| MEMORY.md | 超 160 行按优先级裁剪 |
| auto-evolved.md | 每次覆盖重写 |
| 去重 | Jaccard 相似度合并 |

## 核心设计原则

- **原子性优先**：先积累原子规则，同类足够多再聚合
- **隐私边界**：Observations 只保本地，export 只分享 Instinct 规则
- **置信度演化**：反复观测强化，长期不触发衰减（有遗忘能力）
- **Hook 优先于 Skill**：确定性触发保证 100% 采集率

## 实际效果

- 上下文冷启动: 10 分钟 → 30 秒
- Token 消耗: 降低约 78%
- 错误重复率: 下降 80%
- 知识复利: 随时间指数增长
