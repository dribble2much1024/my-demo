//! 重试策略：决定哪些请求在传输失败后可以换节点重试。

use http::Method;

/// 判断方法在协议上是否幂等、可安全自动重试。
///
/// 返回 true 的方法：GET、HEAD、OPTIONS、PUT、DELETE、TRACE。
/// POST 和 PATCH 默认不重试——代理无法知道业务是否已经执行，
/// 换节点重试可能制造重复副作用（例如重复下单）。
///
/// 注意：PUT/DELETE 在 HTTP 定义上幂等，但业务实现仍可能写错，
/// 生产环境应配合 `Idempotency-Key` 等机制约束可重试的写操作。
pub fn is_idempotent(method: &Method) -> bool {
    // TODO(你来实现): 判断 method 是否属于上述幂等集合。
    todo!("实现幂等方法判断")
}
