# 用 Rust 从零实现线程池 —— 实现指导

> 本文对应微信文章《用 Rust 从零实现线程池：难点不是任务队列，是关闭》（作者 billchen）。
> 骨架已搭好，类型、模块、demo、测试全部就位，**核心逻辑留给你实现**。
> 全文按"概念 → 对应文件 → 你要做什么 → 参考答案"组织，读完即可逐处填 `todo!()`。

---

## 1. 整体架构

线程池分两侧：生产者把任务塞进队列，固定数量的消费者（工人）从队列取任务执行。

```
生产者（提交方）
- execute / try_execute
- 有界队列 BoundedQueue（背压）
        │
        ▼
消费者（固定工人）
- Worker 循环 recv
- panic 隔离（catch_unwind）
- 毒锁恢复（poisoned.into_inner）
- 优雅关闭 / 超时关闭
```

文章的核心观点是：**难点不在任务队列，在三件事——有界队列（背压）、panic 隔离 / 毒锁恢复、关闭语义。**

### 项目结构

```
thread-pool-demo/
├── Cargo.toml              # 无外部依赖，纯标准库
├── GUIDE.md                ← 本文
├── ARTICLE.md              # 原文全文（含标题与链接，方便离线回溯）
├── src/
│   ├── lib.rs              # 模块声明 + 公开 re-export
│   ├── main.rs             # demo 入口：提交 8 个任务，优雅关闭
│   ├── job.rs              # ✅ 已完成：Job 类型别名
│   ├── error.rs            # ✅ 已完成：PoolError
│   ├── queue.rs            # ⛳ 待实现：BoundedQueue::push / pop
│   ├── worker.rs           # ⛳ 待实现：Worker::new（核心循环）
│   └── pool.rs             # ⛳ 待实现：ThreadPool（核心）
└── tests/
    └── pool_test.rs        # ⛳ 待实现：测试断言（脚手架已备好）
```

✅ = 已写好，可直接用；⛳ = 留给你实现的地方（搜 `todo!`）。

---

## 2. 已完成的类型说明（理解它们再动手）

### 2.1 `Job` —— 任务

```rust
pub type Job = Box<dyn FnOnce() + Send + 'static>;
```

一个 box 起来的、可 `Send` 的、只跑一次的闭包。`FnOnce` 允许 move 捕获大对象；
`Send + 'static` 允许跨线程移动。因为它是 trait object，工人无需知道具体闭包类型。

### 2.2 `PoolError` —— 提交失败

```rust
pub enum PoolError { PoolClosed }
```

`try_execute` 用它明确告诉调用方"池已关闭"，而不是静默丢任务。

### 2.3 `BoundedQueue<T>` —— 有界队列（背压）

```rust
pub struct BoundedQueue<T> {
    inner: Mutex<VecDeque<T>>,
    not_empty: Condvar,  // 消费者等这个
    not_full: Condvar,   // 生产者等这个
    capacity: usize,
}
```

两个条件变量一个管"空"一个管"满"。`push` 满时阻塞，`pop` 空时阻塞——这就是背压，
把"内存无限涨"变成"上游变慢"。

### 2.4 `Worker` / `ThreadPool`

两个 struct 的字段（`id`/`handle`，`workers`/`sender`）已定义，构造与循环留给你（见 §4）。

---

## 3. 你要实现的 TODO 清单

按实现难度/依赖顺序排列，建议顺序执行：

| # | 位置 | 内容 | 难度 |
|---|------|------|------|
| 1 | `queue.rs` | `push` / `pop`（条件变量背压） | ★★ |
| 2 | `worker.rs` | `Worker::new`（recv 循环 + panic 隔离 + 毒锁恢复） | ★★★ |
| 3 | `pool.rs` | `ThreadPool::new`（channel + Arc + spawn） | ★★ |
| 4 | `pool.rs` | `execute` / `try_execute`（提交任务） | ★ |
| 5 | `pool.rs` | `Drop`（优雅关闭） | ★★ |
| 6 | `pool.rs` | `shutdown_timeout`（超时关闭） | ★★★ |
| 7 | `tests/pool_test.rs` | 补测试断言 | ★★ |

---

## 4. 逐步指导

### 4.1 `BoundedQueue::push` / `pop` —— 条件变量背压

`mpsc::channel()` 是无界的，生产者多快都能塞进去，内存无限涨——这是 OOM 的经典来源。
标准库没有有界通道，得自己写：`Mutex<VecDeque<T>>` + 两个条件变量。

```rust
fn push(&self, item: T) {
    let mut q = self.inner.lock().unwrap();
    while q.len() == self.capacity {
        q = self.not_full.wait(q).unwrap(); // 队列满，阻塞生产者
    }
    q.push_back(item);
    self.not_empty.notify_one();
}

fn pop(&self) -> T {
    let mut q = self.inner.lock().unwrap();
    while q.is_empty() {
        q = self.not_empty.wait(q).unwrap(); // 队列空，阻塞消费者
    }
    let item = q.pop_front().unwrap();
    self.not_full.notify_one();
    item
}
```

