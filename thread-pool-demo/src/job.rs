//! 任务类型：一个 box 起来的、可 `Send` 的、只跑一次的闭包。

/// 线程池里的一单位工作。
///
/// `FnOnce` 允许 move 捕获大对象；`Send + 'static` 允许跨线程移动并在任意时刻运行。
/// 因为它是 trait object，调度器 / 工人无需知道具体闭包类型，统一当 `Job` 处理。
pub type Job = Box<dyn FnOnce() + Send + 'static>;
