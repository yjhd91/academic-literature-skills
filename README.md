# Codex PubMed Literature Skills

一套面向**学术写作与文献调研**的 Codex/Claude Code 技能,提供"实时检索 → 多平台合并 → 一键自动提取 → 精确筛选 → 批量下载 → 参考文献导出"的完整闭环。

包含两个技能:

- **pubmed-live** - 实时 PubMed 检索与摘要抓取(NCBI E-utilities,纯 Python 标准库)
- **literature-analysis** - 主题到表格的全流程分析:检索式工程、多源检索、证据锚定提取、筛选、导出、PDF 批量下载

---

## 能力总览

### pubmed-live

| 能力 | 说明 |
|------|------|
| 实时检索 | 直连 NCBI E-utilities,数据实时更新(非缓存) |
| PubMed 原生语法 | 支持 `[tiab]`、`[Mesh]`、`[dp]`、`[pt]`、布尔运算符、短语引号 |
| 日期过滤 | `--from / --to` 按出版日期严格过滤(带二次校验) |
| 定向检索 | 作者 `[au]`、单位 `[ad]` 组合 |
| 摘要与全文信息 | 标题/作者/期刊/日期/DOI/PMCID/摘要 |
| 输出 | JSON 或紧凑文本,可存盘供后续分析 |

### literature-analysis

| 能力 | 说明 |
|------|------|
| 检索式工程 | 自动查 MeSH 主题词,生成 MeSH / `[tiab]` / 混合三套 PubMed 检索式,逐个测试命中数并做语法校验 |
| 多查询合并 | 多个检索变体按 PMID 去重合并 |
| 多平台检索 | 一次搜索同时覆盖 PubMed / OpenAlex / Crossref / arXiv / Semantic Scholar / Europe PMC / DOAJ / HAL,按 DOI 主键去重 |
| 两遍策略 | 第一遍轻量表(lite)先扫描,第二遍深提取(extract) |
| 一键自动提取 | 从摘要(结合标题)自动填充 10 个证据字段,找不到标 "Not stated",绝不编造 |
| 精确筛选 | 按纳入/排除标准自动判定 include / exclude / uncertain,理由可追溯 |
| 相关性打分 | 按主题词与标题/摘要的匹配度给 High / Medium / Low |
| 多源补全 | OpenAlex 引用数、开放获取状态、OA PDF 链接 |
| 批量下载 | 只下载合法 OA PDF,%PDF 校验 + manifest 审计 |
| 导出 | BibTeX / RIS / CSV / 格式化 Excel(xlsx) |
| 定向检索 | 指定作者 + 单位检索某人的全部文献 |

---

## 检索范围(可查询的平台)

### 开放 API 平台(脚本直接支持)

| 平台 | 覆盖方向 | 特点 |
|------|---------|------|
| PubMed | 生物医学 | 实时、语法最丰富、摘要全 |
| OpenAlex | 跨学科 | 2.5 亿+ 文献,引用数 + OA 状态 + 多语言期刊元数据 |
| Crossref | 跨学科 DOI 元数据 | 引用数(is-referenced-by-count) |
| arXiv | CS / 物理 / 数学预印本 | 开放 PDF 直链 |
| Semantic Scholar | 引用图 | 无密钥时限流(优雅降级) |
| Europe PMC | 生物医学 + 全文 | 摘要全,开放全文链接 |
| DOAJ | 全球开放获取期刊 | 多语言(实测含阿拉伯语期刊) |
| HAL | 法国开放仓储 | 法文文献,OA PDF |

### 浏览器辅助平台(无公开 API,不假装批量接入)

Google Scholar、CNKI(知网)、万方、维普/中华医学期刊、CiNii/NDL(日本)、eLibrary(俄罗斯)没有公开批量 API 或强反爬/登录墙。本技能对它们:

- 不做假结果:不声称"已接入",不伪造检索命中;
- 提供浏览器辅助路径:通过浏览器会话或机构访问(如知网配合 nature-downloader 技能)做定向核验;
- 用 OpenAlex / Crossref / DOAJ 兜底多语言覆盖(它们索引大量中、日、德、法、俄期刊,含原文标题和摘要)。

---

## 能提供的内容

### 总览表字段(16 列)

source(来源)、pmid、title、journal、pubDate、doi、abstract + **study design、population、sample size、imaging modality / data、method / model、validation、performance metrics、main findings、limitations、evidence level、citation count、open access status、topic relevance、decision、reason、evidence**

### 输出格式

- CSV(UTF-8 BOM,Excel 直接打开不乱码)
- 格式化 Excel(xlsx:加粗表头、冻结首行、自动筛选)
- 对话框 Markdown 表格
- BibTeX / RIS 参考文献
- 批量 PDF + `download_manifest.csv`(downloaded / skipped / failed / not_pdf)

