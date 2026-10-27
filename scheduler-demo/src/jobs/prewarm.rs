use async_trait::async_trait;
use tracing::info;

use crate::context::JobContext;
use crate::handler::JobHandler;

/// 演示任务：预热缓存。
pub struct PrewarmJob;

#[async_trait]
impl JobHandler for PrewarmJob {
    async fn run(&self, context: JobContext) -> Result<(), String> {
        info!(
            delay_ms = context.delay().as_millis() as u64,
            "预热缓存"
        );
        // TODO: 这里放真实的缓存预热逻辑。
        Ok(())
    }
}
