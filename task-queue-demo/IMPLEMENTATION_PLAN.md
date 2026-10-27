# 实现计划：Rust Tokio 进程内任务队列

> 来源文章：用 Tokio 实现进程内后台任务队列（背压、并发 Worker、错误分类、指数退避、死信、优雅排空）。
> 定位：教学 / 单进程场景，任务全在内存，进程崩溃会丢失。

## 1. 目标

一个可直接 `cargo run` / `cargo test` 的进程内任务队列，只做调度语义，不依赖 Redis/Kafka/数据库。

支持六项能力（对应六个可测试不变量）：

1. **背压** —— 队列容量有上限，满载时提交方等待。
2. **并发 Worker** —— 同时执行的任务不超过配置的并发数。
3. **错误分类** —— 只有临时错误重试，永久错误直接进死信。
4. **指数退避** —— 重试次数有上限，等待时间指数增长并封顶。
5. **延迟重试不占 Worker** —— 等待期间不占用并发槽位。
6. **优雅排空** —— 所有发送端关闭后，已接收任务和延迟重试排空再退出。

## 2. 模块结构

```
task-queue-demo/
├── Cargo.toml              # tokio(full) + async-trait + futures
├── IMPLEMENTATION_PLAN.md   # 本文件
└── src/
    ├── lib.rs              # 模块声明 + re-export
    ├── task.rs             # ✅ 已完成：Task / TaskError / TaskHandler
    ├── retry.rs            # ⬜ RetryPolicy::delay_for
    ├── client.rs           # ⬜ QueueClient::enqueue
    ├── queue.rs            # ⬜ Runner::run / handle_result / drain_due + build
    └── main.rs             # ⬜ 运行示例
```

## 3. 核心类型

| 类型 | 位置 | 说明 |
|------|------|------|
| `Task<T>` | task.rs ✅ | id + payload + attempt（从 1 起）+ 容量配额 permit |
| `TaskError` | task.rs ✅ | `Retryable(String)` / `Permanent(String)` |
| `TaskHandler<T>` | task.rs ✅ | `async fn handle(&self, &Task<T>) -> Result<(), TaskError>` |
| `RetryPolicy` | retry.rs | initial_delay / max_delay / max_attempts |
| `QueueConfig` | queue.rs | capacity / concurrency / retry |
| `QueueClient<T>` | client.rs | 可 Clone，Semaphore 背压提交 |
| `Runner<T, H>` | queue.rs | 调度器，四状态 |
| `DeadLetter<T>` | queue.rs | task + reason |
| `QueueReport<T>` | queue.rs | accepted / succeeded / retries_scheduled / dead_letters |

## 4. 六个不变量 → 测试映射

| # | 测试 | 不变量 |
|---|------|--------|
| 1 | 临时失败两次后成功 | 3 错误分类 |
| 2 | 永久失败不重试 | 3 |
| 3 | 达到 max_attempts 进死信 | 4 |
| 4 | 延迟重试不占唯一 Worker（断言执行顺序 a→b→a） | 5 |
| 5 | 实际并发不超配置 | 2 |
| 6 | Handler panic 隔离为死信 | 附加 |
| 7 | 指数退避增长并封顶 | 4 |
| 8 | 运行中+延迟中任务持续占容量配额 | 1 |

## 5. 待实现清单（按建议顺序）

### ① `retry.rs` — `delay_for`

**签名**：`pub fn delay_for(&self, next_attempt: u32) -> Duration`

**逻辑**：`initial_delay * 2^(next_attempt-2)`，结果不超过 `max_delay`。

```rust
let exponent = next_attempt.saturating_sub(2).min(31);
self.initial_delay
    .saturating_mul(1_u32 << exponent)
    .min(self.max_delay)
```

- `saturating_sub` / `saturating_mul` 防整数下溢 / 溢出。
- `min(31)` 限制移位位数。
- 初始 1s、上限 30s 时：attempt2→1s，3→2s，4→4s，5→8s，6→16s，7+→30s。

**验证**：`cargo test retry`

### ② `client.rs` — `enqueue`

**签名**：`pub async fn enqueue(&self, id, payload) -> Result<(), SendError<Task<T>>>`

**逻辑**：先拿容量配额，再构造任务并发送。

```rust
let permit = self.capacity.clone()
    .acquire_owned().await
    .expect("queue capacity semaphore is never closed");
let task = Task::new(id, payload, permit);
self.sender.send(task).await
```

- `OwnedSemaphorePermit` 跟着 `Task` 在各状态间移动，任务终态时 drop 归还配额。
- `acquire_owned` 满载时 `.await` 会等待（这就是背压）。

**验证**：`cargo test`（队列测试从 enqueue 的 panic 推进到 run）

