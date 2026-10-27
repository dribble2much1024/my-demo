# 用 Rust 实现一个反向代理和负载均衡器

> 来源：微信公众平台 · billchen
> 原文链接：https://mp.weixin.qq.com/s/H7lQxRahdTaAOJ11kH9ONw

---

所属：Rust 从零造系统 / 网络代理与可靠性

反向代理表面上只做两步：收下请求，再向后端发出去。落到实现里，需要同时处理四类语义：

```
客户端请求
  -> 保留 method、path、query、header 和 body
  -> 从健康后端中选择一个节点
  -> 建立上游请求并处理超时
  -> 保留 status、header 和 response body
  -> 在失败时决定摘除、重试还是直接返回错误
```

这个项目用 Tokio + Axum 接收请求，用 Reqwest 访问上游，实现一个教学版 HTTP/1.1 反向代理。项目故意收住范围，不去替代 Nginx、HAProxy 或 Envoy，只把转发、负载均衡和故障处理几块代码接起来。

### 一、反向代理和负载均衡各自负责什么
客户端访问反向代理提供的统一入口，由代理代替客户端访问内部服务。同一个服务有多个实例时，负载均衡器再决定当前请求交给哪个节点。
代码里把两部分拆开：

```
Proxy Handler
  -> 读取完整请求
  -> 询问 Load Balancer 候选节点
  -> 构造上游请求
  -> 转换上游响应

Load Balancer
  -> 保存后端列表和健康状态
  -> Round Robin 选择起点
  -> 跳过不健康节点
  -> 在传输失败时摘除节点
```

选择逻辑一旦散落进 HTTP handler，将来改成最少连接、加权轮询或一致性哈希，网络转发代码也得跟着改。

### 二、后端状态为什么使用原子变量
每个后端保存 URL 和健康状态：

```
struct Backend {
    url: Url,
    healthy: AtomicBool,
}

pub struct ProxyState {
    client: Client,
    backends: Arc>,
    next: Arc,
    health_interval: Duration,
}
```

后端列表在启动后不再修改，Vec 不需要锁。运行期间会变化的只有健康状态和轮询位置，一个是布尔值，一个是整数，用原子操作就能表达。
换成 Mutex<Vec<Backend>> 后，每个请求选节点都要获取同一把锁，健康检查更新一个节点时也会挡住其他请求。这几个字段之间没有需要一起提交的状态变化，用原子变量已经够了。
Acquire/Release 保证健康状态的跨线程可见性，轮询计数只需要生成不重复的递增位置，不携带其他内存，因此使用 Relaxed：

```
let start = self.next.fetch_add(1, Ordering::Relaxed) % len;
```

### 三、Round Robin 需要跳过故障节点
正常情况下，三个节点的选择顺序是：

```
A -> B -> C -> A -> B -> C
```

当 B 不健康时，应该变成：

```
A -> C -> A -> C
```

实现先用原子游标确定本次请求的起点，再环形扫描所有节点，只收集健康节点：

```
fn candidate_indices(&self) -> Vec {
    let len = self.backends.len();
    let start = self.next.fetch_add(1, Ordering::Relaxed) % len;
    (0..len)
        .map(|offset| (start + offset) % len)
        .filter(|&index| {
            self.backends[index].healthy.load(Ordering::Acquire)
        })
        .collect()
}
```

返回候选列表，代理在第一个节点连接失败时就能继续尝试后面的节点。
这个实现不保证严格公平。并发请求的到达顺序、节点故障和请求耗时都会改变实际分布；它只保证几个实用条件：无锁、每次扫描的开销固定，健康节点大致均匀地拿到请求。

### 四、代理必须保留哪些 HTTP 语义
一次请求经过代理后，下面这些信息不能丢：
内容
示例
错误后果
Method
GET、POST、DELETE
操作语义改变
Path
/users/42访问错误资源
Query
?page=2筛选和分页丢失
Header
Authorization、Content-Type
认证或解析失败
Body
JSON、表单、二进制
请求内容丢失

目标 URL 由后端基础地址和原始 path_and_query 合成：

```
fn target_url(base: &Url, uri: &Uri) -> Result {
    let path = uri
        .path_and_query()
        .map(|value| value.as_str())
        .unwrap_or("/");
    base.join(path.trim_start_matches('/'))
}
```

