//! 教学版 HTTP/1.1 反向代理与负载均衡器。
//!
//! 职责拆分：
//! - [`proxy`]       —— HTTP 语义、Header、Body、超时、转发
//! - [`balancer`]    —— 候选节点顺序（Round Robin）
//! - [`health`]      —— 探活、摘除、恢复
//! - [`retry`]       —— 幂等性判断
//! - [`headers`]     —— 逐跳 Header 过滤与 X-Forwarded-* 注入
//!
//! 换成加权最少连接 / 一致性哈希时，HTTP 转发部分无需重写；
//! 健康检查换成服务发现时，重试语义也不用变。

pub mod balancer;
pub mod config;
pub mod error;
pub mod headers;
pub mod health;
pub mod proxy;
pub mod retry;
pub mod state;

use std::sync::Arc;

use axum::Router;

use crate::state::ProxyState;

/// 构建代理 Router：`/health` 返回本代理存活标记，其余路径交给 [`proxy::handle`]。
pub fn build_router(state: Arc<ProxyState>) -> Router {
    Router::new()
        .route("/health", axum::routing::get(|| async { "proxy ok" }))
        .fallback(proxy::handle)
        .with_state(state)
}
