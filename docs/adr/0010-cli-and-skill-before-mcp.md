# 0010 AI 通过 CLI + skill 访问 Lumio；MCP 推迟为可选适配层

- 状态：Accepted
- 日期：2026-10-23
- 修改：`docs/ARCHITECTURE.md` 中 P1 原定的"indexer + MCP"

## 背景
Lumio 要让 AI 查询笔记、链接，并提出修改提议。接入的 AI 主要是 Claude Code、Codex、pi，
它们都运行在有 shell 的环境里（Mac 或服务器）。

2026 年的情况：
- MCP 的主要问题是成本：工具定义常驻上下文，单个服务器几十个工具就可能占用数万 token。
- skill 平时只常驻一行简介，用到时才加载完整说明；CLI 在被调用前不占上下文，结果还能在脚本里处理后再返回。
- pi 于 2026-10 的 1.0 版本加入了 MCP，但方式是 Codemode：工具默认不进入模型声明，按需搜索、在脚本中调用。
  MCP 从"所有数据都经过模型的通道"退为"工具目录"。
- 通行的划分：有 shell 的本地 agent 用 CLI + skill；没有 shell 的客户端、托管服务、需要 OAuth 的场景用 MCP。

## 决定
1. **所有能力只实现在 Hub HTTP API 中。** 搜索、查看、链接查询、提议等逻辑都在 Hub；ADR 0006 的
   "AI 只能提议"由 Hub 在写入时强制执行，与 AI 从哪个入口进来无关。
2. **P1 的 AI 入口是 CLI + skill：**
   - `lumio` 增加查询与提议命令（如 `search`、`show`、`links`、`propose`），全部支持 `--json`。
   - 仓库内提供 `skills/lumio/SKILL.md`：何时使用、命令列表、AI 的边界。Claude Code、Codex、pi 共用这一份。
3. **MCP 推迟，作为可选的薄适配层。** 只有在出现**没有 shell 的客户端**需求时（例如在手机 Claude App 里
   查询笔记）才实现：一个把 MCP 工具映射到 Hub API 的适配器，走 ADR 0007 的 HTTPS + token。
   不在 MCP 层实现任何业务逻辑。

## 后果
- 好处：上下文成本最低；三家 agent 共用一份 skill；agent 可以用脚本组合调用、批量处理；
  协议换代时只需替换最外层。
- 代价：没有 shell 的客户端在 MCP 适配器完成前无法访问 Lumio；CLI 的 `--json` 输出成为
  事实上的接口，需要保持稳定（用 `@lumio/schema` 描述）。
