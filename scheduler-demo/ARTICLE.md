# 用 Rust 实现一个定时任务调度器

> 来源：微信公众平台 · billchen
> 原文链接：https://mp.weixin.qq.com/s/qe54RVLgnpdc7TtxQFSrsw

---

所属：Rust 从零造系统 / 异步并发 / 任务调度

每隔 5 分钟清理一次过期 Session，服务启动 30 秒后预热缓存。遇到定时任务，很容易从一个 sleep 循环写起：

```
loop {
    tokio::time::sleep(Duration::from_secs(300)).await;
    cleanup().await;
}
```

这段代码能清理 Session，但两次开始之间的间隔会超过 5 分钟。假如 cleanup() 执行了 20 秒，下次就要等到本次开始的 5 分 20 秒后。
再往下写，还会碰到几个问题。进程暂停了 20 分钟，恢复后该补跑四次，还是只跑一次？任务执行时间超过了周期，下次到点时要不要再启动一个？多个任务各自开一个永久 Tokio task，并发数量和关闭过程又由谁来管？
这篇文章用 Rust 写一个进程内调度器。调度层负责算出哪次执行到期了，执行层负责运行和统计。下面把计划中的一次执行称为 occurrence。

```
调度层：何时应该产生一次 occurrence
  - Schedule
  - deadline 最小堆
  - misfire / overlap policy
             │
             ▼
执行层：这一次 occurrence 怎样运行
  - JoinSet
  - 全局并发上限
  - panic 隔离
  - 运行结果统计
```

Demo 先处理固定间隔和一次性延迟。每天生成报表这类日历需求，留到后面讨论 cron、时区和夏令时。

### 一次性任务和周期任务
时间规则用 Schedule 表示：

```
pub enum Schedule {
    Once {
        after: Duration,
    },
    Every {
        interval: Duration,
        start_after: Duration,
    },
}
```

一次性任务在调度器启动后的某个延迟执行：

```
Schedule::once(Duration::from_secs(30))
```

周期任务默认等一个完整周期再执行第一次：

```
Schedule::every(Duration::from_secs(300))
```

也可以启动后立即执行，然后每隔固定周期执行：

```
Schedule::every_immediately(Duration::from_secs(300))
```

这两种规则都按相对时间调度，可以用来做心跳、清理和轮询。“每天凌晨 2 点”还涉及日历和时区，需要单独计算执行时间。

### 等待任务到期，用 Instant
调度器需要知道距离下次执行还剩多久，这里用 Tokio 的 Instant 计算：

```
let start = Instant::now();
let first_due = start + first_delay(schedule);
tokio::time::sleep_until(first_due).await;
```

SystemTime 对应现实中的时钟，可能被 NTP 校时或管理员调整。Instant 是单调时钟，系统时间往回调也不会跟着倒退，所以等待、超时、耗时和固定间隔都用它计算。
需要把时间写进数据库、记入审计日志、传给其他进程，或者计算日历规则时，再用 SystemTime 或 UTC 时间。
如果数据库保存的是 next_run_at = 2026-08-22T02:00:00+08:00，恢复时先用墙上时钟判断它是否已经到期，再转换成当前进程内的等待 deadline。不要把 Instant 序列化，它只在当前进程和当前启动期间有意义。

### 从计划时间算下一个周期
假设任务周期是 60 秒，每次执行 10 秒。
如果执行完再 sleep 一个周期，得到的是 fixed-delay：

```
00:01 开始 -> 00:01:10 完成 -> sleep 60s
00:02:10 开始 -> 00:02:20 完成 -> sleep 60s
00:03:20 开始
```

如果想要每分钟开始一次，这种写法就会越跑越晚，每轮都多算了任务的执行时间。Demo 采用 fixed-rate，从上一次计划执行的时间推算下一次：

```
计划槽位：00:01, 00:02, 00:03, 00:04
实际开始：可能稍晚，但下一个 deadline 仍锚定计划槽位
```

对应的计算是：

```
next_due = previous_due + interval;
```

如果改成下面这样，下次执行时间就会受当前处理时刻影响：

