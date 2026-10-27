# 用 Rust 实现一个带重试的后台任务队列

> 来源：微信公众平台 · billchen
> 原文链接：https://mp.weixin.qq.com/s/4CuWk-HzpY05wNHrMXL8Nw

---

所属：Rust 从零造系统 / 异步任务与可靠性

本文产物：一个可以直接运行的进程内后台任务队列，支持背压、并发 Worker、错误分类、指数退避、死信和优雅排空

后台任务队列往往从一行代码开始：

```
tokio::spawn(send_email());
```

邮件服务一旦短暂失败，几个问题马上会冒出来：任务放在哪里，什么时候重试，最多执行几次，等待重试时要不要占用 Worker，进程退出时还没完成的任务怎么处理？
我用 Tokio 写了一个进程内任务队列，任务生命周期如下：

```
提交
  -> 等待执行
  -> Worker 处理
       -> 成功
       -> 永久失败 -> 死信
       -> 临时失败 -> 延迟重试 -> 再次执行
       -> 重试耗尽 -> 死信
```

这份代码只讨论调度语义，不依赖 Redis、Kafka 或数据库，拉下来就能运行和测试。任务都在内存里，进程崩溃后会丢失，所以它适合教学和单进程场景，不适合作为跨机器的生产队列。

### 一、先把队列的边界写出来
我给这份实现写了六个可测试的不变量：
1. 队列容量有上限，满载时提交方等待，内存不会无限增长；

2. 同时执行的任务不会超过配置的并发数；

3. 只有临时错误会重试，永久错误直接进入死信；

4. 重试次数有上限，等待时间按指数增长并受最大值限制；

5. 等待重试的任务不占用 Worker；

6. 所有发送端关闭后，已经接收的任务和延迟重试会排空再退出。

max_attempts 表示总执行次数，第一次执行也算在里面。配置为 3 时，流程是：

```
attempt 1 -> retry
attempt 2 -> retry
attempt 3 -> dead letter
```

把它当成“第一次执行再加三次重试”，就会平白多调用一次下游。

### 二、任务 ID 和执行次数分开保存
Task 里保存稳定 ID、业务载荷和当前执行次数：

```
pub struct Task {
    id: String,
    payload: T,
    attempt: u32,
    _capacity_permit: OwnedSemaphorePermit,
}
```

重试只增加 attempt，任务 ID 保持不变：

```
task_id = welcome-alice, attempt = 1
task_id = welcome-alice, attempt = 2
task_id = welcome-alice, attempt = 3
```

稳定 ID 方便日志把多次执行串起来，也可以作为业务幂等键的一部分。这套队列按至少一次执行来设计：Handler 做完副作用、还没来得及返回成功就崩了，任务可能再次执行。队列层面无法替业务保证幂等。
发送邮件可以用业务事件 ID 做去重；创建订单应该依赖数据库唯一约束；扣款需要下游支持稳定的 Idempotency-Key。

### 三、错误分类决定重试策略
Handler 返回带语义的错误，先把临时失败和永久失败分开：

```
pub enum TaskError {
    Retryable(String),
    Permanent(String),
}
```

常见情况可以按下面处理：
错误
分类
动作
连接失败、503、临时限流
Retryable延迟后重试
参数不合法、收件人不存在
Permanent直接进入死信
认证失败、权限不足
通常是 Permanent
修复配置，不要持续请求
写请求超时、结果未知
不能仅凭超时分类
先查询结果或使用幂等键

业务处理器通过 trait 接入队列：

```
#[async_trait]
pub trait TaskHandler: Send + Sync + 'static
where
    T: Send + Sync + 'static,
{
    async fn handle(&self, task: &Task) -> Result;
}
```

队列只处理执行结果，不关心邮件、图片转换还是账单同步。接入新的任务类型时，调度器不用跟着改。

### 四、用指数退避拉开重试间隔
立即重试很容易把故障放大。下游已经过载时，Worker 失败得越快，下一次请求来得越密。
重试策略使用指数退避：

