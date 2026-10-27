//! 集成测试：启动真实后端与代理，通过 HTTP 客户端验证不变量。
//!
//! 测试不直接调用 handler，而是走完整网络路径，覆盖四个关键不变量：
//! 1. path、query、自定义 Header 能完整到达后端；
//! 2. 连续请求被 Round Robin 分配到不同节点；
//! 3. GET 遇到不可达节点会故障转移到健康节点；
//! 4. POST 遇到同样错误不会跨节点重试（避免重复副作用）。
//!
//! 第四项尤其重要：验证失败时不会制造重复副作用，才是代理正确性的一部分。

use std::sync::Arc;

use reverse_proxy_demo::{build_router, config::Config, state::ProxyState};
use url::Url;

/// 启动一个监听随机端口的模拟后端，返回它的地址与调用计数。
///
/// 可配置：
/// - 固定响应体（用于观察 path/query/header 是否透传）；
/// - 共享的调用计数器（用于验证 POST 不重复调用）。
async fn spawn_mock_backend() -> (Url, Arc<std::sync::atomic::AtomicUsize>) {
    // TODO(你来实现): 随机端口绑定 + axum::serve，返回 (地址, 计数器)。
    todo!("实现 mock 后端启动 helper")
}

/// 用给定后端列表启动一个代理，返回代理地址。
async fn spawn_proxy(backends: Vec<Url>) -> String {
    // TODO(你来实现):
    // - 构造 Config（listen 用随机端口，backends 传入）；
    // - ProxyState::new + build_router + 随机端口绑定 + serve。
    todo!("实现代理启动 helper")
}

#[tokio::test]
async fn test_preserves_path_query_and_header() {
    // TODO(你来实现): 断言 path/query/自定义 Header 完整到达后端。
    todo!("不变量 1")
}

#[tokio::test]
async fn test_round_robin_distributes_across_nodes() {
    // TODO(你来实现): 断言连续请求被分配到不同后端节点。
    todo!("不变量 2")
}

#[tokio::test]
async fn test_get_fails_over_to_healthy_node() {
    // TODO(你来实现): 断言 GET 在遇到不可达节点时故障转移到健康节点。
    todo!("不变量 3")
}

#[tokio::test]
async fn test_post_does_not_retry_across_nodes() {
    // TODO(你来实现): 断言 POST 在传输失败时不会跨节点重试。
    todo!("不变量 4")
}
