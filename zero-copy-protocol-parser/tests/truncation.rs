//! 截断测试：在合法帧的每一个字节位置截断，都必须返回 NeedMore 而不是 panic。

mod common;

use common::sample_frame_bytes;
use zero_copy_protocol_parser::*;

/// 对完整合法帧，在每个字节位置截断，都应返回 `NeedMore`（还需更多字节）。
#[test]
fn every_truncation_returns_need_more() {
    let input = sample_frame_bytes();
    let parser = ProtocolParser::default();

    for end in 0..input.len() {
        let result = parser.parse(&input[..end]);
        assert!(
            matches!(result, Err(ParseError::NeedMore { additional }) if additional > 0),
            "截断到 {end} 字节时应返回 NeedMore，实际得到 {result:?}"
        );
    }
}

/// 完整帧应成功解析，且 remaining 为空。
#[test]
fn full_frame_parses() {
    let input = sample_frame_bytes();
    let parsed = ProtocolParser::default().parse(&input).unwrap();
    assert_eq!(parsed.frame.message.user, "alice");
    assert_eq!(parsed.frame.message.topic, "greetings");
    assert_eq!(parsed.frame.message.payload, b"hello world");
    assert!(parsed.remaining.is_empty());
}
