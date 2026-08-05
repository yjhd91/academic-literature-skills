# Academic Literature Skills ｜ 学术文献技能

Multi-source academic literature search & analysis skills for Codex / Claude Code. 面向学术写作与文献调研的多源学术文献检索与分析技能。

**检索 → 合并去重 → 一键自动提取 → 精确筛选 → 批量下载 → 参考文献导出** 的完整闭环。
Full loop: **search → merge/dedupe → one-shot auto-extraction → precise screening → batch PDF download → reference export**.

## 技能组成 / Skills

| 技能 / Skill | 职责 / Role |
|------|------|
| **pubmed-live** | 实时 PubMed 检索与摘要抓取(NCBI E-utilities,纯标准库) / Real-time PubMed search & abstract retrieval |
| **literature-analysis** | 多平台检索、检索式工程、证据锚定提取、筛选、导出 / Multi-source search, query engineering, evidence-anchored extraction, screening, export |

---

## 能力总览 / Capabilities

### pubmed-live

| 能力 / Capability | 说明 / Description |
|------|------|
| 实时检索 / Real-time search | 直连 NCBI E-utilities,数据实时更新 / Live NCBI data, no cache |
| PubMed 原生语法 / Native syntax | `[tiab]` `[Mesh]` `[dp]` `[pt]`、布尔运算符、短语引号 / Boolean, field tags, phrases |
| 日期过滤 / Date filter | `--from/--to` 按出版日期严格过滤(带二次校验) / strict publication-date filtering with re-check |
| 定向检索 / Directed search | 作者 `[au]` + 单位 `[ad]` / author + affiliation |
| 输出 / Output | JSON / 紧凑文本,含标题、作者、期刊、DOI、PMCID、摘要 |

### literature-analysis

| 能力 / Capability | 说明 / Description |
|------|------|
| 检索式工程 / Query engineering | 自动查 MeSH,生成 MeSH/[tiab]/混合三套 PubMed 检索式,测试命中数并校验语法 / MeSH lookup, 3 query variants, hit-count testing, syntax validation |
| 多查询合并 / Multi-query merge | 检索变体按 PMID 去重 / dedupe by PMID |
| 多平台检索 / Multi-source search | 一次搜索覆盖 8 个开放 API 平台,按 DOI 去重 / 8 open-API sources, DOI dedupe |
| 两遍策略 / Two-pass | 第一遍轻量表(lite)→ 第二遍深提取(extract) / lightweight scan, then deep extraction |
| 一键自动提取 / Auto-extraction | 从摘要(结合标题)自动填充 10 个证据字段,找不到标 "Not stated" / rule-based extraction from abstract+title; never invents values |
| 精确筛选 / Precise screening | 按 `--include/--exclude` 自动判定 include/exclude/uncertain,理由可追溯 / criteria-based decisions with transparent reasons |
| 相关性打分 / Relevance scoring | 主题词与标题/摘要匹配度 → High/Medium/Low |
| 多源补全 / Enrichment | OpenAlex 引用数、OA 状态、OA PDF 链接 |
| 批量下载 / PDF batch | 只下载合法 OA PDF,%PDF 校验 + manifest 审计 / legal OA only, %PDF check, manifest audit |
| 导出 / Export | BibTeX / RIS / CSV / 格式化 Excel(xlsx) |

---

## 检索范围 / Search Coverage

### 开放 API 平台(脚本直接支持)/ Open-API sources (script-native)

| 平台 / Source | 覆盖 / Scope | 特点 / Notes |
|------|------|------|
| PubMed | 生物医学 / biomedical | 实时、语法最丰富、摘要全 / live, richest syntax, full abstracts |
| OpenAlex | 跨学科 / interdisciplinary | 2.5 亿+ 文献,引用数 + OA + 多语言期刊 / 250M+ works, citations, OA, multilingual journals |
| Crossref | DOI 元数据 | 引用数(is-referenced-by-count) |
| arXiv | CS / 物理 / 数学预印本 | 开放 PDF 直链 |
| Semantic Scholar | 引用图 / citation graph | 无密钥时限流(优雅降级)/ rate-limited without key |
| Europe PMC | 生物医学 + 全文 | 摘要全,开放全文链接 |
| DOAJ | 全球开放获取期刊 | 多语言(实测含阿拉伯语)/ multilingual |
| HAL | 法国开放仓储 / French OA | 法文文献,OA PDF |

### 浏览器辅助平台(无公开 API)/ Browser-assisted platforms (no public API)

Google Scholar、CNKI(知网)、万方、维普/中华医学期刊、CiNii/NDL(日本)、eLibrary(俄罗斯)没有公开批量 API 或强反爬/登录墙。
Google Scholar, CNKI, Wanfang, VIP, CiNii/NDL, eLibrary have no public bulk API or are anti-bot/login-gated.

- 不做假结果:不声称"已接入" / No fake results - never claim unsupported access
- 浏览器辅助路径:机构访问 + nature-downloader 技能 / Browser-assisted lookups with institutional access
- 多语言兜底:OpenAlex/Crossref/DOAJ 索引大量中、日、德、法、俄期刊 / OpenAlex/Crossref/DOAJ provide multilingual journal coverage

---

## 输出内容 / Outputs

### 总览表字段(23 列)/ Overview table fields (23 columns)

source、pmid、title、journal、pubDate、doi、abstract + **study design、population、sample size、imaging modality / data、method / model、validation、performance metrics、main findings、limitations、evidence level、citation count、open access status、topic relevance、decision、reason、evidence**

### 输出格式 / Formats

