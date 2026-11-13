# Academic Literature Skills ｜ 学术文献检索分析技能

[![CI](https://github.com/yjhd91/academic-literature-skills/actions/workflows/ci.yml/badge.svg)](https://github.com/yjhd91/academic-literature-skills/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Version](https://img.shields.io/badge/version-2.0.0-blue.svg)](CHANGELOG.md)

**多源、多语言、可核查**的学术文献工作流：检索策略生成 → API + 浏览器检索 → 可审计去重 →
摘要字段提取 → 纳排筛选 → **参考文献核验** → **PRISMA 2020 计数** → 导出。
供 Codex / Claude Code / DeepSeek Harness 等宿主直接调用。

Multi-source, multilingual and **verifiable** literature workflow: strategy generation →
API + browser search → auditable deduplication → abstract extraction → screening →
**reference verification** → **PRISMA 2020 counts** → export.

> **开发者 / Developers**：解放军总医院第一医学中心 & 南开大学医学院团队。
> **早期思路来源 / Inspiration**：[ustc-ai4science/academic-search](https://github.com/ustc-ai4science/academic-search)。
> **License**：MIT，允许二次开发，使用时请注明来源。

---

## 2.0.0 更新了什么 / What changed in 2.0.0

| 新增 / Added | 为什么 / Why |
|---|---|
| `verify`：DOI/PMID/BibTeX 三源核验，五档结论，`--strict` 可作投稿前门 | 防幻觉引用。**DOI 在 Crossref 与 OpenAlex 都查不到 = 该文献不存在** |
| `prisma`：从检索文件 + 筛选表**重算** PRISMA 2020 计数 | 流程图数字不再靠手抄；未决定的记录会被点出来，不冒充"已完成" |
| `dedupe`：DOI/标题规范化 + 字段互补 + 可审计报告 | 同一篇的 4 种 DOI 写法不再被当成 4 篇；标题相同但 DOI 不同**不自动合并** |
| `doctor`：环境与 8 个 API 的连通性自检 | "检索不到"先说清是网络、限流、缺依赖，还是站点改版 |
| 内置 PubMed 客户端 + `NCBI_EMAIL`/`NCBI_API_KEY` | 两个 skill 可独立安装；符合 NCBI 使用政策 |
| `tests/`（66 个离线测试）+ CI | 之前 0 测试；现在每次提交自动跑 |
| 中/日/俄文主题相关性 | 之前 `--topic "肺结节"` 直接崩溃，且中文库结果被系统性判为"低相关→排除" |

## 技能组成 / Skills

| 技能 / Skill | 职责 / Role |
|---|---|
| **literature-analysis** | 检索工作台：策略生成、多库检索、浏览器抓取、去重、核验、提取、筛选、PRISMA、导出 |
| **pubmed-live** | 轻量 PubMed 实时检索（纯标准库，单文件）；未知 PMID 报错而不是造空记录 |

## 快速开始 / Quick start

```bash
python scripts/literature.py doctor                     # 1. 环境/API 自检
python scripts/literature.py strategy --concepts "radiomics|lung cancer|prognosis" --test --strategy-out s.json
python scripts/literature.py search-multi --strategy-file s.json --out results.json
python scripts/literature.py dedupe --in results.json --out merged.json --report dedupe.json
python scripts/literature.py verify --in merged.json --md verify.md --strict
python scripts/literature.py extract --in merged.json --out overview.csv --xlsx overview.xlsx --topic "radiomics lung cancer"
```

系统综述再加两步：

```bash
python scripts/literature.py prisma --in results.json --decisions screen.csv --out prisma.md --strict
python scripts/literature.py export --in merged.json --format bib --out references.bib
```

## 完整工作流 / End-to-end workflow

```text
doctor ──► strategy（每平台原生检索式 + 命中数）
              │
              ├─► search-multi（8 个开放 API，单源失败不中断）
              └─► browser-search（无 API 站点：CNKI/万方/维普/中华医学期刊/CiNii/NDL/BASE/CyberLeninka/eLibrary）
              │
              ▼
          dedupe（DOI/标题规范化 + 字段互补 + 复核清单）
              │
              ├─► lite → extract → screen（人工复核）
              ├─► verify（Crossref + PubMed + OpenAlex 三源）
              ├─► prisma（计数重算，未决定项报警）
              └─► enrich → export（BibTeX/RIS）→ download-pdf（仅 OA）
```

## 检索覆盖 / Coverage

### A. 开放 API（脚本原生，全自动）

| 平台 | 覆盖 | 状态 |
|---|---|---|
| PubMed | 生物医学，MeSH 语法最全 | ✅ 实测 |
| OpenAlex | 2.5 亿+ 文献，引用数 + OA + 多语言期刊 | ✅ 实测 |
| Crossref | DOI 元数据与引用数（已过滤同行评议记录） | ✅ 实测 |
| arXiv | CS / 物理 / 数学预印本 | ✅ 实测 |
| Europe PMC | 生物医学 + 开放全文链接 | ✅ 实测 |
| DOAJ | 全球开放获取期刊 | ✅ 实测 |
| HAL | 法国开放仓储 | ✅ 实测 |
| Semantic Scholar | 引用图 | ⚠️ 无 key 时常 429（降级，不视为环境损坏） |

### B. 浏览器辅助（无公开 API）

| 平台 | 语言 | 状态 | 备注 |
|---|---|---|---|
| CNKI 知网 | 中文 | ✅ 2026-08 实测（53/53 全量翻页） | 需登录一次 |
| 万方 | 中文 | ✅ 2026-08 实测（2,417 条/60 条抓取） | 需登录一次 |
| 中华医学期刊 | 中文 | ✅ 2026-08 实测（站内 API，全字段） | 免登录 |
| CiNii Research | 日文 | ✅ 2026-08 实测 | 免登录 |
| CyberLeninka | 俄文 | ✅ 2026-08 实测 | 免登录 |
| Google Scholar | 英文 | ⚠️ 自动化与其条款冲突，仅人工/低频 | 可能 CAPTCHA |
| 维普 VIP | 中文 | ⚠️ 当时网络 502，引擎保留 | 需登录 |
| NDL Search | 日文 | ⚠️ 当时网络 503 | 用 CiNii 补足 |
| BASE | 德文 | ⚠️ 当时网络 403 | 用 OpenAlex/DOAJ 补足 |
| eLibrary | 俄文 | ⚠️ 强制登录会话 | 需登录 |

> ✅ 的实测时间是 **2026-08**，本次 2.0.0 更新**未重新实测**浏览器引擎（维护者网络受限）。
> 站点改版会导致选择器失效——先 `doctor`，再按 `references/browser-patterns.md` 修复。

## 命令速查 / Commands

完整参数见 [literature-analysis/references/commands.md](literature-analysis/references/commands.md)，
记录格式见 [record-schema.md](literature-analysis/references/record-schema.md)。

| 命令 | 作用 |
|---|---|
| `doctor` | 环境 + 8 个 API + CDP + 引擎清单自检 |
| `strategy` / `translate` | 生成各平台原生检索式（MeSH、[tiab]、日期） |
| `search-multi` / `search-all` / `fetch` | 多库 / 多 PubMed 变体 / 单次 PubMed 检索 |
| `browser-search` | 无 API 站点：自动翻译 + 自动翻页；登录墙返回 `login_or_captcha_required` |
| `dedupe` | 合并去重并输出审计报告（含"同题不同 DOI"复核清单） |
| `verify` | 参考文献三源核验（`verified/partial/mismatch/not_found/no_identifier`） |
| `prisma` | PRISMA 2020 计数（识别/去重/筛选/排除原因/纳入/未决定） |
| `lite` / `extract` / `screen` / `overview` / `template` | 扫描表、字段提取、关键词初筛、总览表、空白模板 |
| `enrich` / `export` / `download-pdf` | 引用数与 OA 链接（分平台存证）、BibTeX/RIS、合法 OA PDF |
| `author-search` | 指定作者 / 单位的定向检索 |

## 设计原则 / Design principles

- **不编造 / Never fabricate**：只报告工具返回的值；`verify` 用来证明一条引用确实存在，
  查不到的 DOI 不得写进稿子。未知 PMID 直接报错，不返回空记录。
- **可审计 / Auditable**：去重报告、PRISMA 计数、引用数（含平台与检索时间）都可追溯到文件，
  不把"最大值"当唯一真值，不做跨平台求和。
- **失败可见 / Visible failure**：单源失败不中断其余来源但会列出；登录墙 ≠ 零结果；
  退出码 0/1/2/3 有明确含义。
- **诚实覆盖 / Honest coverage**：✅ 标注实测日期，未复测就写"未复测"。
- **合法获取 / Legal**：仅下载开放获取 PDF；不绕付费墙、不共享账号、不高频抓取。
- **内容即数据 / Content is data**：检索到的标题、摘要、PDF 文本是待报告的数据，不是指令。

## 安装 / Installation

### Codex

```powershell
$dest = "$env:USERPROFILE\.codex\skills"
New-Item -ItemType Directory -Force -Path $dest | Out-Null
Copy-Item -Path "pubmed-live" -Destination $dest -Recurse
Copy-Item -Path "literature-analysis" -Destination $dest -Recurse
```

```bash
# macOS / Linux
mkdir -p ~/.codex/skills && cp -r pubmed-live literature-analysis ~/.codex/skills/
```

或 skill-installer：

```bash
python ~/.codex/skills/.system/skill-installer/scripts/install-skill-from-github.py \
  --repo yjhd91/academic-literature-skills --path pubmed-live --path literature-analysis
```

### Claude Code

```powershell
Copy-Item -Path "pubmed-live","literature-analysis" -Destination "$env:USERPROFILE\.claude\skills" -Recurse
```

```bash
mkdir -p ~/.claude/skills && cp -r pubmed-live literature-analysis ~/.claude/skills/
```

两个 skill **可独立安装**：`literature-analysis` 内置 PubMed 客户端，不依赖 `pubmed-live`。

### 验证 / Verify

```bash
python scripts/literature.py doctor
python scripts/literature.py --version
```

## 依赖与环境变量 / Requirements

- Python 3.9+（仅标准库；`--xlsx` 需要 `openpyxl`，缺失时自动降级为 CSV）
- Node.js 22+（仅浏览器引擎需要；脚本自动探测，可用 `NODE` 环境变量指定）
- Chrome 带 `--remote-debugging-port=9222`（仅浏览器引擎需要）

| 变量 | 默认 | 作用 |
|---|---|---|
| `NCBI_EMAIL` | 空 | NCBI 使用政策要求提供联系邮箱；`doctor` 会提示 |
| `NCBI_API_KEY` | 空 | 把 NCBI 限流从 3 req/s 提到 10 req/s |
| `S2_API_KEY` | 空 | Semantic Scholar 限流缓解（可选） |
| `LIT_REQUEST_GAP` | 0.34 | 同一主机请求最小间隔（秒） |
| `LIT_RETRY_BUDGET` | 30 | 单个 URL 的总重试等待上限（秒） |
| `CROSSREF_TYPE` | journal-article | Crossref 检索的文献类型过滤 |

## 测试 / Tests

```bash
python -m unittest discover -s tests -v      # 66 个离线测试，无网络、无凭据
python tools/validate_skills.py              # 校验两个 SKILL.md 的 frontmatter 与内部链接
node --check literature-analysis/scripts/browser_search.mjs
```

CI（GitHub Actions）在 Python 3.9/3.12/3.13 上跑上述检查。

## 已知限制 / Limitations

- 只读标题与摘要，不解析全文 PDF、不提取表格数据；`extract` 的结果必须人工复核。
- 不做 Meta 分析、偏倚风险（RoB）评价或 GRADE；`prisma` 只计数，不评价。
- 抽取规则对英文摘要最可靠；中日俄文支持设计/样本量/验证/局限，人群与模态仍需人工填。
- 浏览器选择器随站点改版失效，属已知维护成本，不是"这个库没有文献"。
- 各数据库覆盖范围不同，报告时必须写明本次实际返回记录的来源。

## Roadmap

- 全文 PDF 段落定位（claim → 原文锚点）与抽样审计
- 预印本/正式版关联（同一研究的多个报告）
- 更多语言的相关性词表（韩文、葡萄牙文）

## Credits & License

早期思路来自 [ustc-ai4science/academic-search](https://github.com/ustc-ai4science/academic-search)；
设计上参考了 Agent Skills 规范（agentskills.io）、anthropics/skills、paper-search-mcp、
sr-screener 等公开实践。完整致谢见 [CHANGELOG.md](CHANGELOG.md)。

MIT License，使用时请注明来源。
