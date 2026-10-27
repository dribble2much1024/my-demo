use std::time::Duration;

use tokio::time::Instant;

/// 单次执行收到的上下文：计划时间与真实开始时间。
///
/// 两者相减即可得到"晚了多久"。`scheduled_at` 可作为幂等键的一部分，
/// 配合 `job_id` 区分同一个 Job 的不同次执行。
#[derive(Debug, Clone, Copy)]
pub struct JobContext {
    /// 计划执行时间（fixed-rate 锚定的槽位）。
    pub scheduled_at: Instant,
    /// 真实开始执行的时间。
    pub started_at: Instant,
}

impl JobContext {
    /// 本次执行晚于计划多久。
    pub fn delay(self) -> Duration {
        self.started_at.saturating_duration_since(self.scheduled_at)
    }
}
