# 0004 论文 citekey 格式：`姓_年份_标题缩写`

- 状态：Accepted
- 日期：2026-10-22（同日修订：分隔符由 `:` 改为 `_`；姓氏大小写规则明确为"只改首字母"）

## 背景
citekey 同时用于笔记间的链接、`refs.bib` 的 key、论文写作中的 `\cite{}`，以及笔记的文件名。
它需要人一眼能认出是哪篇论文，并且在整个 vault 里稳定不变。

## 决定
格式为 `<第一作者姓>_<年份>_<标题缩写>`，例如 `He_2020_LightGCN`。

| 部分 | 规则 | 例子 |
|---|---|---|
| 姓 | 第一作者的姓，转写为 ASCII；去掉空格、连字符、撇号后直接拼接，保留姓氏前缀；**只把第一个字母改成大写，其余字母保持原样** | `He`、`Muller`（Müller）、`VanderMaaten`（van der Maaten）、`FernandezLopez`（Fernández-López）、`OBrien`（O'Brien） |
| 年份 | 四位数，取首次公开的年份（arXiv 版与正式版不同年时，以 refs.bib 当前采用的版本为准） | `2020` |
| 缩写 | 论文常用名称或方法名；没有现成名称时，取标题关键词的首字母或词干 | `LightGCN`、`ResNet`、`GPT3` |

- schema 正则：`^[A-Z][A-Za-z]*_[0-9]{4}_[A-Za-z0-9]+$`
- 冲突时在缩写末尾加小写字母：`He_2020_LightGCNb`。
- 入库时由工具生成候选 citekey，**缩写由人确认或修改**；一旦确认，不再改动。
- citekey 就是文件名：`papers/He_2020_LightGCN.md`；笔记里写 `[[He_2020_LightGCN]]`，
  写论文时写 `\cite{He_2020_LightGCN}`，三处完全一致，不需要任何转换。

## 为什么不用 `:`、`/`、`-`
- `:` 不能出现在 Obsidian、macOS、Windows 的文件名里，会迫使文件名和 citekey 不一致。
- `/` 是路径分隔符，无法用于文件名。
- `-` 会让编辑器和终端双击时把 key 切成三段；`_` 能整体选中，且 LaTeX/BibTeX 都支持。

## 后果
- 好处：一个字符串贯穿链接、文件名和引用，没有映射规则需要记。
- 代价：与 Google Scholar 默认导出的 key（如 `he2020lightgcn`）不同，导入外部 BibTeX 时需要重写 key。
