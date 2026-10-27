use std::time::Duration;

/// 任务的时间规则。
///
/// 本 Demo 只覆盖固定间隔和一次性延迟两类**相对时间**规则。
/// 日历规则（每天 02:00、cron、时区、夏令时）留到后续单独讨论。
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Schedule {
    /// 一次性：调度器启动后 `after` 之后执行一次。
    Once { after: Duration },
    /// 周期：启动 `start_after` 后执行第一次，之后每隔 `interval` 执行一次。
    Every {
        interval: Duration,
        start_after: Duration,
    },
}

impl Schedule {
    /// 一次性任务，在启动后 `after` 执行。
    pub fn once(after: Duration) -> Self {
        Schedule::Once { after }
    }

    /// 周期任务，先等一个完整周期再执行第一次。
    pub fn every(interval: Duration) -> Self {
        Schedule::Every {
            interval,
            start_after: interval,
        }
    }

    /// 周期任务，启动后立即执行第一次，之后每隔 `interval` 执行。
    pub fn every_immediately(interval: Duration) -> Self {
        Schedule::Every {
            interval,
            start_after: Duration::ZERO,
        }
    }

    /// 距离第一次执行的延迟。
    pub fn first_delay(&self) -> Duration {
        match self {
            Schedule::Once { after } => *after,
            Schedule::Every { start_after, .. } => *start_after,
        }
    }

    /// 周期任务的间隔；一次性任务返回 `None`。
    pub fn interval(&self) -> Option<Duration> {
        match self {
            Schedule::Once { .. } => None,
            Schedule::Every { interval, .. } => Some(*interval),
        }
    }
}
