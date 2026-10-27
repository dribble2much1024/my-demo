//! Proxy Handler：请求转发核心。

use std::sync::Arc;

use axum::body::Bytes;
use axum::extract::State;
use axum::http::{Request, Uri};
use axum::response::{IntoResponse, Response};

use crate::error::ProxyError;
use crate::state::ProxyState;

/// 代理主入口：接收客户端请求，转发到健康后端，返回上游响应。
pub async fn handle(
    State(state): State<Arc<ProxyState>>,
    request: Request<axum::body::Body>,
) -> Result<Response<axum::body::Body>, ProxyError> {
    // TODO(你来实现) 完整转发流程，建议拆成下面几步：
    //
    // 1. 读入并缓存请求体（一次性消费，之后每次重试都能复制 Bytes 句柄）。
    //    超过 max_request_body 返回 413 PayloadTooLarge。
    //
    // 2. 计算候选节点 candidate_indices()：
    //    - 空列表 -> 返回 503 NoHealthyBackend（没有可调度容量）。
    //
    // 3. 依次尝试每个候选节点：
    //    - build_upstream_request(...) 构造上游请求；
    //    - try_send(...) 发送；
    //    - 成功 -> response_to_axum(...) 转换并返回；
    //    - 传输失败 -> mark_unhealthy，然后判断 is_idempotent：
    //      - 幂等 -> 继续尝试下一个候选；
    //      - 非幂等（POST/PATCH）-> 停止重试。
    //
    // 4. 全部候选失败 -> 返回 502 Upstream（上游通信失败）。
    //
    // 注意：后端返回 500 属于合法 HTTP 响应，原样返回，不换节点重试。
    todo!("实现转发主循环")
}

/// 合成目标 URL：后端基础地址 + 原始 path_and_query。
///
/// 例如后端 `http://127.0.0.1:3001`、请求 `/users/42?full=true`
/// -> `http://127.0.0.1:3001/users/42?full=true`。
fn target_url(base: &url::Url, uri: &Uri) -> Result<url::Url, ProxyError> {
    let path = uri.path_and_query().map(|p| p.as_str()).unwrap_or("/");
    base.join(path.trim_start_matches('/'))
        .map_err(|e| ProxyError::BadTarget(e.to_string()))
}

/// 构造上游请求：保留 method/path/query/header/body，终止逐跳 header，注入转发头。
fn build_upstream_request(
    state: &ProxyState,
    method: http::Method,
    uri: &Uri,
    headers: &http::HeaderMap,
    body: Bytes,
) -> Result<reqwest::Request, ProxyError> {
    // TODO(你来实现):
    // - 用 target_url(base, uri) 合成目标（base 是候选后端的 url）；
    // - 保留 method 与请求体（body 是 Bytes，可重复复制）；
    // - 逐项复制 header，但过滤逐跳 header（headers::strip_hop_by_hop）；
    // - 注入 X-Forwarded-Host / X-Forwarded-Proto（headers::inject_forwarded_headers）；
    // - Host 由目标 URL 决定，不要原样转发客户端 Host。
    todo!("实现上游请求构造")
}

/// 单次发送上游请求，失败时做被动摘除。
async fn try_send(
    state: &ProxyState,
    backend_index: usize,
    request: reqwest::Request,
) -> Result<reqwest::Response, ProxyError> {
    // TODO(你来实现):
    // - 用 state.client 发送请求；
    // - 成功 -> 把对应后端标记为健康，返回响应；
    // - 传输错误 -> mark_unhealthy(state, backend_index)，返回错误。
    todo!("实现单次发送 + 被动摘除")
}

/// 把 reqwest 响应转换为 axum 响应：保留 status / header（过滤逐跳）/ body。
async fn response_to_axum(response: reqwest::Response) -> Response<axum::body::Body> {
    // TODO(你来实现):
    // - 读取 status 与 header；
    // - 过滤逐跳 header（headers::strip_hop_by_hop）；
    // - 把响应体读成 bytes 后封装为 axum Body。
    todo!("实现响应转换")
}