要点：
- 判断用 `while` 不是 `if`——`wait` 可能被**虚假唤醒**（spurious wakeup），醒来后要重新检查条件。
- `push` 满时让出锁阻塞；`pop` 空时同样。一个 notify 唤醒一个等待者（`notify_one` 够用）。

### 4.2 `Worker::new` —— recv 循环 + panic 隔离 + 毒锁恢复

这是工人线程的心脏，一段循环要做三件事：

```rust
let handle = thread::spawn(move || loop {
    // 1) 恢复毒化锁，而不是 unwrap() 直接炸
    let guard = match receiver.lock() {
        Ok(g) => g,
        Err(poisoned) => poisoned.into_inner(),
    };
    // 2) recv 阻塞，直到有任务或所有 sender 被丢弃
    match guard.recv() {
        Ok(job) => {
            // 3) catch_unwind 保住工人
            if std::panic::catch_unwind(std::panic::AssertUnwindSafe(job)).is_err() {
                eprintln!("worker task panicked, keeping worker alive");
            }
        }
        Err(_) => break, // 发送端已关闭，退出循环
    }
});
Self { id, handle: Some(handle) }
```

要点：
- **毒锁恢复**：只要持锁期间发生 panic，Mutex 就被"毒化"，后续 `lock()` 都返回 `Err`。
  用 `poisoned.into_inner()` 拿回数据继续用；直接 `.unwrap()` 会让整个池瞬间瘫痪。
- **退出信号**：`recv()` 返回 `Err` 表示所有 `Sender` 已丢弃，`break` 退出。
- **panic 隔离**：`job()` 若 panic，工人线程会死——池不会重建它，池子越来越小（静默减员）。
  `catch_unwind` 接住后工人继续循环。`AssertUnwindSafe` 是明确告诉编译器"跨 panic 边界的
  不一致状态我负责"。

> 已知性能问题：`receiver.lock()` 拿锁后 `recv()` 会一直阻塞持有这把锁，同一时刻其实只有
> 一个工人在等任务。标准库文档对此有专门提示。真正高性能的池用无锁队列或每线程一队列
> （work stealing），见 §7。

### 4.3 `ThreadPool::new` —— channel + Arc + spawn

```rust
assert!(size > 0);
let (sender, receiver) = mpsc::channel::<Job>();
let receiver = Arc::new(Mutex::new(receiver));

let workers = (0..size)
    .map(|id| Worker::new(id, Arc::clone(&receiver)))
    .collect();

Self { workers, sender: Some(sender) }
```

要点：`mpsc::Receiver` 不能克隆，多个工人要共享同一接收端只能加锁（`Arc<Mutex<..>>`）。

### 4.4 `execute` / `try_execute` —— 提交任务

`send` 会失败：如果所有 worker 都退出了，接收端就没了。这时任务其实被丢弃，业务上必须
有个说法。两种接口：

```rust
// 快速路径：忽略 send 错误
pub fn execute<F: FnOnce() + Send + 'static>(&self, f: F) {
    let job: Job = Box::new(f);
    let _ = self.sender.as_ref().unwrap().send(job);
}

// 明确失败：不静默丢任务
pub fn try_execute<F: FnOnce() + Send + 'static>(&self, f: F) -> Result<(), PoolError> {
    let job: Job = Box::new(f);
    self.sender
        .as_ref()
        .ok_or(PoolError::PoolClosed)?
        .send(job)
        .map_err(|_| PoolError::PoolClosed)
}
```

要点：一个"提交成功但永远不执行"的任务，比一个返回错误的失败更难排查。`try_execute`
把"池已关闭"显式抛给调用方，让它决定是否降级。

### 4.5 `Drop` —— 优雅关闭

```rust
fn drop(&mut self) {
    // 先丢弃 sender，让 recv 返回 Err
    drop(self.sender.take());
    // 再等所有工人处理完剩余任务并退出
    for worker in &mut self.workers {
        if let Some(handle) = worker.handle.take() {
            handle.join().unwrap();
        }
    }
}
```

顺序很关键：`drop(sender)` → `recv()` 返回 `Err` → 工人**处理完当前任务后**跳出循环；
`join` 等每个工人真正退出。因为 mpsc 是 FIFO，工人在跳出循环前会把队列剩余任务全跑完，
所以这是"排完队再退"，不是"立刻砍"。

三种关闭语义对比：

| 语义 | 行为 | 适用 |
|------|------|------|
| 优雅关闭 | 跑完已提交任务再退 | 请求处理、批任务 |
| 立即关闭 | 丢弃未开始的任务 | 关闭信号、超时兜底 |
| 超时关闭 | 等 N 秒，还没完就砍 | 线上发布（最常用） |

### 4.6 `shutdown_timeout` —— 超时关闭