```
next_due = Instant::now() + interval;
```

每次执行都会收到计划时间和实际开始时间，两者相减就能知道晚了多久：

```
pub struct JobContext {
    pub scheduled_at: Instant,
    pub started_at: Instant,
}

impl JobContext {
    pub fn delay(self) -> Duration {
        self.started_at.saturating_duration_since(self.scheduled_at)
    }
}
```

计划时间也能用来区分同一个 Job 的不同次执行。生产系统可以用 (job_id, scheduled_at) 标识一个计划槽位，作为幂等键，防止同一次执行重复产生副作用。跨进程或重启后还要使用这个键时，scheduled_at 需要保存为持久化的时间值，不能直接用这里的 Instant。

### 用 BinaryHeap 找到最近的 deadline
给每个任务开一个永久 sleep task，写起来很直接。任务多了，注册、删除、关闭和状态统计就要在多个 task 之间协调。这里用一个 scheduler loop 管理所有 deadline。
Rust 的 BinaryHeap 默认是最大堆，而调度器需要最小 deadline。通过反转 Ord 比较方向，把最早时间放到堆顶：

```
impl Ord for Deadline {
    fn cmp(&self, other: &Self) -> Ordering {
        other
            .due_at
            .cmp(&self.due_at)
            .then_with(|| other.sequence.cmp(&self.sequence))
    }
}
```

两个 deadline 相同时，再按 sequence 排序。
主循环等待关闭信号、正在运行的任务结束，或者最近的 deadline 到达：

```
tokio::select! {
    _ = &mut shutdown => break,
    completion = in_flight.join_next(), if !in_flight.is_empty() => {
        finish_run(completion, ...);
    }
    _ = tokio::time::sleep_until(next_due), if next_due.is_some() => {}
}
```

最近的 deadline 到达后，循环取出堆中所有到期任务，再计算周期任务的下一个 deadline。每次插入和弹出的复杂度是 O(log n)，不用每隔几毫秒扫描全部任务。

### 进程暂停后，漏掉的任务怎么算
机器休眠、runtime 繁忙、进程被暂停，都可能让调度器错过执行时间。假设一个任务每 10 秒执行一次，调度器恢复时，距离原 deadline 已经过了 35 秒：

```
原 deadline：00s
已到期槽位：00s, 10s, 20s, 30s
下个 deadline：40s
```

这种错过计划时间的情况叫 misfire。Demo 提供 Skip 和有上限的 CatchUp：

```
pub enum MisfirePolicy {
    Skip,
    CatchUp { max_runs: usize },
}
```

Skip 丢掉旧槽位，只保留最近一次：

```
执行：30s
跳过：00s, 10s, 20s
```

有上限的 CatchUp { max_runs: 2 } 保留最近两个：

```
执行：20s, 30s
跳过：00s, 10s
```

CatchUp 要有上限。一个“每秒一次”的任务停了三天，如果全部补跑，恢复时就会一下生成 259200 次执行。
到期数量通过整数计算得到：

```
additional = floor((now - due_at) / interval)
total_due = additional + 1
next_due = due_at + total_due * interval
```

下个 deadline 仍然从原 deadline 往后推，补跑不会改变原来的周期。

### 上一次还没跑完，下一次又到了
调度器准时醒来也可能遇到麻烦：上一次任务还没结束，下一次已经到点了。是否允许两次执行重叠，由 overlap 策略决定。

```
pub enum OverlapPolicy {
    Allow,
    SkipIfRunning,
}
```

假设报表任务每分钟运行一次，但一次要 90 秒：

```
Allow
00:01 run A ─────────────────
00:02           run B ─────────────────

SkipIfRunning
00:01 run A ─────────────────
00:02           skip
00:03                    run C ─────────────────
```

缓存刷新或独立分片任务可以考虑允许并发。账单结算、全量同步，以及需要占用排他锁的任务，默认用 SkipIfRunning，避免上一次没结束就启动下一次。
调度器为每个 Job 保存 running 数量：

```
if job.overlap == OverlapPolicy::SkipIfRunning && job.running > 0 {
    report.skipped_overlaps += 1;
    continue;
}

job.running += 1;
```

