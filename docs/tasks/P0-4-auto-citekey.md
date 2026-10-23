# P0-4 citekey 全自动生成

- 负责：后端（Codex）　Review：Claude
- 相关 ADR：0004（2026-10-23 修订）
- 涉及：`packages/core`（citekey、paper）、`apps/cli`（去掉确认流程）
- 依赖：P0-3（已合并）

## 背景
P0-3 中，第一作者的姓含有分解不掉的字母（Søgaard、Łukasiewicz、中文姓名）时，论文完全无法添加，
连 `--abbr` 也救不了；并且每次添加论文都要人确认 citekey。人类决定：
**无法转写的字符直接删除；citekey 全自动生成，不再确认。** 具体规则见修订后的 ADR 0004。

## 用法（修改后）
```
lumio new paper <输入> [--vault <路径>] [--abbr <缩写>]
```
- 删除交互确认和 `--yes` 参数。传入 `--yes` 时按未知参数报错即可。
- `--abbr` 保留，作为可选的主动指定。

## 范围

### packages/core
1. **姓**：NFD 分解 → 去掉附加符号 → **删除所有不是 `[A-Za-z]` 的字符** → 首字母大写，其余不变。
   结果为空时用 `Anon`。不加转写表。
2. **缩写**：
   - 标题第一个冒号前若是单个词（不含空白），取它并删除不是 `[A-Za-z0-9]` 的字符（`GPT-4` → `GPT4`）。
   - 否则（或上一步结果为空），取标题前四个实词的首字母大写；先删除非 ASCII 字母数字的字符再判断实词。
   - 结果为空时用 `Paper`。
   - `--abbr` 给出时：同样删除非法字符；结果为空则报错。
3. 年份不合法（非四位数）仍然报错，这是来源数据的问题，不要掩盖。
4. 上述规则保证结果**总是**匹配 `CITEKEY_PATTERN`；保留最终的 schema 校验作为断言。
5. **冲突自动加后缀**：`papers/<citekey>.md` 已存在、且不是同一篇论文（arXiv/DOI 去重检查已通过）时，
   依次尝试 `b`、`c`……`z`，取第一个不存在的；全部占用时报错。
   与"同名文件已存在"的并发保护配合：写入仍使用不覆盖模式，遇到 `FILE_EXISTS` 时尝试下一个后缀。
6. 去掉"候选 / 已确认"两种类型的区分，简化为一个返回 citekey 的函数；删除不再使用的代码。

### apps/cli
7. 删除 `paper-confirm.ts` 及交互读取逻辑；`new paper` 不再读取标准输入，在非终端环境下也能直接运行。
8. 成功时输出：`papers/Hines_2024_DAIP.md`（与现在一致）。

## 不做
- 不加转写表（ø→o 之类），不加 `--surname` 参数。
- 不改 citekey 的正则（`packages/schema` 不变，**不是契约变更**）。

## 验收标准
1. `bun run check` 通过。
2. citekey 测试（与 ADR 0004 表格一致）：`Muller`、`VanderMaaten`、`FernandezLopez`、`OBrien`、
   `Sgaard`（Anders Søgaard）、`Ukasiewicz`（Jan Łukasiewicz）、`Anon`（中文姓名）；
   缩写 `LightGCN`、`AgentDojo`、`GPT4`（标题 `GPT-4: ...`）、`DAIP`（Spotlighting）、
   全中文标题 → `Paper`。
3. `--abbr Spotlighting` 得到 `Hines_2024_Spotlighting`；`--abbr "!!"` 报错。
4. 冲突：vault 中已有 `He_2020_LightGCN.md`（另一篇论文）时，新论文写入 `He_2020_LightGCNb.md`；
   `b` 也存在时写入 `c`。同一篇论文（arXiv 或 DOI 相同）仍报"已存在"，不加后缀。
5. 在非终端环境（标准输入不是 TTY）下，不带任何参数的 `lumio new paper 2403.14720` 能成功写入。
6. 生成的笔记通过 `Paper` 校验，且之后运行 `lumio sync` 为"补全 0 个"。
