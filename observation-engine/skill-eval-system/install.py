#!/usr/bin/env python3
"""Eval System — 一键安装脚本。

将测评系统部署到 ~/.claude/bin/ 并写入 Stop hook，
可选迁移历史数据（observations.jsonl、eval_results/、baselines/、instincts/）。

用法:
  python install.py                              # 纯系统安装
  python install.py --with-history /old/path     # 含历史数据迁移
  python install.py --dry-run                    # 预览，不写入
  python install.py --force                      # 覆盖已有脚本
"""

import json
import os
import shutil
import sys
from pathlib import Path

# ── 常量 ──────────────────────────────────────────────

SKILL_DIR = Path(__file__).resolve().parent
BIN_DIR = SKILL_DIR / "bin"
CASES_DIR = SKILL_DIR / "eval_cases"

SCRIPTS = [
    "eval_harness.py",
    "eval_graders.py",
    "eval_rubric.py",
    "eval_reporter.py",
    "eval_ci.py",
    "eval_badcase.py",
    "eval_instinct.py",
]

HOOK_KEY = "Stop"
HOOK_COMMAND_WIN = (
    "py D:/workspace/my-demo/observation-engine/bin/eval_ci.py --quick"
    " ; py D:/workspace/my-demo/observation-engine/bin/eval_badcase.py"
    " ; py D:/workspace/my-demo/observation-engine/bin/eval_instinct.py"
)
HOOK_COMMAND_UNIX = (
    "python3 ~/.claude/bin/eval_ci.py --quick"
    " ; python3 ~/.claude/bin/eval_badcase.py"
    " ; python3 ~/.claude/bin/eval_instinct.py"
)

# ── 平台检测 ──────────────────────────────────────────

def _is_windows() -> bool:
    return sys.platform == "win32"


def _python_cmd() -> str:
    return "py" if _is_windows() else "python3"


def _home() -> Path:
    return Path.home()


def _claude_dir() -> Path:
    return _home() / ".claude"


def _target_bin_dir() -> Path:
    return _claude_dir() / "bin"


def _target_cases_dir() -> Path:
    return _claude_dir() / "eval_cases"


def _settings_path() -> Path:
    return _claude_dir() / "settings.json"


# ── 安装逻辑 ──────────────────────────────────────────

def install_scripts(dry_run: bool = False, force: bool = False) -> dict:
    """复制 bin/*.py 到 ~/.claude/bin/，返回 {script: status}。"""
    target_dir = _target_bin_dir()
    results = {}

    if not dry_run:
        target_dir.mkdir(parents=True, exist_ok=True)

    for script in SCRIPTS:
        src = BIN_DIR / script
        dst = target_dir / script

        if not src.exists():
            results[script] = "missing_source"
            continue

        if dst.exists() and not force:
            results[script] = "skipped"
            continue

        if not dry_run:
            shutil.copy2(src, dst)
        results[script] = "installed"

    return results


def install_cases(dry_run: bool = False, force: bool = False) -> dict:
    """复制 eval_cases/*.json 到 ~/.claude/eval-cases/，返回 {file: status}。"""
    target_dir = _target_cases_dir()
    results = {}

    if not dry_run:
        target_dir.mkdir(parents=True, exist_ok=True)

    if not CASES_DIR.exists():
        return results

    for case_file in sorted(CASES_DIR.glob("*.json")):
        dst = target_dir / case_file.name
        if dst.exists() and not force:
            results[case_file.name] = "skipped"
            continue
        if not dry_run:
            shutil.copy2(case_file, dst)
        results[case_file.name] = "installed"

    return results


def install_hooks(dry_run: bool = False) -> str:
    """将 eval hook 命令追加到 settings.json 的 Stop hook 中。

    不会重复追加已有命令。返回值: added / skipped / error。
    """
    sp = _settings_path()

    if not sp.exists():
        if not dry_run:
            # 创建最小 settings.json
            sp.parent.mkdir(parents=True, exist_ok=True)
            hook_cmd = _build_hook_command()
            settings = {
                "hooks": {
                    HOOK_KEY: [{
                        "hooks": [{"type": "command", "command": hook_cmd}]
                    }]
                }
            }
            sp.write_text(json.dumps(settings, indent=2, ensure_ascii=False),
                          encoding="utf-8")
        return "created"

    try:
        settings = json.loads(sp.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, IOError):
        return "error"

    hooks = settings.setdefault("hooks", {})
    stop_entries = hooks.setdefault(HOOK_KEY, [])

    eval_cmds = _eval_hook_commands()
    new_cmd = _build_hook_command()

    # 检查是否已存在
    for entry in stop_entries:
        for h in entry.get("hooks", []):
            existing = h.get("command", "")
            if any(cmd in existing for cmd in eval_cmds):
                return "skipped"

    # 追加到第一个 Stop entry（通常只有一个）
    if stop_entries:
        entry = stop_entries[0]
        existing_hooks = entry.get("hooks", [])
        # 追加新命令到现有命令
        for h in existing_hooks:
            if h.get("type") == "command":
                old_cmd = h.get("command", "")
                h["command"] = old_cmd.rstrip() + " ; " + new_cmd
                break
    else:
        stop_entries.append({
            "hooks": [{"type": "command", "command": new_cmd}]
        })

    if not dry_run:
        sp.write_text(json.dumps(settings, indent=2, ensure_ascii=False),
                      encoding="utf-8")

    return "added"


def _eval_hook_commands() -> list[str]:
    """返回标识 eval hook 的命令片段列表。"""
    return ["eval_ci.py", "eval_badcase.py", "eval_instinct.py"]


