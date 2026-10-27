# 用 Rust 实现一个进程内定时任务调度器 —— 实现指导

> 本文对应微信文章《用 Rust 实现一个定时任务调度器》（作者 billchen）。
> 骨架已搭好，类型、模块、demo、测试全部就位，**核心调度循环留给你实现**。
> 全文按"概念 → 对应文件 → 你要做什么 → 参考答案"组织，读完即可逐处填 `todo!()`。

---

## 1. 整体架构

调度器分两层，职责清晰：

```
调度层：何时应该产生一次 occurrence
- Schedule（时间规则）
- deadline 最小堆（BinaryHeap）
- misfire / overlap policy
        │
        ▼
执行层：这一次 occurrence 怎样运行
- JoinSet（跟踪运行中的 task）
- 全局并发上限（max_concurrency）
- panic 隔离（catch_unwind）
- 运行结果统计（SchedulerReport）
```

一次计划中的执行叫 **occurrence**（对应 `src/scheduler.rs::Occurrence`）。

### 项目结构

```
scheduler-demo/
├── Cargo.toml
├── GUIDE.md                ← 本文
├── src/
│   ├── lib.rs              # 模块声明 + 公开 re-export
│   ├── main.rs             # demo 入口：注册两个任务，跑 Ctrl-C
│   ├── schedule.rs         # ✅ 已完成：Schedule 枚举
│   ├── policy.rs           # ✅ 已完成：MisfirePolicy / OverlapPolicy
│   ├── context.rs          # ✅ 已完成：JobContext
│   ├── handler.rs          # ✅ 已完成：JobHandler trait
│   ├── config.rs           # ✅ 已完成：SchedulerConfig
│   ├── error.rs            # ✅ 已完成：SchedulerError
│   ├── report.rs           # ✅ 已完成：RunOutcome / SchedulerReport
│   ├── deadline.rs         # ⛳ 待实现：Deadline 的 Ord（最小堆）
│   ├── definition.rs       # ✅ 已完成：JobDefinition（builder）
│   ├── scheduler.rs        # ⛳ 待实现：Scheduler（核心）
│   └── jobs/
│       ├── mod.rs
│       ├── cleanup.rs      # ✅ 演示：清理 Session
│       └── prewarm.rs      # ✅ 演示：预热缓存
└── tests/
    └── scheduler_test.rs   # ⛳ 待实现：测试断言（脚手架已备好）
```

✅ = 已写好，可直接用；⛳ = 留给你实现的地方（搜 `todo!`）。

---

## 2. 已完成的类型说明（理解它们再动手）

### 2.1 `Schedule` —— 时间规则

```rust
pub enum Schedule {
    Once { after: Duration },                       // 一次性
    Every { interval: Duration, start_after: Duration }, // 周期
}
```

- `Schedule::once(30s)`：启动后 30s 执行一次。
- `Schedule::every(300s)`：等一个完整周期后执行第一次，之后每 300s。
- `Schedule::every_immediately(300s)`：立即执行第一次，之后每 300s。

Demo 只覆盖**相对时间**规则。"每天凌晨 2 点"涉及日历 + 时区 + 夏令时，留到 §7 讨论。

### 2.2 `Instant` vs `SystemTime`（关键决策）

- **等待、超时、耗时、固定间隔** → 用 `tokio::time::Instant`（单调时钟，NTP 回拨也不倒退）。
- **写数据库、审计日志、跨进程、日历规则** → 用 `SystemTime` / UTC。

骨架里所有 `Instant` 都取自 `tokio::time::Instant`（**不是** `std::time::Instant`）。
这是故意的：`start_paused` 测试必须用它才能拿到被暂停的时钟。不要在进程间序列化 `Instant`，
它只在当前进程本次启动内有意义。持久化应存 `next_run_at` 这类墙上时钟时间。

### 2.3 fixed-rate vs fixed-delay

周期任务有两种"下一次何时开始"的算法：

```
fixed-delay（执行完再 sleep 一个周期）:  next_due = now + interval
fixed-rate （锚定计划槽位）:             next_due = previous_due + interval
```

Demo 用 **fixed-rate**。若用 fixed-delay，每次执行耗时都会让后续执行越来越晚。
fixed-rate 即使某次开始得晚，下一个 deadline 仍锚定原计划槽位。

### 2.4 `JobContext` 与幂等键

```rust
pub struct JobContext {
    pub scheduled_at: Instant,  // 计划槽位
    pub started_at: Instant,    // 真实开始
}
impl JobContext {
    pub fn delay(self) -> Duration {  // 晚了多久
        self.started_at.saturating_duration_since(self.scheduled_at)
    }
}
```

