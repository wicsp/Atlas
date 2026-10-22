# 0001 代码用 monorepo，数据用独立 vault 仓库

- 状态：Accepted
- 日期：2026-10-22

## 背景
后期会有 CLI、Hub、Runtime、飞书 Bot、Chrome 插件、Web、手机端，全部依赖同一套契约；
开发者是一个人加多个 AI。

## 决定
- 所有代码放在一个 monorepo（本仓库）。
- 笔记、论文、任务等数据放在独立的 vault 仓库，格式为 Markdown + YAML frontmatter。

## 后果
- 好处：契约只有一份；AI 能在一个 PR 里看到并修改所有受影响的部分；CI 统一守住边界。
  数据与代码生命周期分离，应用废弃时数据仍可用 Obsidian 打开。
- 代价：monorepo 同时有 Cargo 与 pnpm 两套工具链。
- 何时拆分：某部分要单独开源、有他人参与、或发布节奏完全不同时，优先"发布成独立包"而非搬仓库。