```
pub fn delay_for(&self, next_attempt: u32) -> Duration {
    let exponent = next_attempt.saturating_sub(2).min(31);
    self.initial_delay
        .saturating_mul(1_u32 初始延迟设为 1 秒、上限设为 30 秒时，等待时间为：

```
attempt 2: 1s
attempt 3: 2s
attempt 4: 4s
attempt 5: 8s
...
最大不超过 30s
```

saturating_sub、saturating_mul 和指数上限用来挡住整数下溢和溢出。生产系统还要加随机抖动，避免一批同时失败的任务在同一毫秒再次唤醒；下游返回可信的 Retry-After 时，也应把它纳入调度。

### 五、只限制 channel，任务总量仍然会失控
最直观的背压写法是：

```
let (sender, receiver) = mpsc::channel(config.capacity);
```

调度器把任务从 channel 取走后，任务就不再占用 channel 容量。它可能正在执行，也可能躺在延迟重试堆里。只限制 channel 的话，生产者仍能持续提交，延迟集合会一直长大。
我的做法是让每个新任务先拿一个 Semaphore 配额：

```
let permit = Arc::clone(&self.capacity)
    .acquire_owned()
    .await
    .expect("queue capacity semaphore is never closed");

self.sender
    .send(Task::new(id.into(), payload, permit))
    .await?;
```

OwnedSemaphorePermit 跟着 Task 在这些状态之间移动：

```
mpsc -> ready -> in_flight -> scheduled -> ready -> ... -> terminal
```

任务成功、进入死信或被释放时，配额才会归还。这样 capacity 会覆盖队列里所有未结束的任务，包括等待 recv、正在执行和延迟重试的任务。
enqueue().await 满载时会等待，适合允许背压的内部调用。HTTP API 如果不能长等，可以在外层加提交超时，超时后返回 429 或 503。

### 六、延迟重试不要占住 Worker
下面的写法能跑，但会白白占住执行容量：

```
// 不推荐：Worker 在等待期间不能处理其他任务
tokio::time::sleep(delay).await;
handle(task).await;
```

100 个 Worker 因限流一起等 30 秒时，新到达的正常任务也只能排队。
实现使用 BinaryHeap 保存延迟任务：

```
struct Scheduled {
    ready_at: Instant,
    sequence: u64,
    task: Task,
}
```

Rust 的 BinaryHeap 默认先弹出最大值，所以 Ord 里反转 ready_at 的比较，让最早到期的任务在堆顶。sequence 用来稳定地区分相同到期时间，也就不需要业务载荷 T 实现 Ord。
调度器只等待堆顶 Deadline：

```
let next_deadline = scheduled.peek().map(|item| item.ready_at);

tokio::select! {
    submission = receiver.recv() => { /* 接收新任务 */ }
    completion = in_flight.join_next() => { /* 处理执行结果 */ }
    _ = sleep_until(deadline), if can_wake_retry => { /* 回到循环搬运任务 */ }
}
```

时间到了，所有到期任务从 scheduled 移到 ready。它们等待期间不占 JoinSet 的并发槽位，其他任务可以继续跑。

### 七、JoinSet 负责并发限制和回收
Runner 维护四个状态：

```
receiver   新提交但尚未接收的任务
ready      可以立即执行的任务
in_flight  正在 Handler 中执行的任务
scheduled  等待下一次重试时间的任务
```

只有 in_flight.len() < concurrency 时才会启动新任务：

```
while in_flight.len() 任务完成后，Runner 拿到原 Task 和结果，统一决定成功、重试还是进死信。由调度器修改 attempt，每种业务 Handler 就不用各自解释重试次数。
完整源码还用 catch_unwind 隔离 Handler panic。panic 会进死信，Runner 还能继续处理其他任务。这只是最后一道防线，panic 仍然是代码缺陷，需要告警和修复，不能按普通业务错误处理。

### 八、失败任务进入死信
三种情况会进入死信：

```
永久错误
可重试错误但 attempt 已达到 max_attempts
Handler panic
```

教学实现把死信放进最终的 QueueReport：

```
pub struct DeadLetter {
    pub task: Task,
    pub reason: String,
}

pub struct QueueReport {
    pub accepted: usize,
    pub succeeded: usize,
    pub retries_scheduled: usize,
    pub dead_letters: Vec>,
}
```

