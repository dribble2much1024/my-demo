use std::cmp::Ordering;

use tokio::time::Instant;

/// 堆中的一个待到期 deadline。
///
/// `std::collections::BinaryHeap` 默认是**最大堆**，而调度器需要**最小堆**
/// （最早 `due_at` 在堆顶）。所以要在 `Ord` 里反转比较方向。
///
/// 字段说明：
/// - `due_at`：到期时间（同时也是 fixed-rate 下一次要锚定的槽位）；
/// - `sequence`：相同 `due_at` 时的先后次序，单调递增避免相等；
/// - `job_id`：这个 deadline 属于哪个 Job（排序时不参与比较，只是负载数据）。
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Deadline {
    pub due_at: Instant,
    pub sequence: u64,
    pub job_id: String,
}

impl Deadline {
    pub fn new(due_at: Instant, sequence: u64, job_id: impl Into<String>) -> Self {
        Self {
            due_at,
            sequence,
            job_id: job_id.into(),
        }
    }
}

impl Ord for Deadline {
    fn cmp(&self, other: &Self) -> Ordering {
        // TODO(你来实现): 反转比较方向，让最早 due_at 排到堆顶。
        //
        // 提示：最大堆会先弹出 cmp 结果最大的元素。要让"最早到期"成为"最大"，
        // 需要比较 `other` 与 `self`（方向对调）：
        //
        //   other.due_at.cmp(&self.due_at)
        //       .then_with(|| other.sequence.cmp(&self.sequence))
        //
        // 这样 due_at 更早的 deadline 反而 cmp 结果更大，被堆放到顶部。
        todo!("实现最小堆比较：反转 other 与 self 的比较方向")
    }
}

impl PartialOrd for Deadline {
    fn partial_cmp(&self, other: &Self) -> Option<Ordering> {
        Some(self.cmp(other))
    }
}
