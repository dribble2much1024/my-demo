//! ZP/1 协议的常量定义与大端序读取工具。

/// 固定帧头长度（字节）。
pub const FIXED_HEADER_LEN: usize = 16;

/// 消息体固定前缀长度（字节）：user_len(2) + topic_len(2) + timestamp_ms(8)。
pub const BODY_PREFIX_LEN: usize = 12;

/// 帧头魔数 "ZP"。
pub const MAGIC: [u8; 2] = *b"ZP";

/// 当前唯一支持的协议版本。
pub const SUPPORTED_VERSION: u8 = 1;

/// 默认单帧消息体上限（4 MiB）。生产环境应结合全局内存预算再收紧。
pub const DEFAULT_MAX_BODY_LEN: usize = 4 * 1024 * 1024;

/// 以网络字节序（大端）读取一个 `u16`。
///
/// 调用方需保证 `input[offset..offset + 2]` 已通过长度检查。
pub(crate) fn read_u16(input: &[u8], offset: usize) -> u16 {
    u16::from_be_bytes([input[offset], input[offset + 1]])
}

/// 以网络字节序（大端）读取一个 `u32`。
pub(crate) fn read_u32(input: &[u8], offset: usize) -> u32 {
    u32::from_be_bytes([
        input[offset],
        input[offset + 1],
        input[offset + 2],
        input[offset + 3],
    ])
}

/// 以网络字节序（大端）读取一个 `u64`。
pub(crate) fn read_u64(input: &[u8], offset: usize) -> u64 {
    u64::from_be_bytes([
        input[offset],
        input[offset + 1],
        input[offset + 2],
        input[offset + 3],
        input[offset + 4],
        input[offset + 5],
        input[offset + 6],
        input[offset + 7],
    ])
}
