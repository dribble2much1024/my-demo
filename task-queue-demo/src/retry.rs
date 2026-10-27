//! 指数退避策略。

use std::time::Duration;

/// 重试策略：初始延迟、最大延迟、总执行次数上限。
#[derive(Clone)]
pub struct RetryPolicy {
    initial_delay: Duration,
    max_delay: Duration,
    max_attempts: u32,
}

impl RetryPolicy {
    pub fn new(initial_delay: Duration, max_delay: Duration, max_attempts: u32) -> Self {
        Self {
            initial_delay,
            max_delay,
            max_attempts,
        }
    }

    /// 总执行次数上限（第一次执行也算在内）。
    pub fn max_attempts(&self) -> u32 {
        self.max_attempts
    }

    /// 返回第 `next_attempt` 次执行前的等待时间，指数增长并封顶。
    ///
    /// 规律：`initial_delay * 2^(next_attempt - 2)`，结果不超过 `max_delay`。
    /// `next_attempt` 从 2 开始（第一次执行后进入重试）。
    pub fn delay_for(&self, next_attempt: u32) -> Duration {
        todo!("补全 delay_for：指数退避并封顶")
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn exponential_backoff_grows_and_caps() {
        let policy = RetryPolicy::new(
            Duration::from_secs(1),
            Duration::from_secs(30),
            4,
        );

        // 1s * 2^(n-2)
        assert_eq!(policy.delay_for(2), Duration::from_secs(1));
        assert_eq!(policy.delay_for(3), Duration::from_secs(2));
        assert_eq!(policy.delay_for(4), Duration::from_secs(4));
        assert_eq!(policy.delay_for(5), Duration::from_secs(8));
        assert_eq!(policy.delay_for(6), Duration::from_secs(16));

        // 32s 越过上限，封顶 30s
        assert_eq!(policy.delay_for(7), Duration::from_secs(30));
        // 极大值不会溢出，仍封顶
        assert_eq!(policy.delay_for(40), Duration::from_secs(30));
    }
}
