/// 进程暂停 / 运行时繁忙导致错过计划时间（misfire）时，如何补跑。
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum MisfirePolicy {
    /// 丢掉旧槽位，只保留最近一次到期。
    Skip,
    /// 保留最近 `max_runs` 次到期（有上限，防止补跑风暴）。
    CatchUp { max_runs: usize },
}

/// 上一次执行尚未结束、下一次又到点时，是否允许重叠。
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum OverlapPolicy {
    /// 允许并发执行。
    Allow,
    /// 若同一 Job 仍在运行则跳过本次。
    SkipIfRunning,
}
