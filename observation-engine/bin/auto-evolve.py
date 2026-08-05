#!/usr/bin/env python3
"""Instinct Evolution — 去重、Domain 聚合、规则注入。

由 Stop Hook 在 auto-analyze-instincts.py 之后触发。

流水线：
  1. 加载 instinct .md 文件，解析 frontmatter
  2. 过滤：confidence >= 0.7
  3. Jaccard 语义去重（Union-Find），阈值 0.5
  4. 同 domain ≥ 2 条 → evolved-{domain}.md
  5. 合并为 ~/.claude/rules/auto-evolved.md（每次覆盖重写）
"""

import json
import re
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

# ── 路径 ──────────────────────────────────────────────

INSTINCTS_DIR = Path.home() / ".claude" / "homunculus" / "instincts" / "personal"
EVOLVED_DIR = Path.home() / ".claude" / "homunculus" / "evolved"
RULES_FILE = Path.home() / ".claude" / "rules" / "auto-evolved.md"
ERROR_LOG = Path.home() / ".claude" / "observations" / "errors.log"

# ── 日志 ──────────────────────────────────────────────

def log_error(msg: str) -> None:
    try:
        ts = datetime.now(timezone.utc).isoformat()
        with open(ERROR_LOG, "a", encoding="utf-8") as f:
            f.write(f"[{ts}] [evolve] {msg}\n")
    except Exception:
        pass

# ── Frontmatter 解析 ──────────────────────────────────

def parse_frontmatter(content: str) -> tuple[dict, str]:
    """解析 YAML frontmatter（--- 分隔），纯 stdlib。"""
    lines = content.split("\n")
    if not lines or lines[0].strip() != "---":
        return {}, content

    end_idx = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end_idx = i
            break
    if end_idx is None:
        return {}, content

    metadata = {}
    for line in lines[1:end_idx]:
        m = re.match(r'^(\w[\w_-]*)\s*:\s*(.+)$', line)
        if m:
            key = m.group(1)
            val = m.group(2).strip().strip('"').strip("'")
            if val in ("true", "false"):
                val = val == "true"
            elif re.match(r'^-?\d+\.\d+$', val):
                val = float(val)
            elif re.match(r'^-?\d+$', val):
                val = int(val)
            metadata[key] = val

    body = "\n".join(lines[end_idx + 1:])
    return metadata, body

# ── 加载 instincts ────────────────────────────────────

def load_instincts() -> list[dict]:
    """加载所有 instinct .md 文件，返回 dict 列表。"""
    if not INSTINCTS_DIR.exists():
        return []
    instincts = []
    for md_file in sorted(INSTINCTS_DIR.glob("*.md")):
        try:
            content = md_file.read_text(encoding="utf-8")
            meta, body = parse_frontmatter(content)
            if not meta.get("id"):
                continue
            meta["body"] = body or ""
            instincts.append(meta)
        except Exception:
            continue
    return instincts

# ── Jaccard 去重 ──────────────────────────────────────

def extract_keywords(instinct: dict) -> set[str]:
    """提取英文关键词：trigger + action + body 中的英文单词。"""
    text = " ".join([
        str(instinct.get("trigger", "")),
        str(instinct.get("action", "")),
        str(instinct.get("body", ""))[:200],
    ])
    return set(re.findall(r'[a-zA-Z]{3,}', text.lower()))


