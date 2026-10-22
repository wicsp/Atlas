# Lumio

个人研究工作台：论文笔记、想法、项目/任务、实验结果，以及在多台设备上给 AI 派活。

- 数据（笔记/论文/任务…）**不在本仓库**，放在独立的 vault 仓库里（Markdown + YAML frontmatter）。
- 本仓库只放代码：TypeScript monorepo，运行在 [Bun](https://bun.com) 上。

先读：[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) → [`AGENTS.md`](AGENTS.md) → [`docs/adr/`](docs/adr/)

## 目录

| 路径 | 内容 |
|---|---|
| `packages/schema` | 契约：用 Zod 定义的实体与 job 协议，唯一事实来源 |
| `packages/core` | vault 解析、链接、索引、BibTeX，纯本地逻辑 |
| `packages/api-client` | 调用 Hub 的 SDK，所有客户端共用 |
| `apps/cli` | `lumio` 命令行 |
| `apps/hub` | 服务器：HTTP API、job 队列、定时调度、MCP |
| `apps/runtime` | 每台设备上的 daemon，领取 job 并调用 agent |
| `apps/feishu-bot` | 飞书入口与通知 |
| `apps/web` `apps/chrome-ext` `apps/mobile` | 后期客户端 |
| `sdk/python` | 实验侧的薄客户端（后期），类型从导出的 JSON Schema 生成 |
| `infra/` | Docker / Nix（后期） |

## 开始

```sh
bun install
bun run check          # 类型检查 + 依赖边界检查 + 测试
bun run schema:export  # 把契约导出为 JSON Schema（packages/schema/json/）
```

## 当前阶段

P0：`packages/schema` + `packages/core` + `apps/cli`，做到"arXiv/DOI 一键入库 → 笔记 + BibTeX"。
