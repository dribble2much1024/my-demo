//! 进程内任务调度器（教学版）。
//!
//! TODO 桩尚未实现，下面的 allow 用于压制"未实现"带来的 dead_code / 未用变量告警；
//! 把各 `todo!()` 补完后可删除这一行，让编译器重新帮你把关。
//!
//! 对应文章《用 Rust 实现一个定时任务调度器》。整体分两层：
//!
//! - **调度层**（何时产生一次执行）：[`Schedule`]、[`Deadline`] 最小堆、misfire / overlap 策略；
//! - **执行层**（这一次怎么运行）：`JoinSet`、全局并发上限、panic 隔离、运行统计。
//!
//! 一次计划中的执行称为 *occurrence*（见 [`scheduler::Occurrence`]）。
//!
//! 核心调度循环尚未实现（留作练习），实现见各模块中的 `todo!()` 以及项目根目录的
//! `GUIDE.md` 指导文章。
#![allow(dead_code, unused_variables, unused_mut)]

pub mod config;
pub mod context;
pub mod deadline;
pub mod definition;
pub mod error;
pub mod handler;
pub mod jobs;
pub mod policy;
pub mod report;
pub mod schedule;
pub mod scheduler;

pub use config::SchedulerConfig;
pub use context::JobContext;
pub use deadline::Deadline;
pub use definition::JobDefinition;
pub use error::SchedulerError;
pub use handler::JobHandler;
pub use policy::{MisfirePolicy, OverlapPolicy};
pub use report::{RunOutcome, SchedulerReport};
pub use schedule::Schedule;
pub use scheduler::Scheduler;
