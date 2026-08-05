---
name: migrate-self-evolution
description: Use when migrating or deploying the Claude Code self-evolution system (Observation Engine + Instinct Engine + auto-evolved rules) to a new device with zero configuration — one file, one command
---

# Migrate Self-Evolution System

Zero-cost migration of the complete self-evolution system to a new device. The installer is a single self-contained Python file that embeds all 4 engine scripts and hook configuration. No dependencies beyond Python 3.

## Usage

On the target device:

```bash
# 1. Copy the installer to the target device
scp observation-engine/install/install.py new-device:/tmp/

# 2. Run it
python3 /tmp/install.py

# Done. Next Claude Code session automatically activates.
```

Options:
- `--dry-run` — preview without writing files
- `--force` — overwrite existing scripts (default: skip)

## What Gets Installed

| Path | Component |
|---|---|
| `~/.claude/bin/observe.py` | Observation Engine — Hook-triggered tool call capture |
| `~/.claude/bin/observations_rotate.py` | Log rotation — monthly archiving |
| `~/.claude/bin/auto-analyze-instincts.py` | Instinct Engine — Pattern detection + AI analysis |
| `~/.claude/bin/auto-evolve.py` | Rule evolution — Dedup + domain aggregation |
| `~/.claude/bin/api-gateway-observer.py` | API Gateway Observer — LLM call tracing (optional) |
| `~/.claude/settings.json` | Hook configuration (merged, not replaced) |

## Strategy

**Pure system** — scripts and hooks only, no historical data. The system starts learning from the first session on the new device.

## Platform Detection

| OS | Python command in hooks |
|---|---|
| Windows | `py` |
| macOS / Linux | `python3` |

## After Install

The system requires data accumulation before rules emerge:
- Instinct Engine needs 5+ sessions to reach confidence >= 0.7
- `auto-evolved.md` appears automatically when rules mature
- Check status: `ls ~/.claude/rules/auto-evolved.md`
