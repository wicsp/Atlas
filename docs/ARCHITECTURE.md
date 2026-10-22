# Lumio 架构

> 本文件由人类批准。AI 可以提议修改，但须通过 ADR。

## 1. 目标与非目标

**目标**：在一个地方管理论文笔记、想法、项目/任务、实验结果；把想法通过链接串成报告；
把工作派给 Mac 或服务器上的 AI，并支持定时工作流。

**非目标**（至少在 P3 之前）：自己写编辑器、自己写 agent 循环、多用户与权限、与飞书双向同步正文。

## 2. 总体结构

```
┌─────────── 入口层（可替换）───────────┐
│ CLI │ Obsidian │ 飞书 Bot/多维表格 │ Web/插件/手机(后期) │
└───────────────┬───────────────────────┘
                │ HTTP API / MCP
┌───────────────▼───────────────────────┐
│ Hub（实验室服务器）                      │
│  indexer: vault → SQLite（全文、链接图） │
│  job 队列 + 定时调度 + MCP server        │
└──────┬─────────────────────┬──────────┘
       │ Tailscale            │
┌──────▼──────┐       ┌──────▼──────┐
│ Runtime@Mac │       │ Runtime@服务器│   领取 job → 调用 claude/codex/pi/脚本
└──────┬──────┘       └──────┬──────┘
       └── 结果写回 vault（git commit / 分支 / PR）──┘

Vault：独立 git 仓库，唯一事实来源
  papers/ ideas/ projects/ tasks/ experiments/ reports/ refs.bib
```

## 3. 模块与依赖方向

| 模块 | 职责 | 可以依赖 |
|---|---|---|
| `schema/` | 契约（JSON Schema） | — |
| `crates/core` | vault 解析、链接、索引、BibTeX；纯本地，无网络 | 生成的类型 |
| `crates/cli` | 命令行 | core |
| `crates/hub` | API、队列、调度、MCP | core |
| `crates/runtime` | 设备 daemon | core（与 hub 只走 HTTP） |
| `packages/api-client` | TS SDK | 生成的类型 |
| `apps/*` | 各个 TS 客户端 | api-client |

禁止：反向依赖、apps 之间互相依赖、runtime ↔ hub 代码依赖、core 做网络请求。

## 4. 关键设计

- **Vault 是唯一事实来源**；SQLite 只是派生索引，可随时删除重建。
- **人与 AI 通过同一套文件协作**；AI 的产出以 commit/分支/PR 回到 vault，由人 review 合并。
- **AI 提议，链接由人建立**：AI 可以写草稿、提议链接，但不能直接写入人拥有的链接或改人写的正文（ADR 0006）。
- **论文以 citekey 为人可读的身份**：`He_2020_LightGCN`，同时是文件名、链接和 `\cite{}` 的 key（ADR 0004）。
- **执行不怕中断**：区分 Job 与 Attempt；exit 0 不等于成功；状态不明时交给人，不自动重试（ADR 0005）。
- **Agent 不自己实现**；Runtime 通过适配器调用现成 agent：`run(job, workspace) → result`。
- **飞书只做入口与通知**；本地内容单向发布到飞书，飞书原生文档以只读快照拉回。
- **密钥**：配置只写占位符，由 Runtime 从本机 secret store 注入。

## 5. 阶段

| 阶段 | 内容 | 涉及模块 |
|---|---|---|
| P0 | schema 定稿；论文入库（arXiv/DOI → 笔记 + BibTeX）；Obsidian 编辑 | schema, core, cli |
| P1 | indexer + MCP：让 AI 查询链接、由想法串出带引用的报告初稿 | core, hub |
| P2 | 任务/实验；Runtime + job 派发；Python 实验 SDK；Chrome 插件入库 | runtime, hub, sdk/python, chrome-ext |
| P3 | 飞书 Bot、多维表格镜像、定时工作流 | feishu-bot, hub |
| P4 | Web Dashboard、Docker/Nix、对外 SDK、手机端 | web, infra, mobile |