---

## 命令速查

### pubmed-live

```powershell
python scripts/pubmed.py search "radiomics lung cancer prognosis" --max 10 --sort relevance
python scripts/pubmed.py search "artificial intelligence" --sort pub_date --max 30 --from 2024/01/01 --to 2026/08/05
python scripts/pubmed.py fetch 28418006 40181378
```

### literature-analysis

```powershell
# 1. 自动生成 PubMed 规范检索式(MeSH + [tiab] + 日期),并测试命中数
python scripts/literature.py strategy --concepts "radiomics|lung cancer|prognosis" --dates "2023/01/01:2026/08/05" --test --out queries.txt

# 2a. 多查询合并检索(PubMed)
python scripts/literature.py search-all --queries-file queries.txt --max 15 --out results.json

# 2b. 多平台检索(8 个源一次搜索,按 DOI 去重)
python scripts/literature.py search-multi --query "radiomics lung cancer prognosis" --sources pubmed,openalex,crossref,arxiv,semanticscholar,europepmc,doaj,hal --max 10 --from 2023/01/01 --to 2026/08/05 --sort citations --out results.json

# 3. 第一遍:轻量扫描表
python scripts/literature.py lite --in results.json

# 4. 一键自动提取 + 筛选(全字段填充)
python scripts/literature.py extract --in results.json --out overview.csv --xlsx overview.xlsx --topic "radiomics lung cancer prognosis" --include "external validation|prospective" --exclude "review|animal|editorial"

# 5. 关键词初筛(可选,语义复核仍由 Agent 完成)
python scripts/literature.py screen --in results.json --out triage.csv --include "external validation|prospective" --exclude "review|animal|editorial"

# 6. 多源补全(OpenAlex 引用数 + OA 状态)
python scripts/literature.py enrich --in results.json --out enriched.json

# 7. 导出参考文献
python scripts/literature.py export --in enriched.json --out references.bib
python scripts/literature.py export --in enriched.json --format ris --out references.ris

# 8. 批量下载开放获取 PDF
python scripts/literature.py download-pdf --in results.json --dir pdfs --timeout 40

# 9. 定向检索某作者/单位
python scripts/literature.py author-search --author "Aerts HJWL" --affiliation "Harvard Medical School" --dates "2020/01/01:2026/08/05" --max 20 --out author_results.json
```

### 完整流程示例

```text
用户: 我要写一篇肺部放射组学与预后的综述,帮我找 2023 年以来的文献并列出总览表
Agent: strategy 生成检索式 → search-all/search-multi 合并去重
       → lite 出轻量表 → extract 自动提取全字段 + 按标准筛选
       → QA 精修 → 交付 CSV + xlsx + 对话框表格 + 入选文献 PMID/DOI
```

---

## 安装方式

### 方式一:Codex(推荐)

把两个文件夹复制到 Codex 全局技能目录,新对话自动生效:

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

或用 Codex 的 skill-installer 直接安装:

```bash
python ~/.codex/skills/.system/skill-installer/scripts/install-skill-from-github.py \
  --repo yjhd91/pubmed-literature-skills --path pubmed-live --path literature-analysis
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

### 方式三:手动安装

```bash
git clone https://github.com/yjhd91/pubmed-literature-skills
cd pubmed-literature-skills
cp -r pubmed-live literature-analysis ~/.codex/skills/   # Codex
# 或
cp -r pubmed-live literature-analysis ~/.claude/skills/   # Claude Code
```

### 验证安装

新开一个对话,直接说:"查一下 PubMed 上关于 radiomics lung cancer 的文献",或手动运行:

```bash
python scripts/pubmed.py search "radiomics" --max 3
python scripts/literature.py strategy --concepts "radiomics|lung cancer" --test
```

---

## 依赖

- Python 3(仅标准库;xlsx 输出可选 openpyxl)
- 网络访问 `eutils.ncbi.nlm.nih.gov`、`api.openalex.org`、`api.crossref.org`、`export.arxiv.org`、`www.ebi.ac.uk`、`doaj.org`、`api.archives-ouvertes.fr`、`api.semanticscholar.org`
- 可选:NCBI API Key(`PUBMED_API_KEY`)提升速率到 10 次/秒;Semantic Scholar API Key 避免限流

## 设计原则

- **证据锚定**:每个提取字段都来自摘要原文,找不到标 "Not stated",不编造数字
- **诚实覆盖**:没有公开 API 的平台明确标注为浏览器辅助,不做假结果
- **合法获取**:只下载开放获取 PDF,不绕过付费墙
- **失败处理**:429/超时自动退避重试,单平台失败不影响整体

## License

MIT
