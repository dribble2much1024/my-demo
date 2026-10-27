#!/usr/bin/env python3
"""Eval System — 历史数据导入工具。

从导出目录或归档恢复测评历史数据到当前 agent。

用法:
  python import_history.py /path/to/eval-history-20260811/     # 从目录导入
  python import_history.py /path/to/eval-history-20260811.zip  # 从归档导入
  python import_history.py --dry-run /path/to/archive          # 预览
  python import_history.py --merge /path/to/archive            # 合并 (不覆盖已有)
"""

import json
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path


def _home() -> Path:
    return Path.home()


def _claude_dir() -> Path:
    return _home() / ".claude"


def _load_manifest(source_dir: Path) -> dict | None:
    """加载 manifest.json。"""
    mp = source_dir / "manifest.json"
    if mp.exists():
        try:
            return json.loads(mp.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, IOError):
            pass
    return None


def _resolve_source(path: str) -> Path:
    """解析输入路径，支持目录或 .zip 归档。"""
    p = Path(path)
    if p.is_dir():
        return p
    if p.suffix.lower() == ".zip" and p.exists():
        # 解压到临时目录
        tmp = Path(tempfile.mkdtemp(prefix="eval-import-"))
        with zipfile.ZipFile(p, "r") as zf:
            zf.extractall(tmp)
        # 找到实际根目录（可能嵌套了一层）
        manifests = list(tmp.rglob("manifest.json"))
        if manifests:
            return manifests[0].parent
        return tmp
    raise FileNotFoundError(f"Source not found: {path}")


def import_from_dir(source_dir: Path, dry_run: bool = False,
                    merge: bool = False) -> dict:
    """从目录导入数据到 ~/.claude/。"""
    results = {}

    # 1. observations
    obs_src = source_dir / "observations"
    if obs_src.exists():
        obs_dst = _claude_dir() / "observations"
        if not dry_run:
            if obs_dst.exists() and not merge:
                shutil.rmtree(obs_dst)
            obs_dst.mkdir(parents=True, exist_ok=True)
            for f in obs_src.iterdir():
                dst_file = obs_dst / f.name
                if dst_file.exists() and merge:
                    # 合并 JSONL: 追加
                    if f.suffix == ".jsonl":
                        _merge_jsonl(f, dst_file)
                        continue
                    else:
                        continue  # 跳过已有文件
                shutil.copy2(f, dst_file)
        results["observations"] = "imported"
    else:
        results["observations"] = "not_found"

    # 2. eval_results
    eval_src = source_dir / "eval_results"
    if eval_src.exists():
        eval_dst = _claude_dir() / "eval-results"
        if not dry_run:
            if eval_dst.exists() and not merge:
                shutil.rmtree(eval_dst)
            eval_dst.mkdir(parents=True, exist_ok=True)
            for f in eval_src.iterdir():
                dst_file = eval_dst / f.name
                if dst_file.exists() and merge:
                    continue
                if f.is_dir():
                    if dst_file.exists() and merge:
                        continue
                    shutil.copytree(f, dst_file)
                else:
                    shutil.copy2(f, dst_file)
        results["eval_results"] = "imported"
    else:
        results["eval_results"] = "not_found"

    # 3. instincts
    inst_src = source_dir / "instincts"
    if inst_src.exists():
        inst_dst = _claude_dir() / "homunculus" / "instincts"
        if not dry_run:
            inst_dst.mkdir(parents=True, exist_ok=True)
            for f in inst_src.rglob("*"):
                if f.is_file():
                    rel = f.relative_to(inst_src)
                    dst_file = inst_dst / rel
                    if dst_file.exists() and merge:
                        continue
                    dst_file.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(f, dst_file)
        results["instincts"] = "imported"
    else:
        results["instincts"] = "not_found"

    return results


def _merge_jsonl(src: Path, dst: Path):
    """合并 JSONL 文件，去重（按 session_id）。"""
    existing_ids = set()
    if dst.exists():
        with open(dst, "r", encoding="utf-8") as f:
            for line in f:
                try:
                    obj = json.loads(line.strip())
                    sid = obj.get("session_id", "")
                    if sid:
                        existing_ids.add(sid)
                except json.JSONDecodeError:
                    pass

    with open(src, "r", encoding="utf-8") as f_in:
        with open(dst, "a", encoding="utf-8") as f_out:
            for line in f_in:
                try:
                    obj = json.loads(line.strip())
                    sid = obj.get("session_id", "")
                    if sid and sid not in existing_ids:
                        f_out.write(line)
                        existing_ids.add(sid)
                except json.JSONDecodeError:
                    f_out.write(line)


def main():
    import argparse
    parser = argparse.ArgumentParser(
        description="Eval System — 历史数据导入"
    )
    parser.add_argument("source", type=str,
                        help="导出目录或 .zip 归档路径")
    parser.add_argument("--dry-run", action="store_true",
                        help="预览，不写入")
    parser.add_argument("--merge", action="store_true",
                        help="合并模式，不覆盖已有文件")
    args = parser.parse_args()

    if args.dry_run:
        print("=== DRY RUN (预览模式) ===\n")

    source_dir = _resolve_source(args.source)
    manifest = _load_manifest(source_dir)

    if manifest:
        print(f"来源: {manifest.get('hostname', '?')} @ {manifest.get('exported_at', '?')}")
        print(f"内容: {manifest.get('contents', {})}\n")

    results = import_from_dir(source_dir, dry_run=args.dry_run, merge=args.merge)

    print("导入结果:")
    for item, status in results.items():
        print(f"  {item}: {status}")

    if not args.dry_run:
        print(f"\n数据已写入: {_claude_dir()}")


if __name__ == "__main__":
    main()
