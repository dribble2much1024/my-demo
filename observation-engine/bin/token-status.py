#!/usr/bin/env python3
"""Token 用量查询——读取 api-calls.jsonl 和 last_call.json，输出会话级统计。"""
import json
from pathlib import Path

OBS = Path.home() / ".claude" / "observations"
STATUS = OBS / "last_call.json"
API_CALLS = OBS / "api-calls.jsonl"


def main():
    # 最新调用
    if STATUS.exists():
        data = json.loads(STATUS.read_text(encoding="utf-8"))
        s = data.get("session", {})
        lc = data.get("last_call", {})
        print(f"最新调用: {lc.get('model','?')}  in:{lc.get('input_tokens',0)}  out:{lc.get('output_tokens',0)}  {lc.get('duration_ms',0)}ms  [{lc.get('stop_reason','')}]")
        print(f"会话累计: {s.get('calls',0)} 次调用  in:{s.get('input_tokens',0)}  out:{s.get('output_tokens',0)}  合计:{s.get('input_tokens',0)+s.get('output_tokens',0)} tokens")
        print()

    # 全量统计
    if API_CALLS.exists():
        total_in, total_out, total_calls = 0, 0, 0
        with open(API_CALLS, "r", encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    r = json.loads(line)
                    total_in += r.get("input_tokens", 0) or 0
                    total_out += r.get("output_tokens", 0) or 0
                    total_calls += 1
                except json.JSONDecodeError:
                    continue
        print(f"历史总计: {total_calls} 次调用  in:{total_in}  out:{total_out}  合计:{total_in+total_out} tokens")
    else:
        print("暂无 API 调用记录（需要先启动 api-gateway-observer 并配置 ANTHROPIC_BASE_URL）")


if __name__ == "__main__":
    main()