生产系统可用 `(job_id, scheduled_at)` 标识一个计划槽位，作为**幂等键**，防止同一次执行
重复产生副作用。跨进程 / 重启后要使用这个键时，`scheduled_at` 需要保存为持久化时间值。

### 2.5 策略枚举

```rust
pub enum MisfirePolicy { Skip, CatchUp { max_runs: usize } }
pub enum OverlapPolicy { Allow, SkipIfRunning }
```

- `Skip`：漏掉旧槽位，只跑最近一次。
- `CatchUp { max_runs }`：补跑最近 N 次（**必须有上限**，否则"每秒一次"停了三天会补 259200 次）。
- `Allow`：允许并发；`SkipIfRunning`：同一 Job 上一次没结束就跳过本次。

---

## 3. 你要实现的 TODO 清单

按实现难度/依赖顺序排列，建议顺序执行：

| # | 位置 | 内容 | 难度 |
|---|------|------|------|
| 1 | `deadline.rs` | `Ord` 反转比较（最小堆） | ★ |
| 2 | `scheduler.rs::new` | 校验配置、构造 | ★ |
| 3 | `scheduler.rs::add` | 注册任务 + 校验 | ★★ |
| 4 | `scheduler.rs::run_until` | 主循环（select!） | ★★★ |
| 5 | `scheduler.rs::dispatch_due` | 到期派发 + misfire 计算 | ★★★ |
| 6 | `scheduler.rs::start_ready` | 并发上限 + overlap + panic 隔离 | ★★★ |
| 7 | `scheduler.rs::handle_completion` / `discard_ready` / `drain_in_flight` | 收尾 | ★★ |
| 8 | `tests/scheduler_test.rs` | 补测试断言 | ★★ |

---

## 4. 逐步指导

### 4.1 `Deadline` 的 `Ord` —— 用 BinaryHeap 找最近的 deadline

`BinaryHeap` 默认是**最大堆**，先弹出 `cmp` 最大的元素。我们要**最小堆**（最早到期在堆顶），
所以反转比较方向：

```rust
impl Ord for Deadline {
    fn cmp(&self, other: &Self) -> Ordering {
        other.due_at.cmp(&self.due_at)
            .then_with(|| other.sequence.cmp(&self.sequence))
    }
}
```

要点：
- 比较 `other` 与 `self`（方向对调），`due_at` 更早的 deadline 反而 cmp 结果更大 → 被放到堆顶。
- 两个 deadline 相同时用 `sequence` 打平局，避免"相等"。

### 4.2 `Scheduler::new` / `add` —— 启动期校验

创建 / 注册时检查无效配置，启动就报错，避免运行后忙等或重复 ID 覆盖：

| 校验项 | 错误 |
|--------|------|
| 空 Job ID | `SchedulerError::EmptyJobId` |
| 重复 Job ID | `SchedulerError::DuplicateJobId(id)` |
| 零周期 | `SchedulerError::ZeroInterval` |
| `max_concurrency == 0` | `SchedulerError::ZeroMaxConcurrency` |
| `CatchUp { max_runs: 0 }` | `SchedulerError::ZeroCatchUpRuns` |

`add` 还要计算首次 deadline 并压入堆：

```rust
let first_due = Instant::now() + definition.schedule().first_delay();
// 分配 sequence，push Deadline::new(first_due, sequence, id)
```

### 4.3 `run_until` —— 主循环

这是调度器的心脏。三个事件用 `tokio::select!` 并发等待：

```rust
loop {
    let next_due = self.heap.peek().map(|d| d.due_at);

    tokio::select! {
        _ = &mut shutdown => {              // 1) 关闭信号
            self.discard_ready();
            break;
        }
        completed = self.in_flight.join_next(), if !self.in_flight.is_empty() => {
            self.handle_completion(completed);  // 2) 有任务跑完
        }
        _ = tokio::time::sleep_until(next_due), if next_due.is_some() => {
            self.dispatch_due(Instant::now());  // 3) 最近 deadline 到期
        }
    }

    self.start_ready();  // 每轮结束都尝试启动 ready 队列里的任务
}

self.drain_in_flight().await;  // 关闭后等已启动任务结束
self.report
```

注意：
- 不要给每个任务开一个永久 sleep task——任务多了注册/删除/关闭/统计要在多个 task 间协调。
  一个 scheduler loop 统一管所有 deadline 更好。
- `sleep_until(next_due)` 只有在 `next_due.is_some()` 时才参与 select。
- 堆的插入/弹出是 O(log n)，不必每隔几毫秒扫描全部任务。

