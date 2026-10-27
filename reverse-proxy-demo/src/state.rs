//! 进程内共享状态与后端节点定义。

use std::sync::atomic::{AtomicBool, AtomicUsize};
use std::sync::Arc;
use std::time::Duration;

use reqwest::Client;
use url::Url;

use crate::config::Config;

/// 单个上游后端。
///
/// `url` 在启动后固定不变；`healthy` 是运行期唯一会变化的字段，
/// 用原子布尔表达即可，无需加锁。
pub struct Backend {
    pub url: Url,
    pub healthy: AtomicBool,
}

/// 代理进程内共享状态，被所有 handler 与后台任务通过 `Arc` 共享。
pub struct ProxyState {
    /// 复用连接的上游 HTTP 客户端。
    pub client: Client,
    /// 后端列表。启动后不再增删，`Vec` 本身无需锁。
    pub backends: Arc<Vec<Backend>>,
    /// Round Robin 原子游标。只生成不重复的递增位置，用 `Relaxed` 即可。
    pub next: Arc<AtomicUsize>,
    /// 请求体上限（字节）。
    pub max_request_body: usize,
    /// 主动健康检查间隔。
    pub health_interval: Duration,
    /// 主动健康检查单次超时。
    pub health_timeout: Duration,
    /// 健康检查路径。
    pub health_path: String,
}

impl ProxyState {
    /// 根据配置构建共享状态。
    pub fn new(config: &Config) -> anyhow::Result<Arc<Self>> {
        let client = Client::builder()
            .timeout(config.upstream_timeout)
            .build()?;

        let backends = config
            .backends
            .iter()
            .map(|url| Backend {
                url: url.clone(),
                healthy: AtomicBool::new(true),
            })
            .collect();

        Ok(Arc::new(Self {
            client,
            backends: Arc::new(backends),
            next: Arc::new(AtomicUsize::new(0)),
            max_request_body: config.max_request_body,
            health_interval: config.health_interval,
            health_timeout: config.health_timeout,
            health_path: config.health_path.clone(),
        }))
    }
}