def jaccard_similarity(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def dedup_instincts(instincts: list[dict], threshold: float = 0.5) -> list[list[dict]]:
    """Jaccard 去重 + Union-Find 合并。返回合并后的 instinct 分组。"""
    n = len(instincts)
    if n <= 1:
        return [instincts] if n == 1 else []

    # Union-Find
    parent = list(range(n))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(x: int, y: int) -> None:
        px, py = find(x), find(y)
        if px != py:
            parent[px] = py

    keywords = [extract_keywords(inst) for inst in instincts]

    for i in range(n):
        for j in range(i + 1, n):
            sim = jaccard_similarity(keywords[i], keywords[j])
            if sim >= threshold:
                union(i, j)

    groups = defaultdict(list)
    for i in range(n):
        groups[find(i)].append(instincts[i])
    return list(groups.values())

# ── Domain 聚合 ───────────────────────────────────────

def merge_cluster(domain: str, cluster: list[dict]) -> dict:
    """合并一组相似 instinct，取最高置信度的为代表。"""
    best = max(cluster, key=lambda x: float(x.get("confidence", 0)))
    triggers = list(dict.fromkeys(inst.get("trigger", "") for inst in cluster))  # dedup + ordered
    actions = list(dict.fromkeys(inst.get("action", "") for inst in cluster))
    all_ids = [inst.get("id") for inst in cluster if inst.get("id")]

    return {
        "id": f"evolved-{domain}",
        "domain": domain,
        "trigger": triggers[0] if len(triggers) == 1 else " | ".join(triggers[:3]),
        "action": actions[0] if len(actions) == 1 else " | ".join(actions[:3]),
        "confidence": max(float(inst.get("confidence", 0)) for inst in cluster),
        "source": "auto-evolved",
        "merged_from": all_ids,
        "body": best.get("body", ""),
    }


def aggregate_by_domain(clusters: list[list[dict]]) -> list[dict]:
    """按 domain 分组，>= 2 条才生成 evolved rule。"""
    domain_groups = defaultdict(list)
    for cluster in clusters:
        domains = [inst.get("domain", "general") for inst in cluster]
        domain = max(set(domains), key=domains.count)
        domain_groups[domain].extend(cluster)

    evolved = []
    for domain, instincts in domain_groups.items():
        if len(instincts) >= 2:
            evolved.append(merge_cluster(domain, instincts))
    return evolved

# ── 写入 evolved-{domain}.md ─────────────────────────

def write_evolved_domain(rule: dict) -> None:
    """写入 evolved-{domain}.md 文件。"""
    EVOLVED_DIR.mkdir(parents=True, exist_ok=True)
    file_path = EVOLVED_DIR / f"evolved-{rule['domain']}.md"

    now = datetime.now(timezone.utc).isoformat()
    merged = rule.get("merged_from", [])

    content = (
        f"---\n"
        f"id: {rule['id']}\n"
        f"domain: {rule['domain']}\n"
        f'trigger: "{rule.get("trigger", "")}"\n'
        f'action: "{rule.get("action", "")}"\n'
        f"confidence: {rule['confidence']:.2f}\n"
        f"source: auto-evolved\n"
        f"merged_from: {json.dumps(merged, ensure_ascii=False)}\n"
        f'evolved_at: "{now}"\n'
        f"---\n"
        f"\n"
        f"# Evolved Rule: {rule['domain']}\n\n"
        f"**When:** {rule.get('trigger', '')}\n\n"
        f"**Then:** {rule.get('action', '')}\n\n"
        f"**Confidence:** {rule['confidence']:.2f}\n\n"
        f"**Evolved from:** {', '.join(merged) if merged else 'N/A'}\n"
    )

    try:
        file_path.write_text(content, encoding="utf-8")
    except Exception as e:
        log_error(f"write evolved domain error: {e}")

# ── 写入 auto-evolved.md ─────────────────────────────

def write_auto_evolved(rules: list[dict]) -> None:
    """将聚合后的规则写入 auto-evolved.md（每次覆盖重写）。"""
    rules_dir = RULES_FILE.parent
    rules_dir.mkdir(parents=True, exist_ok=True)

    now = datetime.now(timezone.utc).isoformat()
    lines = [
        "# Auto-Evolved Rules",
        "",
        f"> Last updated: {now}",
        f"> Total rules: {len(rules)}",
        "",
        "These rules are automatically generated from observed behavior patterns.",
        "They are overwritten each session. Do not edit manually.",
        "",
        "---",
        "",
    ]

    for rule in sorted(rules, key=lambda x: x.get("domain", "")):
        lines.extend([
            f"## {rule.get('id', 'unknown')}",
            "",
            f"- **Domain:** {rule.get('domain', 'general')}",
            f"- **Confidence:** {rule.get('confidence', 0):.2f}",
            f"- **When:** {rule.get('trigger', '')}",
            f"- **Then:** {rule.get('action', '')}",
        ])
        merged = rule.get("merged_from")
        if merged:
            lines.append(f"- **Evolved from:** {', '.join(merged)}")
        lines.append("")

    try:
        RULES_FILE.write_text("\n".join(lines), encoding="utf-8")
    except Exception as e:
        log_error(f"write auto-evolved.md error: {e}")

# ══════════════════════════════════════════════════════
# Main
# ══════════════════════════════════════════════════════

def main() -> None:
    try:
        instincts = load_instincts()
        if not instincts:
            return

        # 过滤高置信度
        high_confidence = [
            inst for inst in instincts
            if not inst.get("deprecated", False)
            and float(inst.get("confidence", 0)) >= 0.7
        ]

        if not high_confidence:
            # 没有高置信度规则，清空 auto-evolved.md
            write_auto_evolved([])
            return

        # Jaccard 去重
        clusters = dedup_instincts(high_confidence)
        if not clusters:
            write_auto_evolved([])
            return

        # Domain 聚合
        evolved = aggregate_by_domain(clusters)

        if not evolved:
            write_auto_evolved([])
            return

        # 逐 domain 写 evolved-*.md
        for rule in evolved:
            write_evolved_domain(rule)

        # 写 auto-evolved.md
        write_auto_evolved(evolved)

    except Exception as e:
        log_error(f"auto-evolve error: {e}")


if __name__ == "__main__":
    main()