### 4.4 `dispatch_due` —— misfire 计算

进程暂停 / runtime 繁忙会让调度器错过 deadline。假设周期 10s，恢复时已过 35s：

```
原 deadline：00s
已到期槽位：00s, 10s, 20s, 30s
下个 deadline：40s
```

到期数量的整数运算（**勿用 Duration 直接做除法**，用 as_secs/as_millis 后整数除）：

```rust
additional = (now - due_at) / interval        // 整秒除法，向下取整
total_due  = additional + 1
next_due   = due_at + total_due * interval    // 仍锚定原 deadline，fixed-rate
```

按 `MisfirePolicy` 决定保留哪些槽位：

- `Skip`：只保留 `due_at + additional * interval`（最近一个）。
- `CatchUp { max_runs }`：保留最近 `max_runs` 个。

每个保留的槽位生成一个 `Occurrence { job_id, scheduled_at, sequence }` 推入 `ready`；
被丢弃的计入 `report.skipped_misfires`。周期任务把 `next_due` 压回堆。

### 4.5 `start_ready` —— 并发上限 + overlap + panic 隔离

```rust
while self.in_flight.len() < self.config.max_concurrency {
    let Some(occurrence) = self.ready.pop_front() else { break };

    if job.overlap == SkipIfRunning && job.running > 0 {
        report.skipped_overlaps += 1;
        continue;
    }
    job.running += 1;
    // spawn ...
}
```

panic 隔离用 `catch_unwind`（来自 `futures::FutureExt`）：

```rust
let outcome = AssertUnwindSafe(handler.run(context))
    .catch_unwind()
    .await
    .map(|result| match result {
        Ok(()) => RunOutcome::Succeeded,
        Err(error) => RunOutcome::Failed(error),
    })
    .unwrap_or(RunOutcome::Panicked);
```

要点：
- `JoinSet::len()` 只能知道总共有多少 task 在跑；判断**同一个 Job** 是否重叠要看它自己的
  `running` 计数。
- 捕获 panic 是为了**隔离故障**：记入报告，scheduler loop 继续跑。出现 panic 仍要告警。
- `Err` 走 `Result`（数据库超时、参数错误、下游失败），panic 是程序不变量被破坏。

### 4.6 收尾三件套

- `discard_ready`：`ready.drain(..)`，计数累加到 `discarded_on_shutdown`。
- `handle_completion`：取出 `job_id` + `outcome`，`running` 减一，更新 report。
- `drain_in_flight`：`while let Some(c) = in_flight.join_next().await { ... }`。

**不要用 `abort_all`**：任务可能正在写库、上传文件、发消息，立刻取消后无法确认操作是否完成。
Demo 会一直等已启动任务结束（生产还需设 shutdown deadline，见 §7）。

### 4.7 优雅关闭顺序

```
停止从 deadline 堆产生新 occurrence
  → 丢弃尚未启动的 ready occurrence 并计数
  → 等待 JoinSet 中已启动任务结束
  → 返回 SchedulerReport
```

---

## 5. 运行与测试

```bash
cd scheduler-demo

# 运行 demo（预热缓存 + 清理 Session 两个任务，Ctrl-C 停止并输出统计）
cargo run --offline

# 编译检查
cargo check --offline

# 跑测试
cargo test --offline
```

测试用 Tokio 的暂停时钟，`#[tokio::test(start_paused = true)]` 会由 runtime 推进 sleep，
不需要真实等 5 秒。用 `tokio::time::advance(Duration)` 显式推进时间。

用真实 sleep 测试定时任务跑得慢，还容易受 CI 负载影响；暂停时钟后显式推进，可以直接
检查 deadline 前后、逾期、关闭竞态等边界。

### 测试用例应覆盖

| 测试 | 验证 |
|------|------|
| `one_shot_runs_once` | 一次性任务只跑一次 |
| `periodic_skip_misfired_slots` | Skip 保留最近槽位 |
| `catchup_limits_runs` | CatchUp 限制补跑次数 |
| `skip_if_running_prevents_overlap` | SkipIfRunning 防重叠 |
| `shutdown_waits_for_inflight` | 关闭等待任务完成 |
| `handler_panic_is_isolated` | panic 计入报告、调度器继续跑 |

---

## 6. 快速自查清单

实现完对照检查：

