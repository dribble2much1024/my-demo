# 用 Rust 从零实现线程池：难点不是任务队列，是关闭

> 来源：微信公众平台 · billchen
> 原文链接：https://mp.weixin.qq.com/s/3zlOvrNh6Z6xMimhNCBF9g

---

线程池的核心代码其实不到一百行。但从"能跑"到"能在线上跑"，中间隔着缓存投毒、优雅关闭和任务丢弃。

这篇从零写一个线程池。为了不引入 tokio，用的是标准库的 thread + mpsc + Arc<Mutex<Condvar>>——这也恰好能看清线程池的骨架。

### 先想清楚：线程池解决什么问题
每次来任务就 thread::spawn，看起来最省事：

```
for job in jobs {
    std::thread::spawn(move || handle(job));
}
```

在高并发下这段代码有两个硬伤：
1. 线程创建是昂贵的操作系统调用，频繁 create/destroy 开销巨大

2. 线程数量完全不可控——一万个连接就是一万个线程，内存直接爆掉

线程池的价值就是把线程数量变成一个常量，让任务排队而不是无限开线程。

### 骨架：队列 + 固定工人

```
use std::sync::{mpsc, Arc, Mutex};
use std::thread;

type Job = Box;

pub struct ThreadPool {
    workers: Vec,
    sender: Option>,
}

struct Worker {
    id: usize,
    handle: Option>,
}

impl ThreadPool {
    pub fn new(size: usize) -> Self {
        assert!(size > 0);
        let (sender, receiver) = mpsc::channel::();
        let receiver = Arc::new(Mutex::new(receiver));

        let workers = (0..size)
            .map(|id| Worker::new(id, Arc::clone(&receiver)))
            .collect();

        Self {
            workers,
            sender: Some(sender),
        }
    }
}
```

注意 receiver 被 Arc<Mutex<>> 包着——mpsc::Receiver 本身不能克隆，多个工人线程要共享同一个接收端，只能加锁。
这也引出了第一个性能话题：所有工人抢同一把锁。后面会讲怎么改。

### 工人线程：循环取任务

```
impl Worker {
    fn new(id: usize, receiver: Arc>>) -> Self {
        let handle = thread::spawn(move || loop {
            let message = receiver.lock().unwrap().recv();

            match message {
                Ok(job) => job(),
                Err(_) => break, // 发送端已关闭，退出循环
            }
        });

        Self { id, handle: Some(handle) }
    }
}
```

recv() 会阻塞，直到有任务或者所有 Sender 被丢弃。最后那个 Err 分支就是线程的退出信号。
这里有个细节坑：receiver.lock().unwrap() 拿锁之后，recv() 会一直阻塞持有这把锁。也就是说，同一时刻实际上只有一个工人在等任务。
标准库文档里对这一点有专门的提示——这是个已知的性能问题。真正高性能的池不会用 mpsc，而是用无锁队列或者每线程一个队列（work stealing）。

### 提交任务：sender 不能先消失

```
pub fn execute(&self, f: F)
    where
        F: FnOnce() + Send + 'static,
    {
        let job: Job = Box::new(f);
        // 忽略 send 错误：池已关闭
        let _ = self.sender.as_ref().unwrap().send(job);
    }
```

send 为什么要忽略错误？因为如果所有 worker 都退出了，接收端就没了，send 会失败。这时任务其实是被丢弃的。
这在业务上必须有个说法。两种策略：
• 快速失败：execute 返回 Result，调用方感知并决定是否降级

• 背压：队列满时阻塞提交方，逼它慢下来

我倾向于让接口明确：

```
pub fn try_execute(&self, f: F) -> Result
where
    F: FnOnce() + Send + 'static,
{
    let job: Job = Box::new(f);
    self.sender
        .as_ref()
        .ok_or(PoolClosed)?
        .send(job)
        .map_err(|_| PoolClosed)
}
```

线程池不能静默丢任务。 一个"提交成功但永远不执行"的任务，比一个返回错误的失败更难排查。

