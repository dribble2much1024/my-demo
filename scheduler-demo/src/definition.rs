use std::sync::Arc;

use crate::handler::JobHandler;
use crate::policy::{MisfirePolicy, OverlapPolicy};
use crate::schedule::Schedule;

/// 一次任务注册：把时间规则和执行策略放在一起。
///
/// 示例（见 `main.rs`）：
/// ```ignore
/// JobDefinition::new("cleanup-sessions", Schedule::every(Duration::from_secs(300)), CleanupJob)
///     .misfire_policy(MisfirePolicy::Skip)
///     .overlap_policy(OverlapPolicy::SkipIfRunning);
/// ```
pub struct JobDefinition {
    pub(crate) id: String,
    pub(crate) schedule: Schedule,
    pub(crate) handler: Arc<dyn JobHandler>,
    pub(crate) misfire_policy: MisfirePolicy,
    pub(crate) overlap_policy: OverlapPolicy,
}

impl JobDefinition {
    pub fn new<H>(id: &str, schedule: Schedule, handler: H) -> Self
    where
        H: JobHandler,
    {
        Self {
            id: id.to_owned(),
            schedule,
            handler: Arc::new(handler),
            // 默认策略：账单结算 / 全量同步等排他任务一般默认 SkipIfRunning；
            // misfire 默认 Skip，避免补跑风暴。
            misfire_policy: MisfirePolicy::Skip,
            overlap_policy: OverlapPolicy::SkipIfRunning,
        }
    }

    pub fn misfire_policy(mut self, policy: MisfirePolicy) -> Self {
        self.misfire_policy = policy;
        self
    }

    pub fn overlap_policy(mut self, policy: OverlapPolicy) -> Self {
        self.overlap_policy = policy;
        self
    }

    pub fn id(&self) -> &str {
        &self.id
    }

    pub fn schedule(&self) -> Schedule {
        self.schedule
    }
}