生产系统要把死信持久化，至少记录 task ID、任务类型、载荷引用、执行次数、最后错误、首次创建时间和最后失败时间。还要能查询、告警、修复后重放和审计，否则死信只会变成一个没人看的失败目录。

### 九、关闭时把任务排空
QueueClient 可以 Clone，多个生产者共享一个队列。最后一个 Client 被 drop 后，Tokio channel 返回 None。Runner 会停止接收新任务，但不会立刻退出。
退出条件是：

```
if !receiver_open
    && ready.is_empty()
    && scheduled.is_empty()
    && in_flight.is_empty()
{
    break;
}
```

已经安排的延迟重试仍会执行。示例这样关闭：

```
drop(client);
let report = worker.await.expect("queue runner did not panic");
```

真实服务还要处理排空 Deadline。某个任务如果要在一小时后重试，部署不可能一直等着；持久化队列可以保存状态后退出，纯内存队列只能继续等待，或取消并丢失任务。持久化属于可靠性要求。

### 十、运行示例
示例队列的并发数是 2，最多执行 4 次，初始退避 200 毫秒。代码提交两个邮件任务：

```
welcome-alice  前两次临时失败，第三次成功
welcome-bob    参数永久错误，第一次就进入死信
```

运行：

```
cd workspaces/task-queue-demo
cargo run
```

日志会打印稳定的 task ID、执行次数和重试延迟，最后得到：

```
accepted=2 succeeded=1 retries=2 dead_letters=1
```

### 十一、把失败路径也跑一遍
运行：

```
cargo test
```

测试覆盖八种行为：
1. 临时失败两次后能够成功；

2. 永久失败不会重试；

3. 达到最大次数后进入死信；

4. 延迟重试不会占用唯一的 Worker；

5. 实际并发数不会超过配置；

6. Handler panic 被隔离为死信；

7. 指数退避按预期增长并封顶；

8. 运行中和延迟中的任务都持续占用容量配额。

第四项会记录真实执行顺序：

```
retrying:1 -> ready:1 -> retrying:2
```

如果实现成 Worker 内部 sleep，顺序就会变成：

```
retrying:1 -> retrying:2 -> ready:1
```

第四个测试看的是调度结果：重试等待时，唯一的 Worker 有没有被占住。

### 十二、离生产队列还差哪些能力
当前实现的边界写在下面：

```
已有：进程内提交、全生命周期背压、有限并发、延迟重试、死信、排空
没有：持久化、崩溃恢复、多进程 Worker、任务租约、心跳、超时回收
没有：优先级、公平调度、按租户限额、取消、Deadline、管理 API
没有：持久化死信、指标面板、Trace、手动重放、Schema 版本迁移
```

要把它演进成持久化队列，核心状态通常会变成：

```
Queued
Running(worker_id, lease_until)
RetryScheduled(next_attempt_at)
Succeeded
DeadLettered
```

Worker 认领任务时要原子地写入租约。进程崩溃后，Supervisor 扫描过期租约并重新调度。任务可能已经完成外部副作用，仍要依赖幂等键或结果查询，不能看到租约过期就认定任务没有执行。
数据库实现可以用 FOR UPDATE SKIP LOCKED 认领任务，Redis 可以用 Streams 和 Consumer Group，Kafka/NATS 由 Broker 负责消费确认和重新投递。底层实现不同，错误分类、尝试预算、延迟调度、背压和幂等边界仍然要保留。

### 十三、收尾
后台任务队列要先把失败和等待期间的所有权定义清楚，再把 Future 放进 tokio::spawn：
1. 容量覆盖完整生命周期：等待、执行和延迟重试都要占用配额；

2. 错误先分类再重试：永久错误不会因重复执行而消失；

3. 重试释放 Worker：保存下次执行时间，不在工作协程里长时间 sleep；

4. 任务身份保持稳定：attempt 变化，task ID 和幂等键不变；

5. 终态必须可处理：成功有记录，失败有死信，关闭时有明确排空语义；

6. 内存调度不等于可靠交付：崩溃恢复需要持久化、租约和业务幂等共同完成。

重试会改变系统的流量、延迟、资源占用和副作用次数。把这些边界写成显式状态，再用测试锁住，后台任务的行为才有办法预期。