### ③ `queue.rs` — `drain_due`

**签名**：`fn drain_due(&mut self)`

**逻辑**：把 scheduled 堆中已到期的任务移到 ready。

```rust
let now = Instant::now();
while let Some(s) = self.scheduled.peek() {
    if s.ready_at <= now {
        let s = self.scheduled.pop().unwrap();
        self.ready.push_back(s.task);
    } else {
        break;
    }
}
```

### ④ `queue.rs` — `handle_result`

**签名**：`fn handle_result(&mut self, mut task: Task<T>, result: Result<Result<(), TaskError>, Box<dyn Any + Send>>)`

**逻辑**：`result` 外层是 `catch_unwind` 的结果，`Err(_)` = panic。

```rust
match result {
    Ok(Ok(())) => { self.succeeded += 1; }
    Ok(Err(TaskError::Permanent(reason))) => {
        self.dead_letters.push(DeadLetter { task, reason });
    }
    Ok(Err(TaskError::Retryable(reason))) => {
        if task.attempt() >= self.retry.max_attempts() {
            self.dead_letters.push(DeadLetter { task, reason });
        } else {
            task.increment_attempt();
            let delay = self.retry.delay_for(task.attempt());
            let ready_at = Instant::now() + delay;
            self.retries_scheduled += 1;
            self.scheduled.push(Scheduled { ready_at, sequence: self.sequence, task });
            self.sequence += 1;
        }
    }
    Err(_) => {  // handler panic
        self.dead_letters.push(DeadLetter { task, reason: "handler panicked".into() });
    }
}
```

- 注意 `task` 声明为 `mut`（Retryable 分支要 `increment_attempt`）。
- `max_attempts` 是总执行次数（第一次也算），`attempt` 从 1 起，`attempt >= max_attempts` 即耗尽。

### ⑤ `queue.rs` — `run`

**签名**：`pub async fn run(mut self) -> QueueReport<T>`

**逻辑**：JoinSet 管理在飞任务，`select!` 三分支调度，排空后退出。

```rust
let mut in_flight = JoinSet::new();
let mut receiver_open = true;
loop {
    // fill：填满到并发上限
    while in_flight.len() < self.concurrency {
        let Some(task) = self.ready.pop_front() else { break };
        let handler = Arc::clone(&self.handler);
        in_flight.spawn(async move {
            let result = handler.handle(&task).catch_unwind().await;
            (task, result)
        });
    }

    let next_deadline = self.scheduled.peek().map(|s| s.ready_at);

    // 排空退出条件
    if !receiver_open && self.ready.is_empty()
        && self.scheduled.is_empty() && in_flight.is_empty() {
        break;
    }

    tokio::select! {
        submission = self.receiver.recv() => match submission {
            Some(task) => { self.accepted += 1; self.ready.push_back(task); }
            None => receiver_open = false,
        },
        completion = in_flight.join_next(), if !in_flight.is_empty() => {
            if let Some(Ok((task, result))) = completion {
                self.handle_result(task, result);
            }
        },
        _ = sleep_until(next_deadline.unwrap_or_else(Instant::now)),
            if next_deadline.is_some() => {
            self.drain_due();
        },
    }
}
QueueReport { accepted, succeeded, retries_scheduled, dead_letters }
```

**要点**：
- `catch_unwind`（`futures::FutureExt`）隔离 handler panic，`(task, result)` 一起返回，panic 时 task 不丢。
- `sleep_until` 分支用 `if next_deadline.is_some()` 守卫，scheduled 为空时不等待 deadline。
- 退出条件 = 发送端已关 + ready/scheduled/in_flight 全空（延迟重试会排空执行）。

**验证**：`cargo test`（测试 1~6、8）

### ⑥ `main.rs` — 运行示例

**逻辑**：定义 `EmailHandler`（实现 `TaskHandler<Email>`），构建队列（并发 2、max_attempts 4、初始退避 200ms），提交两个任务：
- `welcome-alice`：前两次 Retryable，第三次成功。
- `welcome-bob`：Permanent，第一次进死信。

打印最终报告（期望 `accepted=2 succeeded=1 retries=2 dead_letters=1`）。

**验证**：`cargo run`

## 6. 实现顺序与验证

依赖关系：`delay_for` ← `handle_result` ← `run`；`enqueue` 是入口；`run` 依赖 `drain_due`/`handle_result`。

建议顺序：**① delay_for → ② enqueue → ③ drain_due → ④ handle_result → ⑤ run → ⑥ main**

每完成一项跑一次 `cargo test`，观察对应测试逐个变绿。全部完成后：

```bash
cargo test   # 期望 9 passed
cargo run    # 期望打印 accepted=2 succeeded=1 retries=2 dead_letters=1
```
