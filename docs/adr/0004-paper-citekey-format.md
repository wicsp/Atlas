# 0004 论文 citekey 格式：`姓:年份:标题缩写`

- 状态：Accepted
- 日期：2026-10-22

## 背景
citekey 同时用于笔记间的链接、`refs.bib` 的 key 和论文写作中的 `\cite{}`。
它需要人一眼能认出是哪篇论文，并且在整个 vault 里稳定不变。

## 决定
格式为 `<第一作者姓>:<年份>:<标题缩写>`，例如 `He:2020:LightGCN`。

| 部分 | 规则 | 例子 |
|---|---|---|
| 姓 | 第一作者的姓，转写为 ASCII，首字母大写；去掉空格、连字符、撇号，保留姓氏前缀 | `He`、`Muller`（Müller）、`VanDerMaaten`（van der Maaten）、`FernandezLopez` |
| 年份 | 四位数，取首次公开的年份（arXiv 版与正式版不同年时，以 refs.bib 当前采用的版本为准） | `2020` |
| 缩写 | 论文常用名称或方法名；没有现成名称时，取标题关键词的首字母或词干 | `LightGCN`、`ResNet`、`GPT3` |

- schema 正则：`^[A-Z][A-Za-z]*:[0-9]{4}:[A-Za-z0-9]+$`
- 冲突时在缩写末尾加小写字母：`He:2020:LightGCNb`。
- 入库时由工具生成候选 citekey，**缩写由人确认或修改**；一旦确认，不再改动。

### 文件名
Obsidian、macOS 和 Windows 都不允许文件名里出现 `:`，所以文件名用 `-` 替换：
`papers/He-2020-LightGCN.md`。

- 因为姓和缩写里都没有 `-`，这个映射可以无损地反向还原。
- 笔记里的链接写作 `[[He-2020-LightGCN]]`；导出报告时，indexer 把它换成 `\cite{He:2020:LightGCN}`。
- frontmatter 的 `aliases` 自动包含 `He:2020:LightGCN`，在 Obsidian 里按原 citekey 也能搜到。

## 后果
- 好处：引用时一眼可读；和 Google Scholar 等常见工具的 key 风格相近；BibTeX 允许 key 中出现 `:`。
- 代价：文件名和 citekey 不完全相同，需要依赖上面这条固定映射规则。