- [ ] 周期任务的 `next_due` 用 `previous_due + interval`（不是 `now + interval`）。
- [ ] `CatchUp` 有上限，整数运算得到到期数量。
- [ ] 同一个 Job 的重叠用自身 `running` 计数判断，不是 `JoinSet::len()`。
- [ ] 全局并发用 `max_concurrency` 限制，`while in_flight.len() < max` 才启动。
- [ ] panic 被 `catch_unwind` 捕获，不影响 scheduler loop。
- [ ] 关闭不 `abort_all`，等待已启动任务自然结束。
- [ ] 所有 `Instant` 用 `tokio::time::Instant`。
- [ ] 启动期校验了空 ID / 重复 ID / 零周期 / `max_concurrency=0` / `CatchUp{0}`。

---

## 7. 生产化还缺什么（文章结尾的讨论）

当前实现把任务定义和状态都放在**内存**里，仅适用于单进程。上生产要补：

### 7.1 重启与多实例

进程重启后一次性任务会丢失、周期基准重来；跑两个实例同一 Job 各执行一遍。要共同执行一份
计划，需要持久化并协调"到期槽位由谁执行"：

```
持久化 JobDefinition 和 next_run_at
  → 事务认领到期槽位（lease / SKIP LOCKED）
  → 写入唯一 execution(job_id, scheduled_at)
  → 提交到持久化工作队列
  → Worker 执行幂等 Handler
  → 记录成功 / 失败 / 租约续期 / 恢复状态
```

数据库唯一键保证同一槽位只建一个 execution，租约确定哪个节点负责，幂等业务键防重复投递。
仅用分布式锁不够——节点可能已执行完副作用、写完成状态前丢锁，接管节点仍会重试。跨进程和
网络就应该按**至少一次**执行设计，并让业务幂等。

### 7.2 ready 队列容量

Demo 的 `ready` 队列没有容量上限，任务产生得比执行快会在内存里越积越多。上线前按业务选：

- 给 ready 队列设最大长度，满时按 Job 统计丢弃；
- 合并同一 Job 的旧 occurrence，只保留最新一次；
- occurrence 写入持久化工作队列，由 Worker 独立消费；
- 按租户 / Job 配额做公平调度。

限制并发只能控制"同时执行多少"；要队列不再增长，还得减少进入、丢弃部分任务或扩容。

### 7.3 cron / 时区 / 夏令时

"每 24 小时一次" ≠ "每天当地时间 02:00"。后者遇夏令时会：某天 02:00 不存在、某个本地时间
出现两次、改时区规则后未来计划变化。日历规则交给成熟 cron/time 库解析；遇到不存在的本地
时间是跳过还是顺延、重复时间执行一次还是两次，由业务决定。规则里存 `Asia/Shanghai` 这类
IANA 时区名，单存 `+08:00` 偏移无法表达时区规则。到期时上次还没结束、暂停漏了几次，仍走
前面定义的 overlap / misfire 策略。

### 7.4 可观测性

`SchedulerReport` 要接入监控：错误、panic、超时、跳过次数、执行延迟。只看"任务有没有启动"
发现不了积压和漏执行。失败重试 Demo 也没做——周期决定业务原本计划何时执行，重试是某次
执行失败后的恢复，两者别混；需要重试时向后台任务队列提交带稳定 ID 的任务，由队列处理
退避和死信，Handler 保证幂等。

---

## 8. 系列文章回溯

本仓库里这几个 Rust demo 均出自「Rust 从零造系统 / 异步并发」系列微信文章（作者 billchen），
对应关系记录如下，方便回溯原文：

| 项目 | 来源文章 | 微信链接 |
|------|----------|----------|
| `thread-pool-demo` | 用 Rust 从零实现线程池：难点不是任务队列，是关闭 | https://mp.weixin.qq.com/s/3zlOvrNh6Z6xMimhNCBF9g |
| `scheduler-demo` | 用 Rust 实现一个定时任务调度器 | https://mp.weixin.qq.com/s/qe54RVLgnpdc7TtxQFSrsw |
| `task-queue-demo` | 用 Rust 实现一个带重试的后台任务队列 | https://mp.weixin.qq.com/s/4CuWk-HzpY05wNHrMXL8Nw |
| `reverse-proxy-demo` | 用 Rust 实现一个反向代理和负载均衡器 | https://mp.weixin.qq.com/s/H7lQxRahdTaAOJ11kH9ONw |
| `zero-copy-protocol-parser` | 用 Rust 实现一个零拷贝二进制协议解析器 | https://mp.weixin.qq.com/s/VQDF60awj6PCdPgDyho9cw |

> 原文全文已抓取并存到各项目目录下的 `ARTICLE.md`（含标题与链接，方便离线回溯）。
> 标题取自微信 `og:title`，与项目库注释里的说法略有出入（例如任务队列原文标题是
> "带重试的后台任务队列"），以表格为准。
