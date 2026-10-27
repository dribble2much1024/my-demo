/// 单次执行的结果。
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum RunOutcome {
    Succeeded,
    Failed,
    Panicked,
}

/// 调度器结束后的运行统计。
#[derive(Debug, Clone, Default)]
pub struct SchedulerReport {
    /// 实际启动过的执行次数。
    pub started: u64,
    /// 成功次数。
    pub succeeded: u64,
    /// 返回 Err 的次数。
    pub failed: u64,
    /// panic 被隔离捕获的次数。
    pub panicked: u64,
    /// 因 misfire 被跳过的次数。
    pub skipped_misfires: u64,
    /// 因 overlap 被跳过的次数。
    pub skipped_overlaps: u64,
    /// 关闭时尚未启动、被丢弃的次数。
    pub discarded_on_shutdown: u64,
}
