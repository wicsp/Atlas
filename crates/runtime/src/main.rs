//! Runtime：每台设备上的 daemon。领取 job → 调用 claude / codex / pi → 结果写回 vault。
//! 只通过 HTTP + job 协议与 Hub 通信，不依赖 lumio-hub。P2 起实现。
fn main() {
    println!("lumio-runtime: not implemented yet");
}