- CSV(UTF-8 BOM,Excel 直接打开不乱码 / opens correctly in Excel)
- 格式化 Excel xlsx(加粗表头、冻结首行、自动筛选 / bold header, freeze, autofilter)
- 对话框 Markdown 表格 / in-chat Markdown tables
- BibTeX / RIS 参考文献 / references
- 批量 PDF + `download_manifest.csv`(downloaded / skipped / failed / not_pdf)

---

## 命令速查 / Command Reference

### pubmed-live

```powershell
python scripts/pubmed.py search "radiomics lung cancer prognosis" --max 10 --sort relevance
python scripts/pubmed.py search "artificial intelligence" --sort pub_date --max 30 --from 2024/01/01 --to 2026/08/05
python scripts/pubmed.py fetch 28418006 40181378
```

### literature-analysis

```powershell
# 生成 PubMed 规范检索式并测试命中数 / build & test PubMed-syntax strategy
python scripts/literature.py strategy --concepts "radiomics|lung cancer|prognosis" --dates "2023/01/01:2026/08/05" --test --out queries.txt

# 多查询合并(PubMed)/ multi-query merge (PubMed)
python scripts/literature.py search-all --queries-file queries.txt --max 15 --out results.json

# 多平台检索(8 源)/ multi-source search (8 sources)
python scripts/literature.py search-multi --query "radiomics lung cancer prognosis" --sources pubmed,openalex,crossref,arxiv,semanticscholar,europepmc,doaj,hal --max 10 --from 2023/01/01 --to 2026/08/05 --sort citations --out results.json

# 第一遍轻量表 / two-pass pass 1
python scripts/literature.py lite --in results.json

# 一键自动提取 + 筛选 / one-shot auto-extraction + screening
python scripts/literature.py extract --in results.json --out overview.csv --xlsx overview.xlsx --topic "radiomics lung cancer prognosis" --include "external validation|prospective" --exclude "review|animal|editorial"

# 多源补全 / enrich (OpenAlex citations + OA)
python scripts/literature.py enrich --in results.json --out enriched.json

# 导出 / export
python scripts/literature.py export --in enriched.json --out references.bib
python scripts/literature.py export --in enriched.json --format ris --out references.ris

# 批量下载 OA PDF / batch download
python scripts/literature.py download-pdf --in results.json --dir pdfs --timeout 40

# 定向检索作者/单位 / author + affiliation search
python scripts/literature.py author-search --author "Aerts HJWL" --affiliation "Harvard Medical School" --dates "2020/01/01:2026/08/05" --max 20 --out author_results.json
```

---

## 安装方式 / Installation

### 方式一:Codex(推荐 / Recommended)

Windows PowerShell:

```powershell
$dest = "$env:USERPROFILE\.codex\skills"
New-Item -ItemType Directory -Force -Path $dest | Out-Null
Copy-Item -Path "pubmed-live" -Destination $dest -Recurse
Copy-Item -Path "literature-analysis" -Destination $dest -Recurse
```

macOS / Linux:

```bash
mkdir -p ~/.codex/skills
cp -r pubmed-live literature-analysis ~/.codex/skills/
```

或用 Codex skill-installer 一行安装 / or one-liner via skill-installer:

```bash
python ~/.codex/skills/.system/skill-installer/scripts/install-skill-from-github.py \
  --repo yjhd91/academic-literature-skills --path pubmed-live --path literature-analysis
```

### 方式二:Claude Code

Windows PowerShell:

```powershell
$dest = "$env:USERPROFILE\.claude\skills"
New-Item -ItemType Directory -Force -Path $dest | Out-Null
Copy-Item -Path "pubmed-live" -Destination $dest -Recurse
Copy-Item -Path "literature-analysis" -Destination $dest -Recurse
```

macOS / Linux:

```bash
mkdir -p ~/.claude/skills
cp -r pubmed-live literature-analysis ~/.claude/skills/
```

### 方式三:手动安装 / Manual

```bash
git clone https://github.com/yjhd91/academic-literature-skills
cd academic-literature-skills
cp -r pubmed-live literature-analysis ~/.codex/skills/   # Codex
# 或 / or
cp -r pubmed-live literature-analysis ~/.claude/skills/   # Claude Code
```

### 验证安装 / Verify

新开对话,说:"查一下 PubMed 上关于 radiomics lung cancer 的文献" / In a new conversation ask for a PubMed search, or run:

```bash
python scripts/pubmed.py search "radiomics" --max 3
python scripts/literature.py strategy --concepts "radiomics|lung cancer" --test
```

---

## 依赖 / Dependencies

- Python 3(仅标准库;xlsx 输出可选 openpyxl)/ stdlib only; openpyxl optional for xlsx
- 网络访问 / Network access to: `eutils.ncbi.nlm.nih.gov`、`api.openalex.org`、`api.crossref.org`、`export.arxiv.org`、`www.ebi.ac.uk`、`doaj.org`、`api.archives-ouvertes.fr`、`api.semanticscholar.org`
- 可选 / Optional:NCBI API Key(`PUBMED_API_KEY`)10 req/s;Semantic Scholar API Key 避免限流

## 设计原则 / Design Principles

- **证据锚定 / Evidence-anchored**:每个提取字段来自摘要原文,找不到标 "Not stated",不编造 / every cell grounded in abstract text; missing info marked "Not stated"
- **诚实覆盖 / Honest coverage**:无公开 API 的平台明确标注浏览器辅助 / platforms without APIs are explicitly browser-assisted
- **合法获取 / Legal access**:只下载开放获取 PDF,不绕过付费墙 / legal OA PDFs only
- **失败处理 / Failure handling**:429/超时退避重试 / backoff retry on 429/timeout

## License

MIT
