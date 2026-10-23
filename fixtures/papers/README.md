# P0-3 公开响应 fixtures

2026-10-22 直接保存以下公开端点返回的原始响应，未改写内容；这些是公开书目数据，不来自用户 vault。
普通测试仅从本目录读取，不联网。新增笔记及去重样例都写到临时目录。

| 文件 | 原始来源 |
|---|---|
| `2002.02126.xml` | https://export.arxiv.org/api/query?id_list=2002.02126 |
| `2002.02126.bib` | https://arxiv.org/bibtex/2002.02126 |
| `2403.14720.xml` | https://export.arxiv.org/api/query?id_list=2403.14720 |
| `2403.14720.bib` | https://arxiv.org/bibtex/2403.14720 |
| `2406.13352.xml` | https://export.arxiv.org/api/query?id_list=2406.13352 |
| `2406.13352.bib` | https://arxiv.org/bibtex/2406.13352 |
| `crossref-lightgcn.json` | https://api.crossref.org/works/10.1145%2F3397271.3401063 |
| `crossref-lightgcn.bib` | https://doi.org/10.1145/3397271.3401063（Accept: application/x-bibtex） |

所有抓取请求使用 `User-Agent: lumio/0.0.0`。arXiv 请求之间间隔至少 3 秒。
arXiv BibTeX 原始响应中的行尾空格也原样保留，用于验证只替换 key 而不改动其余内容。
