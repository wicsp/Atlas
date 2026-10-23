# P0-6 vault 目录分组与路径映射

- 负责：后端（Codex）　Review：Claude
- 相关 ADR：0012（Accepted）、0009
- 涉及：`packages/core`、`apps/cli`
- 依赖：P0-5

## 背景
ADR 0012 把 vault 分为 `library / research / plan / create / life / files` 六个大类。
现有代码在 `vault.ts`（`DIRECTORIES`）、`paper.ts`、`create.ts` 中硬编码了 `papers/`、`ideas/`。

## 范围

### packages/core
1. 新增**唯一的**路径映射表，取代 `DIRECTORIES`：

   | 路径 | 类型 | 私密 |
   |---|---|---|
   | `library/papers` | paper | 否 |
   | `library/sources` | source | 否 |
   | `research/ideas` | idea | 否 |
   | `research/experiments` | experiment | 否 |
   | `plan/projects` | project | 否 |
   | `plan/tasks` | task | 否 |
   | `create/posts` | post | 否 |
   | `life/assets` | asset | **是** |

   导出"按类型取目录"的函数；其他代码一律通过它得到路径。
2. `scanVault`：
   - 按映射表扫描，类型目录下递归扫描子文件夹（现有行为保留）；
   - 返回的 `VaultFile` 增加 `private: boolean`；
   - 跳过 `*.excalidraw.md`，以及 frontmatter 含 `excalidraw-plugin` 键的文件；
   - `research/reports`、`files/` 及映射表以外的位置一律不扫描。
3. `paper.ts`、`create.ts` 改用映射表；去重、冲突后缀等逻辑只在 `library/papers/` 下进行。
4. 补全器（`fill.ts`）支持 source、post、asset：只补公共字段（`id`、`type`、`title`、`created`、`updated`）
   和带默认值的字段，规则与现有类型相同。
5. `refs.bib` 的输出位置改为 `library/refs.bib`（如果当前代码已经生成它）。

### apps/cli
6. `lumio sync` 的输出使用新的相对路径；补全私密实体时照常处理，但输出里只显示路径，不显示字段内容。
7. `lumio new paper`、`lumio new idea` 写入新位置，输出新的相对路径。

### fixtures
8. 把 `fixtures/` 中的 vault 样例改为新的目录结构；增加一个子文件夹样例
   （如 `library/sources/obsidian/x.md`）和一个 Excalidraw 样例。

## 不做
- 不搬迁真实 vault（AGENTS.md 规则 6）。真实 vault 的迁移在合并后由人执行，见下文。
- 不加 `lumio new source|post|asset`，不实现 `--include-private`（属于 P1 的查询命令）。
- 不提供旧路径的兼容模式。

## 验收标准
1. `bun run check` 通过；代码中除映射表外，不再出现 `"papers/"`、`"ideas/"` 等硬编码路径（`grep` 验证）。
2. `lumio sync` 对新 fixture：识别全部八种目录的类型；子文件夹中的文件按所在类型目录处理；
   Excalidraw 文件、`files/`、`research/reports/` 下的文件不出现在输出中。
3. `life/assets/` 下的文件在 `scanVault` 结果中 `private: true`。
4. `lumio new paper 2002.02126` 写入 `library/papers/He_2020_LightGCN.md`；
   `lumio new idea 测试` 写入 `research/ideas/测试.md`。

## 合并后：迁移真实 vault（人执行，或由人指示 Claude 执行）
```
library/papers   ← papers/
research/ideas   ← ideas/
research/experiments ← experiments/
research/reports ← reports/
plan/projects    ← projects/
plan/tasks       ← tasks/
library/refs.bib ← refs.bib
files/templates  ← templates/
```
同时更新 vault 的 `README.md`，以及 Obsidian「模板」插件的文件夹设置（改为 `files/templates`）。
迁移后运行一次 `lumio sync`，结果应为"补全 0 个"。
