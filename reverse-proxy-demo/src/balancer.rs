//! 负载均衡：Round Robin 候选节点选择。

use std::sync::atomic::Ordering;

use crate::state::ProxyState;

impl ProxyState {
    /// 返回本次请求的候选节点下标列表，按尝试优先级排序。
    ///
    /// 行为：
    /// 1. `next.fetch_add(1, Relaxed) % len` 得到本次起点；
    /// 2. 从起点环形扫描一圈，只收集 `healthy == true` 的节点；
    /// 3. 返回下标列表。代理按顺序尝试，第一个连接失败就试下一个。
    ///
    /// 设计说明：
    /// - 不保证严格公平：并发到达顺序、节点故障、请求耗时都会改变实际分布；
    /// - 只保证：无锁、每次扫描开销固定、健康节点大致均匀；
    /// - 游标用 `Relaxed`：它只生成不重复的递增位置，不携带其他内存序。
    pub fn candidate_indices(&self) -> Vec<usize> {
        // TODO(你来实现): 环形扫描，跳过不健康节点，返回健康节点下标。
        todo!("实现 Round Robin 候选选择")
    }
}
