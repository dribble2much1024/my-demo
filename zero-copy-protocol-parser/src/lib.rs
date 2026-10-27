//! 零拷贝二进制协议解析器（ZP/1）。
//!
//! 解析结果借用输入缓冲区，不为变长字段（`user` / `topic` / `payload`）
//! 创建新的 `String` 或 `Vec<u8>`。所有切片都建立在长度、溢出和编码验证之后。
//!
//! 本骨架已就绪：类型、错误、常量、读取工具与测试均已提供，
//! **核心解析逻辑 `ProtocolParser::parse` 与编码器 `encode_frame` 留给你实现**。

mod error;
mod parser;
mod protocol;
mod types;

pub use error::ParseError;
pub use parser::{encode_frame, ProtocolParser};
pub use protocol::{
    BODY_PREFIX_LEN, DEFAULT_MAX_BODY_LEN, FIXED_HEADER_LEN, MAGIC, SUPPORTED_VERSION,
};
pub use types::{Frame, Header, Message, MessageType, ParsedFrame};