例如：

```
后端：http://127.0.0.1:3001
请求：/users/42?full=true
目标：http://127.0.0.1:3001/users/42?full=true
```

Host 不能原样转发。客户端访问的是代理地址，上游连接的 Host 应该由目标 URL 决定。原始 Host 被保存到 X-Forwarded-Host，同时写入 X-Forwarded-Proto: http，让后端仍能知道外部请求信息。

### 五、逐跳 Header 要在代理处终止
HTTP Header 分为端到端和逐跳两类。Authorization、Content-Type、Cache-Control 属于端到端语义；Connection、Keep-Alive、Transfer-Encoding 和 Upgrade 只描述当前这段连接。
代理如果把 Transfer-Encoding 原样复制给下一跳，却已经把请求体重新编码，接收端就可能按错误的消息边界读取。实现会过滤：

```
Connection
Keep-Alive
Proxy-Authenticate
Proxy-Authorization
TE
Trailer
Transfer-Encoding
Upgrade
```

请求方向和响应方向都要过滤。Connection 还可以用逗号分隔的值声明其他逐跳字段，实现会解析这些名字并一并删除。例如 Connection: X-Internal 意味着 X-Internal 不能进入下一跳。
本文实现不支持 HTTP Upgrade，WebSocket 请求不会穿透。支持 WebSocket 时，代理需要识别 101 Switching Protocols，并在升级后双向复制 TCP 字节流。

### 六、为什么要先缓存请求体
Axum 的 Body 是一次性数据流。交给第一个后端后，不能再把同一个 Body 发送给第二个后端。
这里先把请求体读入内存：

```
let body = to_bytes(request.into_body(), MAX_REQUEST_BODY).await?;
```

这样每次尝试都能复制 Bytes 句柄，不必重复复制底层数据。这个选择也让代理失去流式转发能力：必须收完客户端请求体才访问上游，大文件会占用内存并增加首字节延迟。
这个 demo 把单个请求体限制为 16 MiB，超过后返回 413 Payload Too Large。生产代理通常使用流式转发和全链路背压；如果还要重试，可以只缓存小请求，或把可重放内容暂存到受限磁盘。

### 七、哪些请求可以重试
假设代理向订单服务发送：

```
POST /orders
```

后端已经创建订单，但响应返回途中连接中断。代理无法知道请求有没有执行。如果此时换一个节点重试，就可能创建第二笔订单。
这个 demo 只对协议上幂等的方法做故障转移：

```
fn is_idempotent(method: &Method) -> bool {
    matches!(
        *method,
        Method::GET
            | Method::HEAD
            | Method::OPTIONS
            | Method::PUT
            | Method::DELETE
            | Method::TRACE
    )
}
```

POST 和 PATCH 在第一个候选节点发生传输错误后直接返回 502，不会自动发给第二个节点。
PUT、DELETE 在 HTTP 定义上幂等，但业务实现仍可能写错。生产系统还应限制最大尝试次数、设置总请求预算，并使用 Idempotency-Key 或业务唯一键约束允许自动重试的写操作。

### 八、502 和 503 表达两种故障
实现区分两个错误：
状态码
触发条件
含义
503 Service Unavailable
选择前已经没有健康节点
当前没有可调度容量
502 Bad Gateway
存在候选节点，但实际访问全部失败
上游通信失败

后端返回 500 时，代理原样返回 500，不会换节点重试。一个合法的 HTTP 500 说明请求已经到达并被处理，代理不能擅自假设另一台机器执行就安全。
传输错误则会立即把节点标记为不健康：

```
match builder.send().await {
    Ok(response) => {
        backend.healthy.store(true, Ordering::Release);
        return response_to_axum(response).await;
    }
    Err(_) => backend.healthy.store(false, Ordering::Release),
}
```

这叫被动健康检查：真实业务请求发现故障，立即摘除节点。

### 九、主动健康检查负责恢复节点
只靠被动摘除，节点重启后也收不到新请求，健康状态没有机会恢复。
后台任务每 5 秒访问所有后端的 /health：

```
let healthy = client
    .get(health_url)
    .timeout(Duration::from_secs(2))
    .send()
    .await
    .map(|response| response.status().is_success())
    .unwrap_or(false);

backend.healthy.store(healthy, Ordering::Release);
```