### 优雅关闭：最难的部分
Drop 里如果直接让 sender 消失，工人会立刻退出——但队列里排队的任务全被丢了。

```
impl Drop for ThreadPool {
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
}
```

这里的顺序很关键：
1. drop(sender) → recv() 返回 Err → 工人处理完当前任务后跳出循环

2. join 等每个工人真正退出

因为 mpsc 是 FIFO 的，工人在跳出循环前会把队列里剩下的任务全跑完。所以这个版本的关闭是"排完队再退"，不是"立刻砍"。
对比一下两种语义：
语义
行为
适用
优雅关闭
跑完已提交任务再退
请求处理、批任务
立即关闭
丢弃未开始的任务
关闭信号、超时兜底
超时关闭
等 N 秒，还没完就砍
线上发布（最常用）

超时关闭的实现要引入一个"关闭标志"和条件变量，或者更简单——用 JoinHandle 的 is_finished 轮询：

```
pub fn shutdown_timeout(mut self, timeout: std::time::Duration) -> bool {
    drop(self.sender.take());
    let deadline = std::time::Instant::now() + timeout;

    let mut all_done = true;
    for worker in &mut self.workers {
        let handle = worker.handle.take().unwrap();
        // 标准库没有 join_timeout，只能轮询或借助 channel 通知
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

标准库确实没有 join_timeout，这是它的一个明显缺口。Java 有 ExecutorService.awaitTermination(timeout)，Rust 标准库没有——这也是很多人转向 tokio 的原因之一（tokio::time::timeout 可以直接包住 join）。

### 那些真正让线程池崩掉的细节
写到这，基本功能都有了。但线上出问题的点，几乎都不在队列上。
1. panic 会让工人静默减员。 如果 job() panic，那个工人线程就死了。线程池不会重建它，池子越来越小。

```
let message = receiver.lock().unwrap().recv();
match message {
    Ok(job) => {
        // 捕获 panic，保住工人
        if std::panic::catch_unwind(std::panic::AssertUnwindSafe(job)).is_err() {
            eprintln!("worker task panicked, keeping worker alive");
        }
    }
    Err(_) => break,
}
```

AssertUnwindSafe 是在明确告诉编译器："我知道跨 panic 边界可能留下不一致状态，我来负责。"
2. 锁被投毒。receiver.lock().unwrap() 里那个 unwrap 迟早会炸——只要持锁期间发生 panic，Mutex 就被"毒化"，后续所有 lock() 都返回 Err，整个池瞬间瘫痪。
生产代码里要么处理毒化，要么用不投毒的锁：

```
// 恢复毒化状态，继续用
let guard = match receiver.lock() {
    Ok(g) => g,
    Err(poisoned) => poisoned.into_inner(),
};
```

3. 任务参数被 move 走了。 任务里捕获了大对象，队列积压时会占用大量内存。队列深度本身就是内存，需要有界。

### 队列必须有界
mpsc::channel() 是无界的。生产者多快都能塞进去，内存无限涨——这是 OOM 的经典来源。
标准库没有有界通道，得自己写：一个 Mutex<VecDeque<Job>> 加两个条件变量（非空、非满）。

```
struct BoundedQueue {
    inner: Mutex>,
    not_empty: Condvar,
    not_full: Condvar,
    capacity: usize,
}

impl BoundedQueue {
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
}
```

这就是背压：队列满的时候，提交任务这件事本身会阻塞。压力从"内存无限涨"变成了"上游变慢"，系统整体可控。
有界队列 + 阻塞提交 = 背压。这是把"内存溢出"变成"响应变慢"的关键一步。

### 结论
线程池的最小实现不到一百行，但从最小实现到生产可用，要补的是这些东西：
工人 panic 后不重建会静默减员；Mutex 毒化会瘫痪整个池；任务队列必须有界，否则就是 OOM；关闭语义要明确是"排完再退"还是"超时强杀"。

下次看到 rayon 或者 tokio::task 这类库，你就知道表面上的 spawn 背后，藏着多少关于关闭和背压的取舍。
