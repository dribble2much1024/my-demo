use async_trait::async_trait;
use tracing::info;

use crate::context::JobContext;
use crate::handler::JobHandler;

/// 演示任务：清理过期 Session。
pub struct CleanupJob;

#[async_trait]
impl JobHandler for CleanupJob {
    async fn run(&self, context: JobContext) -> Result<(), String> {
        info!(
            delay_ms = context.delay().as_millis() as u64,
            "清理过期 Session"
        );
        // TODO: 这里放真实的 Session 清理逻辑。
        Ok(())
    }
}
