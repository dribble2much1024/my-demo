//! 解析错误类型。错误分类是解析器协议的一部分：上层据此决定
//! 「继续收字节」「协议不兼容直接断开」还是「恶意/损坏输入拒绝并计数」。

use std::fmt;

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum ParseError {
    /// 数据不完整，还需 `additional` 字节（TCP 分片尚未收全）。
    /// 注意：`additional` 不可直接用于无限分配，仍受单帧上限约束。
    NeedMore { additional: usize },

    /// 帧头魔数不匹配，说明连错端口、流错位或数据损坏。
    BadMagic([u8; 2]),

    /// 不支持的协议版本。
    UnsupportedVersion(u8),

    /// 未知消息类型。
    UnknownMessageType(u8),

    /// `header_len` 不是当前支持的固定头长度。
    InvalidHeaderLength(u16),

    /// 消息体超过单帧上限（在等待消息体之前拒绝）。
    FrameTooLarge { body_len: usize, max: usize },

    /// 消息体不足以容纳固定前缀。
    BodyTooShort(usize),

    /// 变长字段长度之和超过消息体。
    InvalidFieldLengths {
        user_len: usize,
        topic_len: usize,
        body_len: usize,
    },

    /// 文本字段不是合法 UTF-8（拒绝，不做有损替换）。
    InvalidUtf8 { field: &'static str },

    /// 长度转换或加法溢出。
    LengthOverflow,
}

impl fmt::Display for ParseError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            ParseError::NeedMore { additional } => {
                write!(f, "需要更多字节：还需 {additional}")
            }
            ParseError::BadMagic(m) => write!(f, "魔数不匹配：{m:?}"),
            ParseError::UnsupportedVersion(v) => write!(f, "不支持的版本：{v}"),
            ParseError::UnknownMessageType(t) => write!(f, "未知消息类型：{t}"),
            ParseError::InvalidHeaderLength(l) => write!(f, "无效头长度：{l}"),
            ParseError::FrameTooLarge { body_len, max } => {
                write!(f, "帧过大：body_len={body_len}, max={max}")
            }
            ParseError::BodyTooShort(l) => write!(f, "消息体过短：{l}"),
            ParseError::InvalidFieldLengths {
                user_len,
                topic_len,
                body_len,
            } => write!(
                f,
                "字段长度无效：user_len={user_len}, topic_len={topic_len}, body_len={body_len}"
            ),
            ParseError::InvalidUtf8 { field } => write!(f, "字段 {field} 不是合法 UTF-8"),
            ParseError::LengthOverflow => write!(f, "长度溢出"),
        }
    }
}

impl std::error::Error for ParseError {}
