# 0007 Hub 是唯一的写入裁判，git 只做历史与备份

- 状态：**Proposed**（方向已获同意，待人类审阅本文后改为 Accepted）
- 日期：2026-10-22
- 影响：ADR 0001、ADR 0006、`docs/ARCHITECTURE.md`（审阅通过后一并修改）

## 背景
原设计中 vault 的 git 仓库是事实来源，手机、Mac、服务器上的 AI 都直接向它写入，靠 git 合并。
这是多写入方模型，有三个问题：
1. 同时修改同一文件时，git 只报冲突，没有任何一方负责裁决。
2. ADR 0006（AI 只能提议）只能靠事后 review 保证，无法在写入时执行。
3. Runtime 的结果要经过 commit、分支、PR 才能回到 vault，对单人使用太重。

另一方面，此前一版项目采用"Core 是唯一权威、外部改文件即冲突"的设计，导致 Obsidian
无法使用、所有界面都要自己做，最终失控。本 ADR 要同时避开这两个问题。

## 决定
1. **Hub 是唯一的写入裁判。** AI、CLI、飞书、Runtime 等**程序**的写入一律通过 Hub API。
   Hub 负责校验（`@lumio/schema`）、执行 ADR 0006、写文件、更新索引。
2. **数据格式仍是 Markdown 文件。** Hub 的数据目录就是 Obsidian vault，SQLite 只是派生索引。
3. **人可以直接编辑文件。** Hub 监听数据目录的变化，自动校验并重建索引。frontmatter 不合法时
   提示人修正，**不拒绝、不覆盖**人的改动。
4. **git 只做历史、备份与撤销。** 由 Hub 定期或在写入后自动提交，不再作为协作或同步协议。
   `.git` 放在同步目录之外（例如 `~/Projects/lumio-vault.git`），vault 内只留指针文件。
5. **AI 的提议存在 Hub 中**（提议队列），由人在客户端接受或拒绝，不再使用 git 分支或 PR。
6. **Hub 的位置可配置。** 代码不假设自己运行在哪台机器上，数据目录通过配置指定。

## 部署（当前）
- Hub 运行在 Mac 上，数据目录为 iCloud 中的 Obsidian vault `Lumio`；手机、iPad 通过
  Obsidian + iCloud 访问，无需额外开发。
- 服务器上的 Runtime 通过 Tailscale 调用 Mac 上的 Hub。
- 已知代价：Mac 离线时，服务器与其他设备之间不同步。若将来把 Hub 迁到服务器，需要为
  手机/iPad 换一种同步方式（如 Obsidian Sync、Syncthing），届时另立 ADR。

## P0 的过渡
P0 尚无 Hub。`lumio paper add` 直接调用 `@lumio/core` 写文件，性质等同于人手动编辑；
P1 引入 Hub 后，CLI 改为调用 Hub API。

## 审阅通过后需要同步修改
- ADR 0001：事实来源由"vault git 仓库"改为"Hub 的数据目录"。
- ADR 0006：提议的载体由 git 分支 / PR 改为 Hub 内的提议队列。
- `docs/ARCHITECTURE.md`：架构图与"关键设计"一节。

## 后果
- 好处：写入有唯一裁判，冲突与 AI 权限都在写入时处理；Obsidian 照常可用；git 历史完整。
- 代价：Hub 必须在线才能接受程序写入；Hub 需要实现文件监听与"外部修改"的处理逻辑。