标准库**没有** `join_timeout`（Java 有 `ExecutorService.awaitTermination(timeout)`，
Rust 标准库没有——这也是很多人转向 tokio 的原因之一，`tokio::time::timeout` 可以直接包住 join）。
只能轮询 `is_finished`：

```rust
pub fn shutdown_timeout(mut self, timeout: Duration) -> bool {
    drop(self.sender.take());
    let deadline = std::time::Instant::now() + timeout;

    let mut all_done = true;
    for worker in &mut self.workers {
        let handle = worker.handle.take().unwrap();
        while !handle.is_finished() {
            if std::time::Instant::now() > deadline {
                all_done = false;
                break;
            }
            std::thread::sleep(std::time::Duration::from_millis(5));
        }
        if handle.is_finished() {
            let _ = handle.join();
        }
    }
    all_done
}
```

要点：超时的工人 `handle` 没 join 就丢——线程仍在后台跑（detach 效果）。生产上要配合
幂等键 / 状态表处理重启后的恢复，见 §7。

---

## 5. 运行与测试

```bash
cd thread-pool-demo

# 运行 demo（4 个工人跑 8 个任务，优雅关闭后打印计数）
cargo run

# 编译检查（含测试目标）
cargo check --all-targets

# 跑测试
cargo test
```

本 demo 不引入 tokio，测试用标准库线程。等任务完成用 `AtomicUsize` 计数 + `drop(pool)`
阻塞等待，或用 channel 通知；需要超时用 `recv_timeout`。因为测试可能多线程并发，
断言尽量用原子量或 channel 同步，避免 `sleep` 猜测时序。

### 测试用例应覆盖

| 测试 | 验证 |
|------|------|
| `executes_all_jobs` | 所有提交任务都执行 |
| `try_execute_after_close_returns_error` | 关闭后 `try_execute` 返回 `PoolClosed` |
| `shutdown_drains_queued_jobs` | 优雅关闭排空队列 |
| `bounded_queue_blocks_when_full` | 满时 `push` 阻塞（背压） |
| `worker_survives_panicking_job` | panic 不减员，工人继续跑 |

---

## 6. 快速自查清单

实现完对照检查：

- [ ] `recv` 返回 `Err` 时 `break`（sender 被 drop）。
- [ ] panic 用 `catch_unwind` + `AssertUnwindSafe` 隔离，工人不退出。
- [ ] 锁被投毒用 `poisoned.into_inner()` 恢复，不用 `.unwrap()` 直接炸。
- [ ] `execute` 忽略 send 错误（快速路径），`try_execute` 返回 `PoolError::PoolClosed`。
- [ ] `Drop` 先 `drop(sender)` 再 `join`（顺序不能反）。
- [ ] `shutdown_timeout` 用 `is_finished` 轮询（std 没有 `join_timeout`）。
- [ ] `push`/`pop` 用 `while` 判断条件（防虚假唤醒），不是 `if`。
- [ ] `ThreadPool::new` 里 `assert!(size > 0)`，receiver 用 `Arc<Mutex<..>>` 共享。

---

## 7. 生产化还缺什么（文章结尾的讨论）

最小实现不到一百行，从"能跑"到"线上能跑"，还差这些：

### 7.1 队列性能

所有工人抢同一把 `Arc<Mutex<Receiver>>` 锁，且 `recv` 阻塞时持有锁——同一时刻只有一个
工人在等任务。高吞吐场景要换：

- **work stealing**：每线程一个队列，空闲工人从别人队列偷任务（rayon、tokio 的做法）；
- 无锁队列（如 crossbeam-channel / crossbeam-deque）；
- 或至少让 `recv` 不持锁（标准 mpsc 的局限是结构性的）。

### 7.2 关闭的兜底

`shutdown_timeout` 超时后没 join 的线程仍在后台跑（detach）。要处理：

- 任务执行到一半被"砍"，副作用不可撤回——业务必须幂等，或记录状态表便于重启恢复；
- 超时关闭 + 幂等键 + 状态表三者配合，才能做到"至少一次"语义下的可靠恢复。

### 7.3 有界队列的背压策略

`BoundedQueue::push` 是**阻塞式**背压（生产者等空位）。生产可能还要：

- 队列满时直接返回错误（快速失败），由调用方决定降级；
- 拒绝策略（丢弃最新 / 丢弃最旧 / 抛给调用方线程执行）；
- 按租户 / 优先级做多队列公平调度。

### 7.4 可观测性

池的状态要接入监控：队列深度、活跃 / 空闲工人数、被拒绝的任务数、任务耗时、panic 次数。
只看"任务有没有提交"，发现不了工人静默减员和队列积压。

### 7.5 与本系列其他 demo 的衔接

线程池是执行层，调度器（`scheduler-demo`）是调度层。二者可以组合：调度器算出到期
occurrence，丢给线程池执行；重试、退避和死信交给任务队列（`task-queue-demo`）处理，
业务 Handler 保证幂等。三者职责分离，别混在一起。

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