2xx 表示健康，超时、连接失败和非 2xx 都表示不健康。这样节点恢复后会自动重新加入轮询。
这个 demo 一次检查就切换状态。生产环境一般会设置阈值，连续失败 N 次才摘除，连续成功 M 次才恢复，避免节点在临界状态反复上下线。节点很多时还要并发探活、加入随机抖动，并限制检查任务本身的资源消耗。

### 十、优雅关闭还要处理慢请求
代理通过 Axum 的 graceful shutdown 停止服务：

```
axum::serve(listener, state.app())
    .with_graceful_shutdown(async {
        let _ = tokio::signal::ctrl_c().await;
    })
    .await
```

收到 Ctrl-C 后，监听器停止接受新连接，已有连接得到完成请求的机会。探活任务在服务退出后被 abort，不会成为残留任务。
生产环境还要给排空设置上限，否则一个迟迟不结束的慢请求就能拖住整个进程。常见顺序是先从服务发现或负载均衡中摘除实例，等待状态传播，再停止 accept，deadline 到达后取消剩余请求。

### 十一、运行并观察轮询
项目提供了一个最小后端程序。先启动两个实例：

```
cd workspaces/reverse-proxy-demo

cargo run --bin demo-backend -- 127.0.0.1:3001 one
cargo run --bin demo-backend -- 127.0.0.1:3002 two
```

第三个终端启动代理：

```
cargo run -- 127.0.0.1:8080 \
  http://127.0.0.1:3001 \
  http://127.0.0.1:3002
```

连续发送请求：

```
curl 'http://127.0.0.1:8080/users?page=1'
# backend=one path=/users?page=1

curl 'http://127.0.0.1:8080/users?page=2'
# backend=two path=/users?page=2
```

停止其中一个后端，再发送 GET，请求会转移到仍然健康的节点。重启该后端后，等待一次健康检查周期，它会重新加入轮询。

### 十二、测试哪些行为
测试不直接调用 handler，而是启动真实的后端监听器和代理监听器，通过 HTTP 客户端请求：

```
cargo test
```

覆盖四个关键不变量：
1. path、query 和自定义 Header 能完整到达后端；

2. 连续请求会被 Round Robin 分配到不同节点；

3. GET 遇到不可达节点会故障转移到健康节点；

4. POST 遇到同样的错误不会跨节点重试。

第四项尤其重要。只测试“成功流量是否均匀”很容易，验证失败时不会制造重复副作用，才是代理正确性的一部分。

### 十三、这个 demo 还缺哪些生产能力
代码在这些地方收住了：

```
已有：HTTP 转发、Round Robin、主动/被动健康检查、超时、有限重试
没有：流式 Body、WebSocket、HTTP/2 上游、TLS 终止、动态服务发现
没有：加权调度、最少连接、一致性哈希、连接池指标、熔断和限流
没有：访问日志、Trace、Metric、管理端口、热更新和多进程状态共享
```

如果继续往生产版本演进，下面几项职责仍然可以分开：

```
Router / Listener       -> 接入、TLS、优雅关闭
Proxy                   -> HTTP 语义、Header、Body、超时
LoadBalancer            -> 候选节点顺序
HealthManager           -> 探活、摘除、恢复、阈值
RetryPolicy             -> 幂等性、次数、总时间预算
Observability           -> access log、trace、metric
```

这样把 Round Robin 换成加权最少连接时，HTTP 转发部分不用重写；健康检查从固定列表换成服务发现时，重试语义也不用跟着变。

### 十四、最后检查五个边界
实现反向代理时，我会反复检查下面五个边界：
1. 保留端到端语义：method、URL、Header、Body、status 都要正确传过去；

2. 终止逐跳语义：Connection、Transfer-Encoding 等 Header 不能直接复制；

3. 只调度健康节点：轮询分配请求，健康状态决定节点能不能进候选集；

4. 按幂等性决定重试：传输失败时，业务操作可能已经执行；

5. 用主动检查恢复节点：被动摘除负责止损，主动探活负责重新接入。

代理位于所有流量的必经之路。每一个自动处理都会影响整个系统：自动重试可能重复写入，错误 Header 可能破坏协议，错误健康判断可能让所有节点退出候选集。先把端到端 Header、逐跳 Header、节点状态和重试条件处理好，再增加负载均衡算法，收益更大。