任务完成后，running 减一。JoinSet::len() 只能告诉我们总共有多少任务在运行，判断同一个 Job 是否重叠，还得看它自己的计数。

### 并发有上限，排队也要考虑容量
即使每个 Job 都允许重叠，也不能到点就一直 spawn。Demo 用 max_concurrency 限制全局并发：

```
pub struct SchedulerConfig {
    pub max_concurrency: usize,
}
```

只有存在空闲执行位时，调度器才从 ready 队列启动任务：

```
while in_flight.len() 这样可以限制同时运行的 Tokio task 数，减少对数据库连接和下游服务的争抢。但 Demo 的 ready 队列还没有容量上限，任务产生得比执行快，仍然会在内存里越积越多。
上线前需要决定排队任务怎么处理，可以按业务选择：
• 为 ready 队列设最大长度，满时按 Job 统计丢弃；

• 合并同一 Job 的旧 occurrence，只保留最新一次；

• 把 occurrence 写入持久化工作队列，由 Worker 独立消费；

• 根据租户和 Job 配额做公平调度。

如果任务长期积压，限制并发只能控制同时执行的数量。要让队列不再增长，还得减少任务进入、丢弃部分任务，或者扩容。

### Handler 的错误和 panic 怎么处理
业务任务通过 trait 接入：

```
#[async_trait]
pub trait JobHandler: Send + Sync + 'static {
    async fn run(&self, context: JobContext) -> Result;
}
```

调度器使用 Arc<dyn JobHandler> 保存不同类型的 Job，并用 JoinSet 跟踪运行实例。每次执行都捕获 panic：

```
let outcome = AssertUnwindSafe(handler.run(context))
    .catch_unwind()
    .await
    .map(|result| match result {
        Ok(()) => RunOutcome::Succeeded,
        Err(error) => RunOutcome::Failed(error),
    })
    .unwrap_or(RunOutcome::Panicked);
```

捕获到的 panic 会记入报告，scheduler loop 继续运行。报告也会记录成功、失败，以及因漏执行、重叠和关闭而跳过的数量：

```
pub struct SchedulerReport {
    pub started: u64,
    pub succeeded: u64,
    pub failed: u64,
    pub panicked: u64,
    pub skipped_misfires: u64,
    pub skipped_overlaps: u64,
    pub discarded_on_shutdown: u64,
}
```

数据库超时、参数错误、下游请求失败，都应该通过 Result 返回。捕获 panic 是为了隔离故障；出现 panic 仍然需要告警，检查程序的不变量在哪里被破坏了。
Demo 没有实现失败重试。周期决定业务原本计划何时执行，重试处理某一次执行失败后的恢复。如果直接把重试当成下一个周期，就很难判断它属于哪个计划槽位。需要重试时，Job 可以向 105 的后台任务队列提交带稳定 ID 的任务，由队列处理退避和死信，业务 Handler 保证幂等。

### 把时间规则和执行策略一起注册
任务定义把时间规则和执行策略放在一起：

```
let mut scheduler = Scheduler::new(SchedulerConfig {
    max_concurrency: 4,
})?;

scheduler.add(
    JobDefinition::new(
        "cleanup-sessions",
        Schedule::every(Duration::from_secs(300)),
        CleanupJob,
    )
    .misfire_policy(MisfirePolicy::Skip)
    .overlap_policy(OverlapPolicy::SkipIfRunning),
)?;
```

创建调度器和注册任务时，会检查以下无效配置：
• 空 Job ID；

• 重复 Job ID；

• 零周期；

• max_concurrency = 0；

• CatchUp { max_runs: 0 }。

这些配置在启动时就会报错，避免运行后才出现忙等，或者重复 ID 覆盖已有任务。

### 收到关闭信号后，等待已启动的任务
主程序把 Ctrl-C Future 传给调度器：

```
let report = scheduler
    .run_until(async {
        if let Err(error) = tokio::signal::ctrl_c().await {
            tracing::error!(%error, "failed to listen for Ctrl-C");
        }
    })
    .await;
