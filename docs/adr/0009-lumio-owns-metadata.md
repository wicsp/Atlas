# 0009 元数据由 Lumio 负责；统一的创建命令

- 状态：Accepted
- 日期：2026-10-22（2026-10-23 按 ADR 0012 修订目录写法）

## 背景
手写 frontmatter 不现实：标题、作者、citekey、ULID、时间戳都容易出错或无法手写。
若改用 Obsidian 模板或 Templater 生成，会把 Lumio 的规则绑在 Obsidian 的插件上，
而且调用外部命令的 Obsidian 插件只能在桌面端运行，手机和 iPad 上不可用。

## 决定
1. **Obsidian 只是编辑器和阅读器。** 所有元数据（`id`、`type`、`created`、`updated`、
   默认值，以及论文的 citekey 与书目信息）都由 Lumio 生成，不依赖 Obsidian 的模板或插件。
2. **两种创建方式，结果完全一致：**
   - **显式创建**：通过 Lumio 的命令（P0）或 Hub API（P1 起，供飞书、快捷指令、网页调用）。
   - **随手写，自动补全**：在对应目录下直接新建普通 Markdown（可以不写 frontmatter），
     由 Lumio 补全缺失的元数据。P0 用 `lumio sync` 手动触发；P1 起由 Hub 监听文件变化自动完成。
3. **命令统一为"动词在前"**：
   ```
   lumio new paper <arXiv号 | DOI | 链接>
   lumio new idea  <标题>
   lumio sync
   ```
   以后新增命令沿用此规律（如 `lumio list papers`、`lumio export bib`）。
4. **统一的内部流水线**：输入 → 解析器（按类型）→ 补全器（所有类型共用）→ 校验 → 写文件。
   `new` 与 `sync` 共用同一个补全器，保证两种创建方式产生的元数据规则相同。
5. **补全规则**：
   - 类型由路径中的类型目录决定（`library/papers/` → paper，`research/ideas/` → idea，依此类推；
     完整映射见 ADR 0012，类型目录下可以有子文件夹）。
   - 标题缺失时取文件名；`created` 取文件创建时间；`id` 新生成。
   - 只补缺失的字段，**不覆盖**已有的值，**不改动正文与链接**（与 ADR 0006 一致）。
   - 无法自动补全的必填项（如论文的 citekey 缩写）不猜测，报告给人处理。
6. **vault 中的 `templates/` 不再作为 Obsidian 模板使用**；笔记结构由 Lumio 在创建时生成。

## 范围
- P0：`lumio new paper`、`lumio new idea`、`lumio sync`。
- task、experiment 的创建留到 P2，与 Runtime 派活一起设计。

## 后果
- 好处：数据规则只存在于 Lumio 一处；手机上随手写的笔记无需任何插件即可纳入体系。
- 代价：手写的笔记在被补全之前，暂时不符合 schema；Lumio 需要能容忍并报告这种中间状态。
