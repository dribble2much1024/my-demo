//! 健康检查：被动摘除 + 主动恢复。

use std::sync::atomic::Ordering;
use std::sync::Arc;

use crate::state::ProxyState;

/// 被动健康检查：真实业务请求传输失败时，立即标记节点不健康。
///
/// 由 [`crate::proxy::handle`] 在 `send` 返回 `Err` 时调用。
pub fn mark_unhealthy(state: &ProxyState, index: usize) {
    if let Some(backend) = state.backends.get(index) {
        backend.healthy.store(false, Ordering::Release);
    }
}

/// 主动健康检查：后台任务周期性探活所有后端。
///
/// 每 `health_interval` 秒，对每个后端 `GET {url}{health_path}`，
/// 单次超时 `health_timeout`，2xx 视为健康，其余（超时/连接失败/非 2xx）视为不健康。
///
/// 这样被动摘除的节点在恢复后能自动重新加入轮询。
pub fn spawn_health_check(state: Arc<ProxyState>) -> tokio::task::JoinHandle<()> {
    tokio::spawn(async move {
        // TODO(你来实现): 周期性探活循环，更新每个 Backend.healthy。
        //
        // 提示：
        // - 用 tokio::time::interval(state.health_interval) 驱动周期；
        // - 对每个后端 client.get(...).timeout(state.health_timeout).send()；
        // - 2xx -> store(true, Release)，否则 store(false, Release)；
        // - 可在每个周期用 tracing 记录健康状态变化。
        todo!("实现主动健康检查任务")
    })
}
