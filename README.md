# Academic Literature Skills ｜ 学术文献检索分析技能

**多源、多语言、多数据库学术文献检索 → 自动策略生成 → API 自动化检索 → 浏览器翻页抓取 → 精确提取 → 筛选 → 汇总交付**
的完整闭环，供 Codex / Claude Code 直接调用。

Multi-source, multilingual, multi-database academic literature search and analysis skills for Codex / Claude Code:
**auto search-strategy generation → API search → browser-assisted paginated scraping → precise abstract extraction → screening → summarized delivery**.

> **开发者 / Developers**：解放军总医院第一医学中心 & 南开大学医学院团队（PLA General Hospital First Medical Center & Nankai University School of Medicine）。采用AI辅助编写和完成本项目。
> **早期思路来源 / Early inspiration**：[ustc-ai4science/academic-search](https://github.com/ustc-ai4science/academic-search)。
> **开源声明 / License & Attribution**：本项目完全开源，允许任何形式的二次开发和使用；使用时请注明来源。
> Fully open source. Any form of secondary development and use is permitted; please credit the source when you use it.

---

## 技能组成 / Skills

| 技能 / Skill | 职责 / Role |
|------|------|
| **pubmed-live** | 实时 PubMed 检索与摘要抓取（NCBI E-utilities，纯标准库）/ Real-time PubMed search & abstract retrieval |
| **literature-analysis** | 多数据库检索工作台：策略生成、跨库转换、API 检索、浏览器抓取、精确提取、筛选、导出 / Multi-source workbench: strategy generation, cross-database query conversion, API search, browser scraping, extraction, screening, export |

---

## 完整工作流 / End-to-End Workflow

当用户提出“检索某个主题”后，系统按以下流程自动执行：

```text
用户提出主题
   │
   ▼
① 标准化检索策略生成（多语言 × 多数据库）
   ├─ 概念拆解：疾病/人群、干预/暴露、结局、模态
   ├─ 平台原生检索式：PubMed MeSH/[tiab]/[dp]、arXiv、Europe PMC、OpenAlex、Crossref、DOAJ、HAL、S2 自动转换
   ├─ 检索词多语言翻译：中文（知网/万方/维普/中华医学期刊）、日文（CiNii/NDL）、俄文（eLibrary/CyberLeninka）、德文（BASE）、法文（HAL）
   └─ 每个变体先测命中数，零命中/语法错误自动标红
   │
   ▼
② API 数据库自动化检索
   ├─ PubMed / OpenAlex / Crossref / arXiv / Semantic Scholar / Europe PMC / DOAJ / HAL
   ├─ 多平台并行，按 PMID/DOI/标题合并去重
   └─ 记录引用数、OA 状态、OA PDF 链接
   │
   ▼
③ 无 API 数据库：浏览器自动搜索（默认浏览器 / 内置浏览器 / CDP Chrome）
   ├─ 自动翻译检索词，进入 Google Scholar、知网 CNKI、万方、维普、中华医学期刊、
   │   CiNii/NDL（日本）、BASE（德国）、CyberLeninka / eLibrary（俄罗斯）
   ├─ 自动翻页循环，突破网页单页显示限制，取回完整文献信息（标题/作者/期刊/年卷期/页码/摘要/DOI/链接）
   ├─ 登录类站点（CNKI/万方/维普/eLibrary）：浏览器窗口登录一次，会话保持后全自动
   └─ 网络受限站点（NDL 503、维普 502、BASE 403）如实标注，用 CiNii/OpenAlex/DOAJ/CyberLeninka 补足
   │
   ▼
④ 汇总交付
   ├─ 全部来源合并 → 一键自动提取（16 列证据锚定字段）
   ├─ 按纳入/排除标准精确筛选（include / exclude / uncertain + 理由 + 原文证据）
   ├─ 输出：xlsx（格式化 Excel）+ 对话框 Markdown 表格 + CSV（UTF-8 BOM）+ BibTeX/RIS
   └─ 可选：OpenAlex 补全引用数/OA → 批量下载合法 OA PDF（%PDF 校验 + manifest 审计）
```

**关键点 / Key points**：

- 不同平台的检索式不同，系统自动为每个平台生成原生语法，用户无需手写。
- 有 API 的平台全自动；没有 API 的平台用真实浏览器自动搜索、自动翻页、完整抓取，不伪造结果。
- 检索覆盖一直更新到当前日期（含 2026 年 8 月最新文献）。
- 全流程产出同一套标准 JSON 记录，任意来源都可继续进入提取/筛选/导出流水线。

---

## 检索覆盖范围 / Search Coverage

### A. 开放 API 平台（脚本原生支持，全自动）/ Open-API sources (script-native, fully automated)

| 平台 / Source | 覆盖 / Scope | 特点 / Notes |
|------|------|------|
| PubMed | 生物医学 / biomedical | 实时、语法最丰富、摘要全 / live, richest syntax, full abstracts |
| OpenAlex | 跨学科 / interdisciplinary | 2.5 亿+ 文献，引用数 + OA + 多语言期刊 / 250M+ works, citations, OA, multilingual journals |
| Crossref | DOI 元数据 | 引用数（is-referenced-by-count） |
| arXiv | CS / 物理 / 数学预印本 | 开放 PDF 直链 |
| Semantic Scholar | 引用图 / citation graph | 无密钥时限流（优雅降级）/ rate-limited without key |
| Europe PMC | 生物医学 + 全文 | 摘要全，开放全文链接 |
| DOAJ | 全球开放获取期刊 | 多语言 / multilingual |
| HAL | 法国开放仓储 / French OA | 法文文献，OA PDF |

### B. 浏览器辅助平台（无公开 API，自动搜索 + 翻页 + 抓取）/ Browser-assisted platforms (no public API)

这些平台没有可公开调用的批量 API，或反爬/登录墙严格。系统用 Chrome（CDP）自动翻译检索词、进入站点、
循环翻页、突破单页显示限制，取回完整文献信息，并汇总进同一套 JSON/xlsx 流水线：

| 平台 / Platform | 国家/语言 | 实测状态（2026-08）/ Verified (2026-08) | 登录 |
|------|------|------|------|
| Google Scholar | 国际 / EN | 引擎就绪；反爬可能弹 CAPTCHA，可见窗口过一次即可 | 否 |
| CNKI 知网 | 中国 / 中文 | **53/53 全量翻页抓取**，自动触发检索 + 自动点下一页 | 需登录一次 |
| 万方 Wanfang | 中国 / 中文 | **2,417 条全量翻页**，60/60 抓取，标题/作者/期刊/摘要/ID 全字段 | 需登录一次 |
| 维普 VIP | 中国 / 中文 | 引擎就绪；当前网络 502/连接断开，恢复后直接可用 | 需登录一次 |
| 中华医学期刊 medjournals.cn | 中国 / 中文 | **调用站点官方检索 API（pageSize=50 循环）**，返回标题/DOI/作者/期刊/卷期/页码/摘要 | 否 |
| CiNii / NDL | 日本 / 日文 | CiNii **实测 10 篇真实日文文献**；NDL 当前网络 503，恢复后可用 | 否 |
| BASE | 德国 / 多语 | 当前网络 403；德文覆盖用 OpenAlex/DOAJ 补足 | 否 |
| CyberLeninka | 俄罗斯 / 俄文 | **实测 10 篇真实俄文文献** | 否 |
| eLibrary | 俄罗斯 / 俄文 | 强制登录会话（未登录跳转 start_session.asp）；CDP 窗口登录后可用 | 必须 |

所有浏览器结果自动写入标准 JSON，可直接进入 `extract` / `overview` / 筛选 / 导出流水线。
All browser results flow into the same standard JSON pipeline.

---

## 能力清单 / Capabilities

### 检索策略工程 / Search-strategy engineering

- 自动查 MeSH，生成 MeSH / [tiab] / 混合三套 PubMed 检索式并测试命中数
- 8 个 API 平台的原生检索式自动转换（字段语法、日期参数各平台不同）
- 检索词多语言翻译：zh-CN / ja / de / fr / ru
- 定向检索：指定作者 `[au]` + 单位 `[ad]`（`author-search`）

### 检索与合并 / Search & merge

- `search-all`：多查询按 PMID 去重
- `search-multi`：8 个 API 平台同时检索，按 DOI/标题去重
- `browser-search`：12+ 个浏览器引擎，自动翻译 + 自动翻页 + 去重 + xlsx 输出
- OpenAlex 补全：引用数、OA 状态、OA PDF 链接

### 提取与筛选 / Extraction & screening

- 一键自动提取 16 列证据锚定字段（study design / population / sample size / modality / method / validation /
  performance / findings / limitations / evidence level / topic relevance / decision / reason / evidence / citations / OA）
- 找不到的信息标 “Not stated / 未提及”，绝不编造；每个字段附原文 evidence 短语
- 按 `--include / --exclude` 判定 include / exclude / uncertain，理由可追溯
- 证据等级量表（指南 / 系统综述 / RCT / 前瞻+外部验证 / 回顾+外部验证 / 回顾+内部验证 / 观察性 / 综述）

### 交付 / Delivery

- xlsx（加粗表头、冻结首行、自动筛选）+ 对话框 Markdown 表格 + CSV（UTF-8 BOM）
- BibTeX / RIS 参考文献导出
- 批量下载合法 OA PDF（%PDF 校验 + `download_manifest.csv` 审计）

---

## 输出示例 / Output Sample

### xlsx 总览表字段（16 提取列 + 来源列）/ Overview table fields

`source`、`pmid`、`title`、`journal`、`pubDate`、`doi`、`abstract` + **study design、population、sample size、
imaging modality / data、method / model、validation、performance metrics、main findings、limitations、
evidence level、citation count、open access status、topic relevance、decision、reason、evidence**

### 对话框 Markdown 表格

每次检索都会在对话框内直接给出一张美观、可读的汇总表（来源、标题、期刊、年份、摘要片段、DOI/链接、
相关性、决策），用户无需打开文件即可初筛。

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
# ① 多平台策略生成 + 命中数测试 / strategy generation for all platforms
python scripts/literature.py strategy --concepts "radiomics|lung cancer|prognosis" --sources pubmed,openalex,crossref,arxiv,semanticscholar,europepmc,doaj,hal --dates "2023/01/01:2026/08/05" --test --strategy-out strategy.json

# 跨库检索词转换 / cross-database query conversion
python scripts/literature.py translate --concepts "radiomics|lung cancer|prognosis" --sources pubmed,arxiv,europepmc --dates "2023/01/01:2026/08/05" --test

# ② API 多平台检索 / multi-source API search
python scripts/literature.py search-multi --query "radiomics lung cancer prognosis" --sources pubmed,openalex,crossref,arxiv,semanticscholar,europepmc,doaj,hal --max 10 --from 2023/01/01 --to 2026/08/05 --sort citations --out results.json

# ③ 浏览器抓取无 API 平台（自动翻译 + 自动翻页）/ browser-assisted search
python scripts/literature.py browser-search --engine cnki --query "radiomics lung cancer prognosis" --max 50 --out cnki.json --xlsx cnki.xlsx
python scripts/literature.py browser-search --engine wanfang --query "radiomics lung cancer prognosis" --max 60 --out wf.json --xlsx wf.xlsx
python scripts/literature.py browser-search --engine medjournals --query "radiomics lung cancer prognosis" --max 60 --out med.json --xlsx med.xlsx
python scripts/literature.py browser-search --engine google-scholar --query "radiomics lung cancer prognosis" --max 20 --out gs.json
python scripts/literature.py browser-search --engine ciinii --query "radiomics lung cancer" --max 20 --out ciinii.json --xlsx ciinii.xlsx
python scripts/literature.py browser-search --engine cyberleninka --query "radiomics lung cancer" --max 20 --out cyber.json --xlsx cyber.xlsx
python scripts/literature.py browser-search --engine elibrary --query "radiomics lung cancer" --max 20 --out el.json

# ④ 一键自动提取 + 筛选 / one-shot extraction + screening
python scripts/literature.py extract --in results.json --out overview.csv --xlsx overview.xlsx --topic "radiomics lung cancer prognosis" --include "external validation|prospective" --exclude "review|animal|editorial"

# OpenAlex 补全 / enrich
python scripts/literature.py enrich --in results.json --out enriched.json

# 导出 / export
python scripts/literature.py export --in enriched.json --out references.bib
python scripts/literature.py export --in enriched.json --format ris --out references.ris

# 批量下载 OA PDF / batch download
python scripts/literature.py download-pdf --in results.json --dir pdfs --timeout 40

# 定向检索作者/单位 / author + affiliation search
python scripts/literature.py author-search --author "Aerts HJWL" --affiliation "Harvard Medical School" --dates "2020/01/01:2026/08/05" --max 20 --out author_results.json
```

浏览器引擎列表：`bing`、`duckduckgo`、`google-scholar`、`pubmed-web`、`cnki`、`wanfang`、`vip`、
`medjournals`、`ciinii`、`ndl`、`base`、`cyberleninka`、`elibrary`。

---

## 安装方式 / Installation

### 方式一：Codex（推荐）/ Method 1: Codex (recommended)

Windows PowerShell：

```powershell
$dest = "$env:USERPROFILE\.codex\skills"
New-Item -ItemType Directory -Force -Path $dest | Out-Null
Copy-Item -Path "pubmed-live" -Destination $dest -Recurse
Copy-Item -Path "literature-analysis" -Destination $dest -Recurse
```

macOS / Linux：

```bash
mkdir -p ~/.codex/skills
cp -r pubmed-live literature-analysis ~/.codex/skills/
```

或使用 Codex skill-installer 一键安装 / or install via skill-installer：

```bash
python ~/.codex/skills/.system/skill-installer/scripts/install-skill-from-github.py \
  --repo yjhd91/academic-literature-skills --path pubmed-live --path literature-analysis
```

### 方式二：Claude Code

Windows PowerShell：

```powershell
$dest = "$env:USERPROFILE\.claude\skills"
New-Item -ItemType Directory -Force -Path $dest | Out-Null
Copy-Item -Path "pubmed-live" -Destination $dest -Recurse
Copy-Item -Path "literature-analysis" -Destination $dest -Recurse
```

macOS / Linux：

```bash
mkdir -p ~/.claude/skills
cp -r pubmed-live literature-analysis ~/.claude/skills/
```

### 方式三：手动安装 / Method 3: Manual

```bash
git clone https://github.com/yjhd91/academic-literature-skills
cd academic-literature-skills
cp -r pubmed-live literature-analysis ~/.codex/skills/    # Codex
# 或 / or
cp -r pubmed-live literature-analysis ~/.claude/skills/   # Claude Code
```

### 浏览器引擎额外要求 / Browser-engine extra requirements

浏览器检索需要 Node.js 22+（内置 WebSocket）与一个带远程调试端口的 Chrome：

```powershell
& "C:\Program Files\Google\Chrome\Application\chrome.exe" --remote-debugging-port=9222 --user-data-dir="D:\chrome-cdp"
```

登录类站点（CNKI/万方/维普/eLibrary）在该 Chrome 窗口登录一次即可；CAPTCHA 同理。

### 验证安装 / Verify

新开对话说：“查一下 radiomics lung cancer 的文献，生成多数据库检索策略，汇总成表格”，或运行：

```bash
python scripts/pubmed.py search "radiomics" --max 3
python scripts/literature.py strategy --concepts "radiomics|lung cancer" --test
```

---

## 依赖 / Dependencies

- Python 3（仅标准库；xlsx 输出可选 openpyxl）/ stdlib only; openpyxl optional for xlsx
- Node.js 22+（浏览器引擎）/ Node.js 22+ (browser engines)
- 网络访问：`eutils.ncbi.nlm.nih.gov`、`api.openalex.org`、`api.crossref.org`、`export.arxiv.org`、
  `www.ebi.ac.uk`、`doaj.org`、`api.archives-ouvertes.fr`、`api.semanticscholar.org`，
  以及浏览器引擎所需的各站点（部分站点需要登录/机构网络）
- 可选 / Optional：NCBI API Key（`PUBMED_API_KEY`，10 req/s）；Semantic Scholar API Key 避免限流

## 设计原则 / Design Principles

- **证据锚定 / Evidence-anchored**：每个提取字段来自摘要原文，找不到标 “Not stated”，不编造
- **诚实覆盖 / Honest coverage**：无公开 API 的平台用真实浏览器自动抓取并如实报告；网络被墙/登录墙如实标注
- **合法获取 / Legal access**：只下载开放获取 PDF，不绕过付费墙；浏览器检索保持适度频率
- **失败处理 / Failure handling**：429/超时退避重试；单个平台失败不中断其余平台
- **完全开源 / Fully open source**：允许任何形式的二次开发和使用，使用时注明来源

## License

MIT（使用时请注明来源 / please credit the source when used）
