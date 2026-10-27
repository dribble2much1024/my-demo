//! 测试共享辅助：手工构造一个合法的 ZP/1 帧字节。
//!
//! 独立于 `encode_frame`，因此测试不依赖尚未实现的编码器，
//! 只依赖你实现的 `parse`。

#![allow(dead_code)]

pub const SAMPLE_USER: &str = "alice";
pub const SAMPLE_TOPIC: &str = "greetings";
pub const SAMPLE_PAYLOAD: &[u8] = b"hello world";
pub const SAMPLE_TIMESTAMP_MS: u64 = 1_700_000_000_000;
pub const SAMPLE_REQUEST_ID: u32 = 42;
pub const SAMPLE_MESSAGE_TYPE: u8 = 1; // Publish

/// 构造一帧合法字节：16 字节固定头 + 消息体（前缀 + user + topic + payload）。
pub fn sample_frame_bytes() -> Vec<u8> {
    let user = SAMPLE_USER.as_bytes();
    let topic = SAMPLE_TOPIC.as_bytes();
    let payload = SAMPLE_PAYLOAD;

    let body_len = 12 + user.len() + topic.len() + payload.len();

    let mut v = Vec::with_capacity(16 + body_len);

    // 固定头（16 字节）
    v.extend_from_slice(b"ZP"); // magic
    v.push(1); // version
    v.push(SAMPLE_MESSAGE_TYPE); // message_type
    v.extend_from_slice(&0u16.to_be_bytes()); // flags
    v.extend_from_slice(&16u16.to_be_bytes()); // header_len
    v.extend_from_slice(&SAMPLE_REQUEST_ID.to_be_bytes()); // request_id
    v.extend_from_slice(&(body_len as u32).to_be_bytes()); // body_len

    // 消息体
    v.extend_from_slice(&(user.len() as u16).to_be_bytes()); // user_len
    v.extend_from_slice(&(topic.len() as u16).to_be_bytes()); // topic_len
    v.extend_from_slice(&SAMPLE_TIMESTAMP_MS.to_be_bytes()); // timestamp_ms
    v.extend_from_slice(user);
    v.extend_from_slice(topic);
    v.extend_from_slice(payload);

    v
}
