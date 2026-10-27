use async_trait::async_trait;

use crate::context::JobContext;

/// 业务任务接入点。
///
/// 数据库超时、参数错误、下游请求失败都应通过 `Result::Err` 返回。
/// 这里的 `String` 只用于演示；生产建议换成结构化错误类型（如 `thiserror` 枚举）。
///
/// 注意：捕获 panic 是为了隔离故障，不是替代错误处理。出现 panic 仍需要告警。
#[async_trait]
pub trait JobHandler: Send + Sync + 'static {
    async fn run(&self, context: JobContext) -> Result<(), String>;
}
