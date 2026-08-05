#!/usr/bin/env python3
"""API Gateway Observer — 本地 HTTP 转发代理，观测所有 LLM API 调用。

原理：将 ANTHROPIC_BASE_URL 指向本代理，代理转发到真实后端。
代理在本地回环接收明文 HTTP 请求，向外部走 HTTPS，无 MITM 证书。

用法：python3 api-gateway-observer.py [--port 8899] [--upstream-host api.deepseek.com] [--upstream-prefix /anthropic]

输出：~/.claude/observations/api-calls.jsonl
"""

import http.client
import http.server
import json
import os
import re
import ssl
import sys
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

# ══════════════════════════════════════════════════════
OBSERVATIONS_DIR = Path.home() / ".claude" / "observations"
API_CALLS_FILE = OBSERVATIONS_DIR / "api-calls.jsonl"
ERROR_LOG = OBSERVATIONS_DIR / "errors.log"
STATUS_FILE = OBSERVATIONS_DIR / "last_call.json"

# 会话级计数器
_session_stats = {"calls": 0, "input_tokens": 0, "output_tokens": 0}

# 默认上游配置（DeepSeek Anthropic 兼容接口）
UPSTREAM_HOST = "api.deepseek.com"
UPSTREAM_PATH_PREFIX = "/anthropic"


def log_error(msg: str) -> None:
    try:
        ts = datetime.now(timezone.utc).isoformat()
        with open(ERROR_LOG, "a", encoding="utf-8") as f:
            f.write(f"[{ts}] [gateway] {msg}\n")
    except Exception:
        pass


