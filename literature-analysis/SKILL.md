---
name: literature-analysis
description: >-
  多源、多语言、多数据库学术文献检索分析与筛选工作台（Multi-source multilingual academic literature search,
  analysis and screening workbench）。自动生成标准化检索策略(MeSH/平台语法/多语言翻译),自动检索 API 数据库
  (PubMed/OpenAlex/Crossref/arXiv/Semantic Scholar/Europe PMC/DOAJ/HAL),并驱动浏览器检索无 API 数据库
  (Google Scholar/知网CNKI/万方/维普/中华医学期刊/CiNii/NDL/BASE/CyberLeninka/eLibrary),自动翻页抓取,
  汇总 xlsx + Markdown 表格。从摘要精确提取研究设计/人群/样本量/模态/方法/验证/性能/发现/局限/证据等级等字段,
  按纳入/排除标准筛选文献。Use when the user asks to search literature across databases, build search strategies,
  translate queries for foreign databases, retrieve papers and abstracts, extract structured fields from abstracts,
  screen/shortlist papers, or produce literature comparison tables (检索文献/查文献/文献综述/摘要提取/文献筛选/多数据库检索).
---

# 文献检索分析工作台 (Literature Analysis Workbench)

> 开发者：解放军总医院第一医学中心 & 南开大学医学院团队。
> 项目早期思路来源于 [ustc-ai4science/academic-search](https://github.com/ustc-ai4science/academic-search)。
> 完全开源，允许任何形式的二次开发与使用；使用时请注明来源。

## 标准工作流（用户提出检索后按此执行）

### Step 1 - 生成多语言、多数据库标准化检索策略

把用户的主题拆成概念（疾病/人群、干预/暴露、结局、模态等），自动生成每个平台的原生检索式，并按目标语言翻译：

```powershell
# 全平台策略生成 + 命中数测试（MeSH/[tiab] 针对 PubMed，其余平台自动转各自语法）
python scripts/literature.py strategy --concepts "radiomics|lung cancer|prognosis" --sources pubmed,openalex,crossref,arxiv,semanticscholar,europepmc,doaj,hal --dates "2023/01/01:2026/08/05" --test --strategy-out strategy.json

# 跨库检索词转换（含日期/字段语法）
python scripts/literature.py translate --concepts "radiomics|lung cancer|prognosis" --sources pubmed,arxiv,europepmc --dates "2023/01/01:2026/08/05" --test

# 为无 API 数据库准备目标语言检索词（中/日/德/法/俄）
python scripts/literature.py translate-query --text "radiomics lung cancer prognosis" --to zh-CN
```

规则：所有检索式必须先测命中数再使用；零命中的变体通常是语法错误或字段过窄，不得直接发布。日期范围默认写到
当前日期（含 2026 年 8 月最新文献），确保检索覆盖到最新。

### Step 2 - API 数据库自动化检索并汇总

```powershell
# 单文件多查询（PubMed 变体合并去重）
python scripts/literature.py search-all --queries-file queries.txt --max 15 --out results.json

# 多平台同时检索，按 DOI/标题合并去重
python scripts/literature.py search-multi --query "radiomics lung cancer prognosis" --sources pubmed,openalex,crossref,arxiv,semanticscholar,europepmc,doaj,hal --max 10 --from 2023/01/01 --to 2026/08/05 --sort citations --out results.json
```

`search-multi` 覆盖 8 个开放 API 平台，逐平台打印实际使用的检索式；不可用的平台失败不中断并说明原因。
OpenAlex 记录额外携带引用数、OA 状态、OA PDF 链接。之后用 `lite` 先出紧凑扫描表，让用户圈定核心文献。

### Step 3 - 无 API 数据库：浏览器自动搜索、翻页循环、完整抓取

Google Scholar、知网（CNKI）、万方、维普、中华医学期刊（medjournals.cn）、CiNii/NDL（日本）、
BASE（德国）、CyberLeninka/eLibrary（俄罗斯）没有可公开调用的 API 或反爬严格。用统一命令驱动
Chrome（默认浏览器或内置浏览器），自动翻译检索词、进入站点、循环翻页、突破单页显示限制，取回完整文献信息：

```powershell
python scripts/literature.py browser-search --engine cnki --query "radiomics lung cancer prognosis" --max 50 --out cnki.json --xlsx cnki.xlsx
python scripts/literature.py browser-search --engine wanfang --query "radiomics lung cancer prognosis" --max 60 --out wf.json --xlsx wf.xlsx
python scripts/literature.py browser-search --engine medjournals --query "radiomics lung cancer prognosis" --max 60 --out med.json --xlsx med.xlsx
python scripts/literature.py browser-search --engine google-scholar --query "radiomics lung cancer prognosis" --max 20 --out gs.json
python scripts/literature.py browser-search --engine ciinii --query "radiomics lung cancer" --max 20 --out ciinii.json --xlsx ciinii.xlsx
python scripts/literature.py browser-search --engine cyberleninka --query "radiomics lung cancer" --max 20 --out cyber.json --xlsx cyber.xlsx
python scripts/literature.py browser-search --engine elibrary --query "radiomics lung cancer" --max 20 --out el.json
```

引擎矩阵与已验证状态见 [references/browser-patterns.md](references/browser-patterns.md)。要点：

- 查询自动翻译：CNKI/万方/维普/中华医学期刊→中文，CiNii/NDL→日文，CyberLeninka/eLibrary→俄文，BASE→德文。
- 自动翻页：CNKI（53/53 全量，已验证）、万方（2,417 条全量翻页，已验证）、中华医学期刊
  （API pageSize=50 循环，返回标题/DOI/作者/期刊/卷期/页码/摘要，已验证）。
- 登录类站点（CNKI/万方/维普/eLibrary）：在可见 CDP Chrome 窗口登录一次，会话保持后重跑即可。
- 网络被墙的站点（NDL 503、维普 502、BASE 403）引擎保持可用；网络恢复后直接生效，覆盖不足时用
  CiNii/OpenAlex/DOAJ/CyberLeninka 补足，并如实说明。
- 需要 CDP Chrome：`--remote-debugging-port=9222 --user-data-dir="D:\chrome-cdp"`；脚本自动探测端口。

### Step 4 - 精确提取、筛选并交付

```powershell
# 一键自动提取（16 列全字段，含 evidence 原文引用）
python scripts/literature.py extract --in results.json --out overview.csv --xlsx overview.xlsx --topic "radiomics lung cancer prognosis" --include "external validation|prospective" --exclude "review|animal|editorial"

# 关键词初筛（随后必须逐条语义复核）
python scripts/literature.py screen --in results.json --out triage.csv --include "external validation|prospective" --exclude "review|animal|editorial"

# OpenAlex 补全引用数/OA，导出 BibTeX/RIS，批量下载 OA PDF
python scripts/literature.py enrich --in results.json --out enriched.json
python scripts/literature.py export --in enriched.json --out references.bib
python scripts/literature.py download-pdf --in results.json --dir pdfs --timeout 40
```

交付物：

- `--xlsx`：格式化 Excel（加粗表头、冻结首行、筛选器）；CSV 用 UTF-8 BOM，Excel 直接打开不乱码。
- 对话框内同时给出一张美观的 Markdown 汇总表（含来源、标题、期刊、年份、摘要片段、DOI/链接、相关性、决策）。
- 报告找到多少条、纳入/排除/不确定各多少及理由；绝不添加来源之外记录，绝不改动 PMID/DOI/标题/数字。

## 命令速查

| 命令 | 作用 |
|------|------|
| `strategy --concepts A\|B --sources ... --dates ...` | 生成并测试多平台检索式（含 MeSH 查询） |
| `translate --concepts ... --sources ...` | 跨库检索词转换（各平台语法） |
| `translate-query --text ... --to zh-CN\|ja\|de\|fr\|ru` | 检索词翻译 |
| `search-all --queries-file ...` | 多查询 PubMed 检索合并去重 |
| `search-multi --query ... --sources ...` | 8 个 API 平台同时检索合并 |
| `browser-search --engine ... --query ... [--xlsx]` | 无 API 平台浏览器检索（自动翻译+翻页） |
| `lite --in results.json` | 紧凑扫描表（两遍策略第一遍） |
| `extract --in ... --xlsx ...` | 一键全字段提取 + 筛选 |
| `screen --in ...` | 关键词初筛 |
| `author-search --author "Aerts HJWL" --affiliation ...` | 定向检索某作者/某单位 |
| `template --in ... --fields "..."` | 自定义字段提取 |
| `enrich --in ...` | OpenAlex 补全引用数/OA |
| `export --in ... --format bib\|ris` | 导出参考文献 |
| `download-pdf --in ... --dir pdfs` | 批量下载合法 OA PDF |

## PubMed 语法规则（手写检索式时必须遵守）

- 布尔：`AND`/`OR`/`NOT` 大写、空格分隔、括号分组：`(a OR b) AND c`。
- 字段标签：`[tiab]` 标题摘要、`[Mesh]` MeSH（自动扩展）、`[Majr]` 主要主题、`[dp]` 发表日期、
  `[pt]` 出版类型、`[la]` 语言、`[ta]` 期刊、`[au]` 作者、`[ad]` 单位、`[auid]` 作者标识。
- 短语加引号：`"lung cancer"[tiab]`；日期区间：`("2023/01/01"[dp] : "2026/08/05"[dp])`。
- 类型限定：`AND review[pt]`、`AND meta-analysis[pt]`、`NOT review[pt]`。
- 截断：`radiom*[tiab]` 扩大召回但增加噪声，慎用。
- MeSH（扩展+同义词）召回最大；`[tiab]` 引号短语精确度最高；混合两者平衡。

## 定向检索（指定单位/个人的文献）

```powershell
python scripts/literature.py author-search --author "Aerts HJWL" --affiliation "Harvard Medical School" --dates "2020/01/01:2026/08/05" --max 20 --out author_results.json
```

- `[au]` 用 "姓 名首字母" 格式；重名时试多种写法（`Zhang Y` vs `Zhang YC`）。
- `[ad]` 是自由文本：`"Fudan University"[ad] AND "Shanghai"[ad]`，同人不同科室写法不同。
- 身份唯一时优先 Author Identifier `[auid]` 或 ORCID。
- 重名常见：用合作者、科室、主题交叉验证确实属于该人后再引用。

## 提取与筛选精度规则（Step 4 必须遵守）

- 每一格只能来自摘要原文；摘要未提即写 `未提及 / Not stated`，绝不推断、估计或补数。
- 每个已填字段在 `evidence` 列给出逐字原文短语（如样本量 `"112 patients (mean age 75 years)"`）。
- 保留原始数字、单位、置信区间；区分作者结论与报道事实。
- `topic relevance` 按主题与标题+摘要的重合度评分：High>=0.7、Medium>=0.4、否则 Low。
- `decision`：include/exclude/uncertain；摘要缺少关键信息（如未提外部验证）时给 uncertain，不猜。
- 生物医学证据等级（并说明理由）：1 临床指南；2 系统综述/Meta 分析；3 RCT；
  4 前瞻队列+外部验证；5 回顾性+外部验证；6 回顾性+内部验证；7 横断面/病例对照/病例系列；
  8 叙述性综述/观点/预印本。摘要不足时标 unclear。
- 启发式规则可能误读（随机训练/测试划分不是 RCT；"需前瞻性试验证实"不代表本研究是前瞻性），
  逐条 QA 复核，规则不得压过仔细阅读。

## 输出约定

- 每条记录保留 `evidence` 列；没有原文证据的表格不可用于稿件。
- 写稿时直接复用短名单的 PMID/DOI，不要重敲参考文献。
- 多平台结果合并后统一进入 `extract` / `overview` / 筛选流水线。

## 参考文件

- [references/browser-patterns.md](references/browser-patterns.md)：浏览器引擎矩阵、验证记录、CDP 设置、
  CAPTCHA/登录处理、手动兜底流程（网站改版时先读这里再更新选择器）。
