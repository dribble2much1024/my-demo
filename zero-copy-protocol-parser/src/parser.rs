//! 解析器主体。`ProtocolParser::parse` 与 `encode_frame` 是留给你实现的核心。

use crate::error::ParseError;
use crate::protocol::*;
use crate::types::*;

/// 协议解析器。持有单帧消息体上限等配置。
pub struct ProtocolParser {
    /// 单帧消息体最大长度（字节）。来自对端的 `body_len` 必须不超过它。
    pub max_body_len: usize,
}

impl Default for ProtocolParser {
    fn default() -> Self {
        Self {
            max_body_len: DEFAULT_MAX_BODY_LEN,
        }
    }
}

impl ProtocolParser {
    /// 从 `input` 解析出第一帧，返回「已解析帧 + 剩余后缀」。
    ///
    /// 生命周期 `'a` 把输入与结果绑定：`Frame<'a>` 里的 `&str` / `&[u8]`
    /// 与 `remaining` 都借用 `input`，编译器保证它们不会比输入活得更久。
    ///
    /// 实现顺序要点（对应文章的核心约束）：
    /// 1. 先确认父区间存在（长度检查），再读取任何字段；
    /// 2. 长度字段必须先限制（溢出 + 上限），再决定「等待更多字节」；
    /// 3. 所有切片 / `&str` 视图都必须在边界验证通过之后才创建；
    /// 4. 区分 `NeedMore`（继续收）与格式/恶意错误（拒绝）。
    pub fn parse<'a>(&self, input: &'a [u8]) -> Result<ParsedFrame<'a>, ParseError> {
        // ============================================================
        // 第一阶段：解析并验证固定帧头（FIXED_HEADER_LEN = 16 字节）
        // ============================================================
        // 1. 长度不足：input.len() < FIXED_HEADER_LEN
        //    -> Err(ParseError::NeedMore { additional: FIXED_HEADER_LEN - input.len() })
        //
        // 2. 校验 magic：input[0..2] == MAGIC，否则 BadMagic(magic)
        // 3. 校验 version：input[2] == SUPPORTED_VERSION，否则 UnsupportedVersion(input[2])
        // 4. 解析消息类型：MessageType::try_from(input[3])?
        // 5. 读取 flags：read_u16(input, 4)
        // 6. 读取 header_len：read_u16(input, 6)
        //    若 usize::from(header_len) != FIXED_HEADER_LEN -> InvalidHeaderLength(header_len)
        // 7. 读取 request_id：read_u32(input, 8)
        // 8. 读取 body_len：read_u32(input, 12)
        //
        // ============================================================
        // 长度限制：先限制，再等待（防止 4 字节字段声明 4 GB）
        // ============================================================
        // 9.  body_len: u32 -> usize，用 usize::try_from，溢出 -> LengthOverflow
        // 10. body_len > self.max_body_len -> FrameTooLarge { body_len, max }
        // 11. frame_len = FIXED_HEADER_LEN + body_len，用 checked_add -> LengthOverflow
        // 12. input.len() < frame_len -> NeedMore { additional: frame_len - input.len() }
        //
        // ============================================================
        // 第二阶段：用切片划出消息体
        // ============================================================
        // 13. body = &input[FIXED_HEADER_LEN..frame_len]
        // 14. body.len() < BODY_PREFIX_LEN -> BodyTooShort(body.len())
        // 15. 读取 user_len   = usize::from(read_u16(body, 0))
        //         topic_len  = usize::from(read_u16(body, 2))
        //         timestamp_ms = read_u64(body, 4)
        // 16. fields_end = BODY_PREFIX_LEN + user_len + topic_len
        //     用 checked_add / and_then 逐级相加 -> LengthOverflow
        // 17. fields_end > body.len() -> InvalidFieldLengths { user_len, topic_len, body_len }
        //
        // ============================================================
        // 构造借用视图：验证全部通过后才创建切片 / &str
        // ============================================================
        // 18. user  = str::from_utf8(&body[BODY_PREFIX_LEN..BODY_PREFIX_LEN + user_len])
        //     .map_err(|_| ParseError::InvalidUtf8 { field: "user" })?
        // 19. topic = str::from_utf8(&body[BODY_PREFIX_LEN + user_len..fields_end])
        //     .map_err(|_| ParseError::InvalidUtf8 { field: "topic" })?
        // 20. payload = &body[fields_end..]
        //
        // ============================================================
        // 组装并返回
        // ============================================================
        // 21. 组装 Header { version, message_type, flags, header_len, request_id, body_len }
        // 22. 组装 Message { user, topic, timestamp_ms, payload }
        // 23. 组装 Frame { header, message }
        // 24. Ok(ParsedFrame { frame, remaining: &input[frame_len..] })

        todo!("核心解析逻辑留给你实现：按上方 1~24 步依次完成，最后返回 ParsedFrame")
    }
}

/// 编码一帧为 `Vec<u8>`（用于示例与 roundtrip 测试）。
///
/// 编码路径返回拥有所有权的输出缓冲区，不违背「解析路径零拷贝」。
/// 布局需与协议一一对应：16 字节固定头 + 消息体（前缀 + user + topic + payload）。
pub fn encode_frame(
    message_type: MessageType,
    flags: u16,
    request_id: u32,
    user: &str,
    topic: &str,
    timestamp_ms: u64,
    payload: &[u8],
) -> Vec<u8> {
    // 提示：
    // - body_len = BODY_PREFIX_LEN + user.len() + topic.len() + payload.len()
    // - 固定头：MAGIC、SUPPORTED_VERSION、message_type as u8、flags、header_len=16、request_id、body_len
    // - 消息体：user_len、topic_len、timestamp_ms、user 字节、topic 字节、payload 字节
    // - 所有多字节整数用 to_be_bytes() 按大端写入
    todo!("编码逻辑留给你实现：用于 demo 与 roundtrip 测试")
}
