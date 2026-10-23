# Lumio 架构

> 本文件由人类批准。AI 可以提议修改，但须通过 ADR。

## 1. 目标与非目标

**目标**：在一个地方管理论文笔记、想法、项目/任务、实验结果；把想法通过链接串成报告；
把工作派给 Mac 或服务器上的 AI，并支持定时工作流。

**非目标**（至少在 P3 之前）：自己写编辑器、自己写 agent 循环、多用户与权限、与飞书双向同步正文。

## 2. 总体结构

```
 Obsidian（Mac / iPad / 手机）── 直接编辑文件 ──┐
                                                ▼
┌──── 程序入口（可替换）────┐      ┌──────────────────────────────┐
│ CLI │ 飞书 Bot │ Web/插件  │─API─▶│ Hub（唯一写入裁判，位置可配置）│
└──────────────────────────┘ token │  校验 → 执行 ADR 0006 → 写文件 │
                                    │  监听文件变化 → 补全与索引    │
                                    │  提议队列 · job 队列 · MCP    │
                                    └───────┬───────────┬──────────┘
            Tailscale（或 HTTPS 反向代理）  │           │ 自动 commit
                   ┌────────────────────────┘           ▼
            ┌──────▼───────┐                 vault 的 git（只做历史与备份，
            │ Runtime@设备 │ 领取 job →       .git 在同步目录之外）
            │ 调用 agent   │ 结果经 Hub API 写回
            └──────────────┘

Vault = Hub 的数据目录 = Obsidian vault（唯一事实来源，当前位于 iCloud）
  papers/ ideas/ projects/ tasks/ experiments/ reports/
SQLite 只是派生索引；refs.bib 由各论文笔记的 BibTeX 一节生成
```


## 3. 模块与依赖方向

全部使用 TypeScript，运行在 Bun 上（ADR 0002）。

| 模块 | 职责 | 可以依赖 |
|---|---|---|
| `packages/schema` | 契约（Zod），导出 JSON Schema 给其他语言（ADR 0003） | 仅 zod |
| `packages/core` | vault 解析、链接、索引、BibTeX；纯本地，无网络 | schema |
| `packages/api-client` | 调用 Hub 的 SDK | schema |
| `apps/cli` | 命令行 | core, schema |
| `apps/hub` | API、队列、调度、MCP | core, schema |
| `apps/runtime` | 设备 daemon（与 hub 只走 HTTP） | schema |
| `apps/feishu-bot` `apps/web` 等 | 各个客户端 | api-client |

禁止：反向依赖、apps 之间互相依赖、core 做网络请求。由 `bun run lint:deps` 强制。
CLI、Hub、Runtime 用 `bun build --compile` 编译为单个二进制，分别部署到 Mac 和服务器。

## 4. 关键设计

- **Hub 是唯一的写入裁判**：程序（CLI、AI、飞书、Runtime）的写入一律经过 Hub API；人可以在 Obsidian 里直接改文件，
  Hub 监听并补全，不拒绝、不覆盖人的改动。git 只做历史与备份（ADR 0007）。
- **Vault 是唯一事实来源**；SQLite 只是派生索引，可随时删除重建。
- **部署不绑定位置**：Hub 只讲 HTTP、默认只监听 `127.0.0.1`，HTTPS 交给反向代理；所有 API 都要求 token，
  内网也不例外（ADR 0007）。
- **AI 提议，链接由人建立**：AI 的提议进入 Hub 的提议队列，由人接受后才写入；AI 不能直接写入人拥有的链接
  或改人写的正文（ADR 0006）。
- **论文以 citekey 为人可读的身份**：`He_2020_LightGCN`，同时是文件名、链接和 `\cite{}` 的 key（ADR 0004）。
- **元数据由 Lumio 负责，Obsidian 只是编辑器**：用 `lumio new <类型>` 创建，或随手写后由 `lumio sync`
  （P1 起由 Hub 自动）补全；两条路径共用同一个补全器（ADR 0009）。
- **vault 中的空字段视为未填写**（ADR 0008）。
- **执行不怕中断**：区分 Job 与 Attempt；exit 0 不等于成功；状态不明时交给人，不自动重试（ADR 0005）。
- **Agent 不自己实现**；Runtime 通过适配器调用现成 agent：`run(job, workspace) → result`。
- **飞书只做入口与通知**；本地内容单向发布到飞书，飞书原生文档以只读快照拉回。
- **密钥**：配置只写占位符，由 Runtime 从本机 secret store 注入。

## 5. 阶段

| 阶段 | 内容 | 涉及模块 |
|---|---|---|
| P0 | `lumio new paper`（arXiv/DOI → 笔记 + BibTeX）、`lumio new idea`、`lumio sync`（补全元数据） | schema, core, cli |
| P1 | indexer + MCP：让 AI 查询链接、由想法串出带引用的报告初稿 | core, hub, api-client |
| P2 | 任务/实验；Runtime + job 派发；Python 实验 SDK；Chrome 插件入库 | runtime, hub, sdk/python, chrome-ext |
| P3 | 飞书 Bot、多维表格镜像、定时工作流 | feishu-bot, hub |
| P4 | Web Dashboard、Docker/Nix、对外 SDK、手机端 | web, infra, mobile |
