---
title: 不改一行代码，看透 AI Agent 的每一次调用
source: 阿里云云原生
author: 古琦
date: 2026-07-02
url: https://mp.weixin.qq.com/s/FLZdJiq6kCVNkcMZXJPmIw
---

# OBI（OpenTelemetry eBPF Instrumentation）— 内核级 AI Agent 无侵入观测

## 核心思路

把观测能力下沉到 Linux 内核网络层：用 eBPF uprobe 挂在 OpenSSL `SSL_write`/`SSL_read`，
在加密前/解密后拦截明文 HTTP 流量，不改一行业务代码，自动识别并解析所有 AI 相关网络调用。

## 关键技术

### 1. TLS 明文截获
- uprobe 挂在 libssl.so 的 SSL_write/SSL_read（也支持 Go crypto/tls、Python _ssl）
- 不需要 CA 证书、不需要私钥——应用和密码库之间的接口永远是明文 buffer

### 2. 三级协议识别状态机
- Level 1: 响应头特征码（Openai-Version, Anthropic-Organization-Id 等）
- Level 2: URL Host + Path 二段验证
- Level 3: 请求/响应体顶层键 verify（model + messages, model + input 等）

### 3. 跨语言协程追踪
- Python asyncio: 4 个 uprobe (task_step, Task.init, PyContext_CopyCurrent, context_run)
- Go goroutine: runtime.newproc1 + runtime.casgstatus + 祖先溯源（最多 6 层）
- 跨进程: 内核层 tpinjector 注入 W3C traceparent 到 HTTP header

### 4. SSE 流式处理
- 按 trace ID 维护累积缓冲区
- 事件级实时累积 token
- 最终输出与非流式 API 完全等价的 OTel Span

### 5. 性能：1% CPU
- BPF ringbuf 零拷贝（Linux 5.8+）
- 背压由 ringbuf 水位线控制
- 内核 eBPF 只做最薄的"抓 buffer + 入 ringbuf"

## 适配的 Provider
OpenAI, Anthropic, Gemini, 通义千问, Bedrock, Pinecone, Qdrant, Milvus, Chroma, Weaviate, MCP

## 我们的实现对照

我们的 `api-gateway-observer.py` 借鉴了相同的"中间人"思想，但层次不同：

| | OBI | api-gateway-observer |
|---|---|---|
| **层** | Linux 内核 eBPF | Python HTTP 代理 |
| **入侵性** | 零（DaemonSet） | 改一行 ANTHROPIC_BASE_URL |
| **可见内容** | HTTP 明文 | HTTP 明文（本地回环） |
| **协议识别** | 三级状态机 | 已知后端（DeepSeek） |
| **流式处理** | uprobe + 累积缓冲 | SSE chunk 累积 |
| **跨平台** | Linux 专属 | 全平台（Python） |
