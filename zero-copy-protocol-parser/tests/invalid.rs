//! 非法输入测试：覆盖 magic、version、message_type、header_len、
//! 超大 body_len、字段长度越界、非法 UTF-8、空消息体等边界。

mod common;

use common::sample_frame_bytes;
use zero_copy_protocol_parser::*;

/// magic 校验。
#[test]
fn rejects_bad_magic() {
    let mut input = sample_frame_bytes();
    input[0] = b'X';
    assert!(matches!(
        ProtocolParser::default().parse(&input),
        Err(ParseError::BadMagic(_))
    ));
}

/// version 校验。
#[test]
fn rejects_unsupported_version() {
    let mut input = sample_frame_bytes();
    input[2] = 99;
    assert!(matches!(
        ProtocolParser::default().parse(&input),
        Err(ParseError::UnsupportedVersion(99))
    ));
}

/// message_type 校验。
#[test]
fn rejects_unknown_message_type() {
    let mut input = sample_frame_bytes();
    input[3] = 42;
    assert!(matches!(
        ProtocolParser::default().parse(&input),
        Err(ParseError::UnknownMessageType(42))
    ));
}

/// header_len 校验。
#[test]
fn rejects_invalid_header_length() {
    let mut input = sample_frame_bytes();
    input[6] = 0;
    input[7] = 20;
    assert!(matches!(
        ProtocolParser::default().parse(&input),
        Err(ParseError::InvalidHeaderLength(20))
    ));
}

/// 超大 body_len 必须在等待消息体之前被拒绝（防 4 字节字段声明 4 GB）。
#[test]
fn rejects_oversized_body_len_before_waiting() {
    let mut input = sample_frame_bytes();
    input[12..16].copy_from_slice(&u32::MAX.to_be_bytes());
    assert!(matches!(
        ProtocolParser::default().parse(&input),
        Err(ParseError::FrameTooLarge { .. }) | Err(ParseError::LengthOverflow)
    ));
}

/// user_len + topic_len 超过消息体时返回结构错误。
#[test]
fn rejects_field_lengths_exceeding_body() {
    let mut input = sample_frame_bytes();
    // user_len 位于 body offset 0..2（= frame offset 16..18）
    input[16] = 0xff;
    input[17] = 0xff;
    assert!(matches!(
        ProtocolParser::default().parse(&input),
        Err(ParseError::InvalidFieldLengths { .. })
    ));
}

/// 非法 UTF-8 不会被有损转换，应被明确拒绝。
#[test]
fn rejects_invalid_utf8() {
    let mut input = sample_frame_bytes();
    // user 字段起始于 body offset 12（= frame offset 28），首个字节改成非法 UTF-8
    input[28] = 0xff;
    assert!(matches!(
        ProtocolParser::default().parse(&input),
        Err(ParseError::InvalidUtf8 { field: "user" })
    ));
}

/// body_len = 0 时消息体不足以容纳固定前缀。
#[test]
fn rejects_empty_body() {
    let mut input = sample_frame_bytes();
    input[12..16].copy_from_slice(&0u32.to_be_bytes());
    input.truncate(16);
    assert!(matches!(
        ProtocolParser::default().parse(&input),
        Err(ParseError::BodyTooShort(_))
    ));
}