```

收到关闭信号后，Demo 按下面的顺序退出：

```
停止从 deadline 堆产生新 occurrence
    -> 丢弃尚未启动的 ready occurrence，并计数
    -> 等待 JoinSet 中已经启动的任务结束
    -> 返回 SchedulerReport
```

这里没有直接调用 abort_all。任务可能正在写数据库、上传文件或发布消息，立刻取消后，可能无法确认操作到底完成了没有。
Demo 会一直等已启动的任务结束，生产服务还需要设置 shutdown deadline。到期后取消剩余任务，再通过幂等键或状态表处理重启后的恢复。即使调度器能取消任务，已经写入数据库或发出的消息也不会自动撤回。

### 运行 Demo 和测试
运行 Demo：

```
cd workspaces/scheduler-demo
cargo run --offline
```

示例注册了两个任务：启动 1 秒后预热一次缓存，以及每 5 秒清理一次 Session。按 Ctrl-C 后停止派发，并输出最终统计。
执行测试：

```
cargo test --offline
```

测试使用 Tokio 的暂停时间：

```
#[tokio::test(start_paused = true)]
async fn one_shot_runs_once() {
    // 调度器中的 sleep 会由测试 runtime 推进，不需要真实等待 5 秒。
}
```

配套测试覆盖一次性任务只运行一次、关闭等待任务完成，以及 Skip 保留最近槽位、CatchUp 限制补跑次数、SkipIfRunning 防止同一 Job 重叠。Handler panic 也有测试，确认它会计入报告，调度器还能继续运行。
用真实 sleep 测试定时任务，跑得慢，还容易受 CI 负载影响。暂停时钟后显式推进时间，可以直接检查 deadline 前后、逾期和关闭竞态等边界。

### 重启和多实例运行，还缺哪些处理
当前实现把任务定义和状态都放在内存里。进程重启后，一次性任务会丢失，周期基准也会重新开始。运行两个实例，相同 Job 就会被各执行一遍；扩到三个实例，也就执行三遍。只有业务本来就要求每个实例各跑一次时，这种行为才符合预期。
如果多个实例要共同执行一份计划，还需要保存任务状态，并协调到期任务由谁执行：

```
持久化 JobDefinition 和 next_run_at
    ↓
事务认领到期槽位（lease / SKIP LOCKED）
    ↓
写入唯一 execution(job_id, scheduled_at)
    ↓
提交到持久化工作队列
    ↓
Worker 执行幂等 Handler
    ↓
记录成功、失败、租约续期与恢复状态
```

数据库唯一键保证同一槽位只创建一个 execution，租约确定当前由哪个节点负责，幂等业务键防止重复投递产生重复副作用。少了其中一项，另外两项也补不上。
仅使用分布式锁也不够。节点可能已经执行完副作用，但在写完成状态前失去锁；接管节点仍会重试。只要系统跨越进程和网络，就应该按至少一次执行设计，并让业务幂等。

### 接入 cron 后，仍要处理时区和夏令时
“每 24 小时一次”和“每天当地时间 02:00”不是同一个规则。后者遇到夏令时会出现：
• 某天的 02:00 根本不存在；

• 某个本地时间出现两次；

• 修改时区规则后，未来计划发生变化。

日历规则可以交给成熟的 cron/time 库解析。遇到不存在的本地时间，是跳过还是顺延；遇到重复时间，是执行一次还是两次，仍然要由业务决定。规则里需要保存 Asia/Shanghai 这样的 IANA 时区名，单存一个固定的 +08:00 偏移无法表达时区规则。
cron 库算出下一个日历时间，调度器据此等待和派发。到期时上次任务还没结束，或者进程暂停期间漏了几次执行，仍然按前面定义的 overlap 和 misfire 策略处理。
目前这个 Demo 能在单进程内按计划派发任务，限制补跑和并发，并在关闭时等待已启动的任务。用在生产环境，还缺 ready 队列容量、关闭等待期限和持久化恢复。运行报告也需要接入监控，记录错误、panic、超时、跳过次数和执行延迟；只看任务有没有启动，发现不了积压和漏执行。
