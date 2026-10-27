# ZP/1 零拷贝协议解析器 —— 分步实现计划

> 本文档是 `parse` 与 `encode_frame` 的分步实现指引。
> 每步都有明确的「完成标志」，建议按顺序推进，跑绿一步再进入下一步。
> 骨架已就绪：类型、错误、常量、读取工具、测试均已提供，你只需填 `src/parser.rs` 里的两个函数体。

---

## 目标与完成标准

- **目标**：实现一个安全的零拷贝二进制协议解析器，解析结果借用输入缓冲区，不复制变长字段。
- **完成定义（Definition of Done）**：
  1. `cargo test` 全部通过（覆盖截断、粘包、地址、非法输入等边界）。
  2. `cargo clippy --all-targets -- -D warnings` 零警告。
  3. `cargo run --example demo` 正常打印一帧的解析结果。

---

## 协议布局速查

### 固定帧头（16 字节，大端序）

| 偏移 | 长度 | 字段 | 说明 |
|------|------|------|------|
| 0  | 2 | `magic`       | 固定为 `"ZP"` |
| 2  | 1 | `version`     | 当前仅支持 `1` |
| 3  | 1 | `message_type`| `1=Publish, 2=Request, 3=Response` |
| 4  | 2 | `flags`       | 任意 |
| 6  | 2 | `header_len`  | 当前仅支持 `16` |
| 8  | 4 | `request_id`  | 任意 |
| 12 | 4 | `body_len`    | 消息体长度（不可信，需限制） |

### 消息体

| 偏移 | 长度 | 字段 |
|------|------|------|
| 0  | 2  | `user_len` |
| 2  | 2  | `topic_len` |
| 4  | 8  | `timestamp_ms` |
| 12 | `user_len`  | `user`（UTF-8） |
| ...| `topic_len` | `topic`（UTF-8） |
| ...| 剩余字节    | `payload`（无单独长度字段，由减法推出） |

**关键常量**（见 `src/protocol.rs`）：`FIXED_HEADER_LEN = 16`、`BODY_PREFIX_LEN = 12`、`MAGIC = b"ZP"`、`SUPPORTED_VERSION = 1`。

---

## 分步实现计划

### Step 0：确认骨架可编译

- `cargo test --no-run` 应编译通过，仅出现 11 个 `unused`/`dead_code` 警告（因为 `parse`/`encode_frame` 还是 `todo!()`，属正常）。
- 这些警告会随着你逐步实现而消失。

---

### Step 1：固定帧头校验

在 `parse` 里实现第一阶段，只处理前 16 字节的读取与校验：

1. `input.len() < FIXED_HEADER_LEN` → `Err(ParseError::NeedMore { additional: 16 - input.len() })`。
2. `input[0..2] != MAGIC` → `Err(ParseError::BadMagic([input[0], input[1]]))`。
3. `input[2] != SUPPORTED_VERSION` → `Err(ParseError::UnsupportedVersion(input[2]))`。
4. `let message_type = MessageType::try_from(input[3])?`。
5. 读 `flags`、`header_len`、`request_id`、`body_len`（用 `read_u16`/`read_u32`）。
6. `usize::from(header_len) != FIXED_HEADER_LEN` → `Err(ParseError::InvalidHeaderLength(header_len))`。

**要点**：永远先做长度检查再取字节，下标访问才有前置保证。

**完成标志**：

```
cargo test rejects_bad_magic rejects_unsupported_version rejects_unknown_message_type rejects_invalid_header_length
```

---

### Step 2：长度限制（先限制，再等待）

继续 `parse`，处理不可信的 `body_len`，顺序不能反：

1. `let body_len = usize::try_from(body_len_u32).map_err(|_| ParseError::LengthOverflow)?;`
2. `body_len > self.max_body_len` → `Err(ParseError::FrameTooLarge { body_len, max: self.max_body_len })`。
3. `let frame_len = FIXED_HEADER_LEN.checked_add(body_len).ok_or(ParseError::LengthOverflow)?;`
4. `input.len() < frame_len` → `Err(ParseError::NeedMore { additional: frame_len - input.len() })`。

**要点**：上限检查必须放在返回 `NeedMore` 之前，否则攻击者用一个头就能让上层等待/分配 4 GB。

**完成标志**：

