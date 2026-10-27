//! 零拷贝验证：用地址测试证明字段借用输入缓冲区；用 remaining 处理粘包。

mod common;

use common::{sample_frame_bytes, SAMPLE_REQUEST_ID, SAMPLE_TIMESTAMP_MS};
use zero_copy_protocol_parser::*;

/// 地址测试：字段指针必须落在输入缓冲区范围内（证明没有复制）。
#[test]
fn fields_borrow_from_input() {
    let input = sample_frame_bytes();
    let parsed = ProtocolParser::default().parse(&input).unwrap();

    let input_range = input.as_ptr_range();
    assert!(input_range.contains(&parsed.frame.message.user.as_ptr()));
    assert!(input_range.contains(&parsed.frame.message.topic.as_ptr()));
    assert!(input_range.contains(&parsed.frame.message.payload.as_ptr()));
}

/// 两帧连续输入时，remaining 能继续解析第二帧（粘包）。
#[test]
fn parses_second_frame_from_remaining() {
    let mut input = sample_frame_bytes();
    input.extend_from_slice(&sample_frame_bytes());

    let first = ProtocolParser::default().parse(&input).unwrap();
    assert!(!first.remaining.is_empty());

    let second = ProtocolParser::default().parse(first.remaining).unwrap();
    assert_eq!(second.frame.message.user, "alice");
    assert!(second.remaining.is_empty());
}

/// 头字段与时间戳解码正确（大端序）。
#[test]
fn header_values_decoded_correctly() {
    let input = sample_frame_bytes();
    let parsed = ProtocolParser::default().parse(&input).unwrap();

    assert_eq!(parsed.frame.header.version, 1);
    assert_eq!(parsed.frame.header.message_type, MessageType::Publish);
    assert_eq!(parsed.frame.header.header_len, 16);
    assert_eq!(parsed.frame.header.request_id, SAMPLE_REQUEST_ID);
    assert_eq!(parsed.frame.message.timestamp_ms, SAMPLE_TIMESTAMP_MS);
}
