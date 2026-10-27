//! 解析结果类型。带生命周期 `'a` 的结果借用输入缓冲区，不拥有变长字段。

use crate::error::ParseError;

/// 解析出的消息体。`user` / `topic` 借用输入字节（`&'a str`），
/// `payload` 借用输入字节（`&'a [u8]`）；小整数 `timestamp_ms` 按值保存。
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct Message<'a> {
    pub user: &'a str,
    pub topic: &'a str,
    pub timestamp_ms: u64,
    pub payload: &'a [u8],
}

/// 解析后的固定帧头。小整数从大端序解码后按值保存。
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct Header {
    pub version: u8,
    pub message_type: MessageType,
    pub flags: u16,
    pub header_len: u16,
    pub request_id: u32,
    pub body_len: u32,
}

/// 一帧完整的解析结果。
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Frame<'a> {
    pub header: Header,
    pub message: Message<'a>,
}

/// 解析一帧后返回的「已消费帧 + 输入缓冲区剩余后缀」。
/// `remaining` 用于处理 TCP 粘包：一次 `read` 可能包含多帧。
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ParsedFrame<'a> {
    pub frame: Frame<'a>,
    pub remaining: &'a [u8],
}

/// 消息类型。在协议边界就把不可信字节收窄为领域枚举。
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum MessageType {
    Publish = 1,
    Request = 2,
    Response = 3,
}

impl TryFrom<u8> for MessageType {
    type Error = ParseError;

    fn try_from(value: u8) -> Result<Self, Self::Error> {
        match value {
            1 => Ok(Self::Publish),
            2 => Ok(Self::Request),
            3 => Ok(Self::Response),
            other => Err(ParseError::UnknownMessageType(other)),
        }
    }
}