```
cargo test rejects_oversized_body_len_before_waiting
```

---

### Step 3：划出消息体 + 字段边界验证

在 `parse` 里进入第二阶段：

1. `let body = &input[FIXED_HEADER_LEN..frame_len];`
2. `body.len() < BODY_PREFIX_LEN` → `Err(ParseError::BodyTooShort(body.len()))`。
3. 读 `user_len`、`topic_len`（`read_u16`）、`timestamp_ms`（`read_u64`）。
4. `let fields_end = BODY_PREFIX_LEN.checked_add(user_len).and_then(|e| e.checked_add(topic_len)).ok_or(ParseError::LengthOverflow)?;`
5. `fields_end > body.len()` → `Err(ParseError::InvalidFieldLengths { user_len, topic_len, body_len: body.len() })`。

**要点**：先验证父区间存在、再验证子区间不越界，最后才允许创建切片。

**完成标志**：

```
cargo test rejects_field_lengths_exceeding_body rejects_empty_body
```

---

### Step 4：构造借用视图（UTF-8 + payload）

边界验证通过后，才创建 `&str` 和 `&[u8]`：

1. `let user = std::str::from_utf8(&body[BODY_PREFIX_LEN..BODY_PREFIX_LEN + user_len]).map_err(|_| ParseError::InvalidUtf8 { field: "user" })?;`
2. `let topic = std::str::from_utf8(&body[BODY_PREFIX_LEN + user_len..fields_end]).map_err(|_| ParseError::InvalidUtf8 { field: "topic" })?;`
3. `let payload = &body[fields_end..];`

**要点**：用 `from_utf8`（拒绝非法编码），**不要**用 `from_utf8_lossy`（会有损替换且可能分配）。

**完成标志**：

```
cargo test rejects_invalid_utf8
```

---

### Step 5：组装返回 + remaining

把前面读到的字段组装成 `Frame<'a>`，并返回输入后缀：

1. 组装 `Header { version, message_type, flags, header_len, request_id, body_len }`。
2. 组装 `Message { user, topic, timestamp_ms, payload }`。
3. `Ok(ParsedFrame { frame: Frame { header, message }, remaining: &input[frame_len..] })`。

**要点**：`remaining` 是同一输入的后缀，处理粘包；`Frame<'a>` 借用输入，编译器保证它不会比输入活得更久。

**完成标志**（此时 `parse` 完整，以下应全部通过）：

```
cargo test
```

---

### Step 6：实现 encode_frame（编码器）

实现 `encode_frame`，用于 demo 与 roundtrip 测试：

1. `let body_len = BODY_PREFIX_LEN + user.len() + topic.len() + payload.len();`
2. 写入固定头：`MAGIC`、`SUPPORTED_VERSION`、`message_type as u8`、`flags`、`header_len = 16`、`request_id`、`body_len as u32`。
3. 写入消息体：`user_len`、`topic_len`、`timestamp_ms`、`user` 字节、`topic` 字节、`payload` 字节。
4. 所有多字节整数用 `to_be_bytes()` 按大端写入。

**要点**：编码路径返回拥有所有权的 `Vec<u8>`，不违背「解析路径零拷贝」。

**完成标志**：取消 `examples/demo.rs` 里的注释，运行 `cargo run --example demo` 能打印出正确的 `user/topic/payload`。

**可选（推荐）**：新增一个 roundtrip 测试，`encode_frame(...)` 后再 `parse` 回来，断言字段等价。

---

### Step 7：收尾验证

三条命令全部通过即达成完成定义：

```bash
cargo test
cargo clippy --all-targets -- -D warnings
cargo run --example demo
```

---

## 常见失败方式（实现时对照自查）

| 反模式 | 正确做法 |
|--------|----------|
| 先切片、靠 panic 兜底 | 先 `checked_add`/长度检查，再创建视图 |
| 收到长度后立即 `reserve` | 先过 `max_body_len` 和全局预算 |
| 用 `from_utf8_lossy` 当校验 | 用 `from_utf8` 明确拒绝非法编码 |
| 把一次 TCP `read` 当一帧 | 靠 `body_len` 处理半包/粘包，返回 `remaining` |
| 把未知版本当当前版本解析 | 版本不符时拒绝或协商 |
| 只测合法样例 | 覆盖截断、溢出、越界、非法编码、超大长度 |
