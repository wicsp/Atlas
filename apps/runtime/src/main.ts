// Runtime：每台设备上的 daemon。领取 job → 调用 claude / codex / pi / 脚本 → 结果写回 vault。
// 只通过 HTTP + job 协议与 Hub 通信，不 import apps/hub（ADR 0005）。P2 起实现。
// 若将来用 Rust 重写，替换这一个 app 即可（ADR 0002）。
console.log("lumio-runtime: not implemented yet");
