# 统一入口：Rust + TS 一起检查

default: check

check: check-rust check-ts check-schema

check-rust:
    cargo fmt --all --check
    cargo clippy --workspace -- -D warnings
    cargo test --workspace

check-ts:
    pnpm check

check-schema:
    for f in schema/*.json schema/*/*.json; do python3 -m json.tool "$f" > /dev/null || exit 1; done

# 从 schema/ 生成各语言类型（工具待 ADR 0003 定稿后补全）
codegen:
    @echo "TODO: typify → crates/core, json-schema-to-zod → packages/api-client, datamodel-codegen → sdk/python"