def write_record(record: dict) -> None:
    try:
        OBSERVATIONS_DIR.mkdir(parents=True, exist_ok=True)
        with open(API_CALLS_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception as e:
        log_error(f"write record error: {e}")


# ══════════════════════════════════════════════════════
# 请求/响应解析
# ══════════════════════════════════════════════════════

def extract_request_meta(body: bytes, path: str) -> dict:
    """从请求体提取元信息：model、messages 数量、tools、stream 标志。"""
    meta = {
        "endpoint": path,
        "model": "",
        "messages_count": 0,
        "tools_count": 0,
        "stream": False,
        "max_tokens": 0,
    }
    try:
        data = json.loads(body)
        meta["model"] = data.get("model", "")
        meta["stream"] = data.get("stream", False)
        meta["max_tokens"] = data.get("max_tokens", 0)

        msgs = data.get("messages")
        if isinstance(msgs, list):
            meta["messages_count"] = len(msgs)

        tools = data.get("tools")
        if isinstance(tools, list):
            meta["tools_count"] = len(tools)
            meta["tool_names"] = [t.get("name", "") for t in tools if isinstance(t, dict)]
    except (json.JSONDecodeError, Exception):
        pass
    return meta


def parse_sse_events(chunks: list[bytes]) -> dict:
    """从累积的 SSE chunk 中提取最终 usage、model、stop_reason、tool_use 名称。"""
    result = {
        "model": "",
        "input_tokens": 0,
        "output_tokens": 0,
        "stop_reason": "",
        "tool_calls": [],
    }
    full_text = b"".join(chunks).decode("utf-8", errors="replace")

    # 按 SSE 事件分割
    events = re.split(r"\n(?=event:|\n*data:)", full_text)
    for event in events:
        data_match = re.search(r"^data:\s*(.+)$", event, re.MULTILINE)
        if not data_match:
            continue
        try:
            payload = json.loads(data_match.group(1))
        except json.JSONDecodeError:
            continue

        etype = payload.get("type", "")

        if etype == "message_start":
            msg = payload.get("message", {})
            result["model"] = msg.get("model", "")
            usage = msg.get("usage", {})
            result["input_tokens"] = usage.get("input_tokens", 0)

        elif etype == "content_block_start":
            cb = payload.get("content_block", {})
            if cb.get("type") == "tool_use":
                result["tool_calls"].append(cb.get("name", ""))

        elif etype == "message_delta":
            delta = payload.get("delta", {})
            result["stop_reason"] = delta.get("stop_reason", "")
            usage = payload.get("usage", {})
            result["output_tokens"] = usage.get("output_tokens", 0)

    return result


def parse_nonstream_body(body: bytes) -> dict:
    """解析非流式响应体，提取 usage。"""
    result = {"input_tokens": 0, "output_tokens": 0, "stop_reason": ""}
    try:
        data = json.loads(body)
        usage = data.get("usage", {})
        result["input_tokens"] = usage.get("input_tokens", 0)
        result["output_tokens"] = usage.get("output_tokens", 0)
        result["stop_reason"] = data.get("stop_reason", "")
        # 提取 tool_use
        content = data.get("content", [])
        if isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and block.get("type") == "tool_use":
                    result.setdefault("tool_calls", []).append(block.get("name", ""))
    except (json.JSONDecodeError, Exception):
        pass
    return result


# ══════════════════════════════════════════════════════
# HTTP 请求处理器
# ══════════════════════════════════════════════════════

class ProxyHandler(http.server.BaseHTTPRequestHandler):

    def do_GET(self):
        """健康检查。"""
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(b"API Gateway Observer OK\n")

    def do_POST(self):
        start_time = datetime.now(timezone.utc)
        session_id = os.environ.get("CLAUDE_SESSION_ID") or uuid.uuid4().hex[:12]

        # 读取请求体
        content_length = int(self.headers.get("Content-Length", 0))
        request_body = self.rfile.read(content_length) if content_length > 0 else b""

        # 提取请求元信息
        req_meta = extract_request_meta(request_body, self.path)

        # 转发到上游
        upstream_path = UPSTREAM_PATH_PREFIX + self.path
        status_code = 502
        response_body = b""
        response_chunks: list[bytes] = []
        is_stream = req_meta.get("stream", False)

        try:
            conn = http.client.HTTPSConnection(
                UPSTREAM_HOST,
                context=ssl.create_default_context(),
                timeout=120,
            )

            # 构建转发头
            fwd_headers = {}
            for key, value in self.headers.items():
                kl = key.lower()
                if kl in ("host", "connection", "transfer-encoding"):
                    continue
                fwd_headers[key] = value
            fwd_headers["Host"] = UPSTREAM_HOST

            if request_body:
                fwd_headers["Content-Length"] = str(len(request_body))

            conn.request("POST", upstream_path, body=request_body, headers=fwd_headers)
            upstream_resp = conn.getresponse()

            status_code = upstream_resp.status

            # 转发响应头
            resp_headers = []
            for key, value in upstream_resp.getheaders():
                kl = key.lower()
                if kl in ("transfer-encoding",):
                    # http.server 自己处理 chunked
                    continue
                resp_headers.append((key, value))

            # 特殊处理: 无 Content-Length 且 200 → 流式
            cl = upstream_resp.getheader("Content-Length")
            content_type = upstream_resp.getheader("Content-Type", "")

            if is_stream or (status_code == 200 and cl is None):
                # 流式响应
                resp_headers.append(("Content-Type", "text/event-stream"))
                # 不发送 Content-Length — 用 chunked
                self.send_response(status_code)
                for k, v in resp_headers:
                    if k.lower() != "content-length":
                        self.send_header(k, v)
                self.end_headers()

                while True:
                    chunk = upstream_resp.read(8192)
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    response_chunks.append(chunk)
                self.wfile.flush()
            else:
                # 非流式响应
                response_body = upstream_resp.read()
                resp_headers.append(("Content-Length", str(len(response_body))))
                self.send_response(status_code)
                for k, v in resp_headers:
                    self.send_header(k, v)
                self.end_headers()
                self.wfile.write(response_body)

            conn.close()

        except Exception as e:
            log_error(f"upstream error: {e}")
            try:
                self.send_response(502)
                self.send_header("Content-Type", "text/plain")
                self.end_headers()
                self.wfile.write(f"Gateway Error: {e}".encode())
            except Exception:
                pass

        # 构建观测记录
        duration_ms = int(
            (datetime.now(timezone.utc) - start_time).total_seconds() * 1000
        )

        record = {
            "session_id": session_id,
            "ts": start_time.isoformat(),
            "endpoint": req_meta.get("endpoint", ""),
            "model": req_meta.get("model", ""),
            "messages_count": req_meta.get("messages_count", 0),
            "tools_count": req_meta.get("tools_count", 0),
            "stream": is_stream,
            "max_tokens": req_meta.get("max_tokens", 0),
            "status_code": status_code,
            "duration_ms": duration_ms,
        }

        # 提取响应元信息
        if is_stream and response_chunks:
            sse_meta = parse_sse_events(response_chunks)
            record.update({
                "input_tokens": sse_meta.get("input_tokens", 0),
                "output_tokens": sse_meta.get("output_tokens", 0),
                "stop_reason": sse_meta.get("stop_reason", ""),
                "tool_calls": sse_meta.get("tool_calls", []),
            })
        elif response_body:
            nonstream_meta = parse_nonstream_body(response_body)
            record.update({
                "input_tokens": nonstream_meta.get("input_tokens", 0),
                "output_tokens": nonstream_meta.get("output_tokens", 0),
                "stop_reason": nonstream_meta.get("stop_reason", ""),
                "tool_calls": nonstream_meta.get("tool_calls", []),
            })

        if req_meta.get("tool_names"):
            record["request_tools"] = req_meta["tool_names"]

        # 实时输出 + 累积
        _session_stats["calls"] += 1
        _session_stats["input_tokens"] += record.get("input_tokens", 0)
        _session_stats["output_tokens"] += record.get("output_tokens", 0)
        record["session_calls"] = _session_stats["calls"]
        record["session_input_total"] = _session_stats["input_tokens"]
        record["session_output_total"] = _session_stats["output_tokens"]

        model = record.get("model", "?")[:25]
        inp = record.get("input_tokens", 0)
        out = record.get("output_tokens", 0)
        dur = record.get("duration_ms", 0)
        sc = record.get("status_code", 0)
        sm = record.get("stop_reason", "")[:12]
        ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
        line = (
            f"  [{ts}] #{_session_stats['calls']} {model}"
            f"  in:{inp} out:{out}  {dur}ms  {sc}"
            f"  [{_session_stats['input_tokens']}+{_session_stats['output_tokens']}={_session_stats['input_tokens']+_session_stats['output_tokens']}]"
            f"  {sm}"
        )
        print(line, flush=True)

        write_record(record)

        # 写入状态文件供快速查询
        try:
            STATUS_FILE.write_text(json.dumps({
                "last_call": record,
                "session": _session_stats,
            }, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass

    def log_message(self, format, *args):
        """关闭默认的 stderr 日志。"""
        return


# ══════════════════════════════════════════════════════
# Main
# ══════════════════════════════════════════════════════

def main() -> None:
    port = 8899
    args = sys.argv[1:]
    for i, arg in enumerate(args):
        if arg == "--port" and i + 1 < len(args):
            port = int(args[i + 1])
        elif arg == "--upstream-host" and i + 1 < len(args):
            global UPSTREAM_HOST
            UPSTREAM_HOST = args[i + 1]
        elif arg == "--upstream-prefix" and i + 1 < len(args):
            global UPSTREAM_PATH_PREFIX
            UPSTREAM_PATH_PREFIX = args[i + 1]

    OBSERVATIONS_DIR.mkdir(parents=True, exist_ok=True)

    server = http.server.HTTPServer(("127.0.0.1", port), ProxyHandler)
    print(f"API Gateway Observer")
    print(f"  Listen: http://127.0.0.1:{port}")
    print(f"  Upstream: https://{UPSTREAM_HOST}{UPSTREAM_PATH_PREFIX}")
    print(f"  Logs: {API_CALLS_FILE}")
    print(f"  (Ctrl+C to stop)")
    print()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.")
        server.shutdown()


if __name__ == "__main__":
    main()