def _build_hook_command() -> str:
    """构建 hook 命令字符串。默认路径适配当前 OS。"""
    py = _python_cmd()
    bin_dir = _target_bin_dir()
    return (
        f"{py} {bin_dir / 'eval_ci.py'} --quick"
        f" ; {py} {bin_dir / 'eval_badcase.py'}"
        f" ; {py} {bin_dir / 'eval_instinct.py'}"
    )


# ── 历史数据迁移 ──────────────────────────────────────

def migrate_history(source_root: str, dry_run: bool = False) -> dict:
    """迁移历史数据到新 agent。

    source_root: 旧 observation-engine 根目录
    """
    src = Path(source_root)
    results = {}

    # 1. observations.jsonl → ~/.claude/observations/
    obs_src = src / "observations.jsonl"
    if obs_src.exists():
        obs_dst = _home() / ".claude" / "observations" / "observations.jsonl"
        if not dry_run:
            obs_dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(obs_src, obs_dst)
        results["observations.jsonl"] = "migrated"
    else:
        # 也尝试 src/observations/ 目录
        obs_dir_src = src / "observations"
        if obs_dir_src.exists():
            obs_dst = _home() / ".claude" / "observations"
            if not dry_run:
                obs_dst.mkdir(parents=True, exist_ok=True)
                for f in obs_dir_src.iterdir():
                    if f.is_file():
                        shutil.copy2(f, obs_dst / f.name)
            results["observations/"] = "migrated"
        else:
            results["observations"] = "not_found"

    # 2. eval_results/ → ~/.claude/eval-results/
    eval_src = src / "eval_results"
    if eval_src.exists():
        eval_dst = _home() / ".claude" / "eval-results"
        if not dry_run:
            if eval_dst.exists():
                shutil.rmtree(eval_dst)
            shutil.copytree(eval_src, eval_dst)
        results["eval_results"] = "migrated"
    else:
        results["eval_results"] = "not_found"

    # 3. baselines/ (在 eval_results 内部)
    baseline_src = src / "eval_results" / "baselines"
    if baseline_src.exists():
        baseline_dst = _home() / ".claude" / "eval-results" / "baselines"
        if not dry_run:
            baseline_dst.mkdir(parents=True, exist_ok=True)
            for f in baseline_src.iterdir():
                if f.is_file():
                    shutil.copy2(f, baseline_dst / f.name)
        results["baselines"] = "migrated"

    # 4. instincts/ → ~/.claude/homunculus/instincts/
    instinct_src = _home() / ".claude" / "homunculus" / "instincts"
    # 从当前系统迁移（如果 source_root 有自己的 instincts）
    alt_instinct = src / "instincts"
    if alt_instinct.exists():
        instinct_dst = _home() / ".claude" / "homunculus" / "instincts"
        if not dry_run:
            instinct_dst.mkdir(parents=True, exist_ok=True)
            for f in alt_instinct.rglob("*"):
                if f.is_file():
                    rel = f.relative_to(alt_instinct)
                    dst_file = instinct_dst / rel
                    dst_file.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(f, dst_file)
        results["instincts"] = "migrated"
    else:
        results["instincts"] = "not_found"

    return results


# ── 入口 ──────────────────────────────────────────────

def main():
    import argparse
    parser = argparse.ArgumentParser(
        description="Eval System — 一键安装脚本"
    )
    parser.add_argument("--dry-run", action="store_true",
                        help="预览所有操作，不写入文件")
    parser.add_argument("--force", action="store_true",
                        help="覆盖已有脚本")
    parser.add_argument("--with-history", type=str,
                        help="迁移历史数据 (旧 observation-engine 根目录)")
    parser.add_argument("--skill-dir", type=str,
                        help="指定 skill 源码目录 (默认: 脚本同目录)")
    args = parser.parse_args()

    dry_run = args.dry_run
    force = args.force

    if dry_run:
        print("=== DRY RUN (预览模式) ===\n")

    py = _python_cmd()
    print(f"平台: {'Windows' if _is_windows() else 'Unix'}, Python: {py}")
    print(f"目标: {_claude_dir()}\n")

    # Step 1: 安装脚本
    print("[1/4] 安装测评脚本到 ~/.claude/bin/")
    script_results = install_scripts(dry_run=dry_run, force=force)
    for script, status in script_results.items():
        icon = {"installed": "  +", "skipped": "  ~", "missing_source": "  X"}.get(status, "  ?")
        print(f"{icon} {script}: {status}")

    # Step 2: 安装用例集
    print("\n[2/4] 安装用例集到 ~/.claude/eval-cases/")
    case_results = install_cases(dry_run=dry_run, force=force)
    if case_results:
        for case, status in case_results.items():
            print(f"  + {case}: {status}")
    else:
        print("  (无用例文件)")

    # Step 3: 写入 Hook
    print("\n[3/4] 配置 Stop Hook")
    hook_status = install_hooks(dry_run=dry_run)
    print(f"  {hook_status}")

    # Step 4: 历史迁移 (可选)
    if args.with_history:
        print(f"\n[4/4] 迁移历史数据: {args.with_history}")
        mig_results = migrate_history(args.with_history, dry_run=dry_run)
        for item, status in mig_results.items():
            icon = "+" if status == "migrated" else "~"
            print(f"  {icon} {item}: {status}")
    else:
        print("\n[4/4] 历史数据迁移: 跳过 (使用 --with-history 启用)")

    print(f"\n=== {'预览完成' if dry_run else '安装完成'} ===")
    if not dry_run:
        print(f"脚本: {_target_bin_dir()}")
        print(f"用例: {_target_cases_dir()}")
        print(f"Hook: {_settings_path()}")
        print(f"\n下次 Claude Code session 结束时自动运行 CI + BadCase + Instinct 检测。")


if __name__ == "__main__":
    main()
