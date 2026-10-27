//! 最小示例：编码一帧 -> 解析 -> 打印。
//!
//! 需要先完成 `src/parser.rs` 里的 `parse` 与 `encode_frame`，
//! 再取消下方注释，运行 `cargo run --example demo`。

use zero_copy_protocol_parser::*;

fn main() {
    // 编码一帧（等你实现 encode_frame 后取消注释）
    // let bytes = encode_frame(
    //     MessageType::Publish,
    //     0,
    //     42,
    //     "alice",
    //     "greetings",
    //     1_700_000_000_000,
    //     b"hello world",
    // );

    // 解析（等你实现 parse 后取消注释）
    // let parsed = ProtocolParser::default().parse(&bytes).unwrap();
    // println!("header    = {:#?}", parsed.frame.header);
    // println!("user      = {}", parsed.frame.message.user);
    // println!("topic     = {}", parsed.frame.message.topic);
    // println!("payload   = {:?}", parsed.frame.message.payload);
    // println!("remaining = {} 字节", parsed.remaining.len());

    println!("骨架已就绪。请先实现 src/parser.rs 中的 parse 与 encode_frame，");
    println!("再取消本文件中的注释，运行 `cargo run --example demo`。");
}
