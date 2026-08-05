#!/usr/bin/env python3
"""Observation Rotate — 在 JSONL 超阈值时按月归档旧数据，主文件保留最近 30 天。

由 Stop Hook 在每次会话结束时触发。
"""

import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

OBSERVATIONS_DIR = Path.home() / ".claude" / "observations"
OBSERVATIONS_FILE = OBSERVATIONS_DIR / "observations.jsonl"
MAX_SIZE_BYTES = 5 * 1024 * 1024  # 5MB
MAX_LINES = 8000
RETENTION_DAYS = 30


def should_rotate() -> bool:
    """检查是否需要轮转。"""
    if not OBSERVATIONS_FILE.exists():
        return False

    file_size = OBSERVATIONS_FILE.stat().st_size
    if file_size > MAX_SIZE_BYTES:
        return True

    line_count = 0
    with open(OBSERVATIONS_FILE, "r", encoding="utf-8") as f:
        for _ in f:
            line_count += 1
            if line_count > MAX_LINES:
                return True
    return False


def parse_ts(record: dict) -> datetime | None:
    """从记录中提取时间戳。"""
    ts = record.get("ts", "")
    try:
        ts = ts.replace("Z", "+00:00")
        return datetime.fromisoformat(ts)
    except (ValueError, TypeError):
        return None


def rotate() -> None:
    """将 30 天前的记录按月归档，主文件只保留最近 30 天。"""
    if not OBSERVATIONS_FILE.exists():
        return

    cutoff = datetime.now(timezone.utc) - timedelta(days=RETENTION_DAYS)
    recent: list[str] = []
    archive_buckets: dict[str, list[str]] = {}

    with open(OBSERVATIONS_FILE, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
                ts = parse_ts(record)
                if ts is None or ts < cutoff:
                    month_key = (
                        ts.strftime("%Y-%m")
                        if ts
                        else datetime.now(timezone.utc).strftime("%Y-%m")
                    )
                    archive_buckets.setdefault(month_key, []).append(line)
                else:
                    recent.append(line)
            except json.JSONDecodeError:
                recent.append(line)

    for month_key, lines in archive_buckets.items():
        archive_file = OBSERVATIONS_DIR / f"observations-{month_key}.jsonl"
        with open(archive_file, "a", encoding="utf-8") as f:
            for line in lines:
                f.write(line + "\n")

    with open(OBSERVATIONS_FILE, "w", encoding="utf-8") as f:
        for line in recent:
            f.write(line + "\n")


def main() -> None:
    try:
        OBSERVATIONS_DIR.mkdir(parents=True, exist_ok=True)
        if should_rotate():
            rotate()
    except Exception:
        pass


if __name__ == "__main__":
    main()
