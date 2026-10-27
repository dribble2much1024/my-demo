#!/usr/bin/env python3
"""Eval System — 历史数据导出工具。

将当前 agent 的测评历史数据打包导出为压缩归档，便于迁移到新 agent。

导出内容:
  - observations/     (工具调用追踪日志)
  - eval_results/     (测评报告 JSON + HTML)
  - baselines/        (基线快照)
  - instincts/        (退化检测 Instinct .md)

用法:
  python export_history.py                           # 导出到当前目录
  python export_history.py --output /tmp/eval-backup  # 指定输出目录
  python export_history.py --archive                  # 打包为 .zip
"""

import json
import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path


def _home() -> Path:
    return Path.home()


def _claude_dir() -> Path:
    return _home() / ".claude"


def _find_observations() -> Path | None:
    """定位 observations 数据源。"""
    # 优先: ~/.claude/observations/observations.jsonl
    candidates = [
        _claude_dir() / "observations" / "observations.jsonl",
        _claude_dir() / "observations.jsonl",
        _home() / "observations.jsonl",
    ]
    for c in candidates:
        if c.exists():
            return c
    return None


def _find_eval_results() -> Path | None:
    """定位测评结果目录。"""
    candidates = [
        _claude_dir() / "eval-results",
        _claude_dir() / "eval_results",
    ]
    for c in candidates:
        if c.exists():
            return c
    return None


def _find_instincts() -> Path | None:
    """定位 Instinct 文件。"""
    p = _claude_dir() / "homunculus" / "instincts"
    if p.exists():
        return p
    return None


def export_to_dir(output_dir: Path) -> dict:
    """导出所有历史数据到指定目录。"""
    output_dir.mkdir(parents=True, exist_ok=True)
    results = {}

    # 1. observations
    obs = _find_observations()
    if obs:
        if obs.is_file():
            dst = output_dir / "observations" / obs.name
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(obs, dst)
            size = dst.stat().st_size
            results["observations"] = f"{size / 1024:.1f} KB"
        else:
            dst = output_dir / "observations"
            if dst.exists():
                shutil.rmtree(dst)
            shutil.copytree(obs, dst)
            count = len(list(dst.rglob("*")))
            results["observations"] = f"{count} files"
    else:
        results["observations"] = "not_found"

    # 2. eval_results
    evals = _find_eval_results()
    if evals:
        dst = output_dir / "eval_results"
        if dst.exists():
            shutil.rmtree(dst)
        shutil.copytree(evals, dst)
        count = len(list(dst.rglob("*.json"))) + len(list(dst.rglob("*.html")))
        results["eval_results"] = f"{count} files"
    else:
        results["eval_results"] = "not_found"

    # 3. instincts
    instincts = _find_instincts()
    if instincts:
        dst = output_dir / "instincts"
        if dst.exists():
            shutil.rmtree(dst)
        shutil.copytree(instincts, dst)
        count = len(list(dst.rglob("*.md")))
        results["instincts"] = f"{count} files"
    else:
        results["instincts"] = "not_found"

    # 4. 生成 manifest.json
    manifest = {
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "hostname": os.environ.get("COMPUTERNAME", os.environ.get("HOSTNAME", "unknown")),
        "platform": sys.platform,
        "contents": results,
    }
    manifest_path = output_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False),
        encoding="utf-8"
    )

    return results


def archive_dir(source_dir: Path, archive_path: Path) -> Path:
    """将目录打包为 .zip。"""
    shutil.make_archive(
        str(archive_path.with_suffix("")),
        "zip",
        source_dir,
    )
    return archive_path.with_suffix(".zip")


def main():
    import argparse
    parser = argparse.ArgumentParser(
        description="Eval System — 历史数据导出"
    )
    parser.add_argument("--output", type=str, default=".",
                        help="输出目录 (默认: 当前目录)")
    parser.add_argument("--archive", action="store_true",
                        help="打包为 .zip 压缩归档")
    args = parser.parse_args()

    output_base = Path(args.output).resolve()
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    export_dir = output_base / f"eval-history-{timestamp}"

    print(f"[export] 导出到: {export_dir}")
    results = export_to_dir(export_dir)

    print("\n导出内容:")
    for item, size in results.items():
        print(f"  {item}: {size}")

    manifest_path = export_dir / "manifest.json"
    print(f"\nManifest: {manifest_path}")

    if args.archive:
        archive_path = output_base / f"eval-history-{timestamp}.zip"
        final = archive_dir(export_dir, archive_path)
        print(f"Archive: {final} ({final.stat().st_size / 1024:.0f} KB)")


if __name__ == "__main__":
    main()
