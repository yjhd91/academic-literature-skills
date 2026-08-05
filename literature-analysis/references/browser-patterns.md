# Browser-Assisted Search Patterns

Unified command: `browser-search --engine <engine> --query "<topic>" --max 20 --out results.json`

Drives a real Chrome (via DevTools Protocol) to search platforms that have no public API, then converts results into the standard record JSON so they flow into `extract` / `overview`.

## Engine matrix

| Engine | Search URL template | Extractors (CSS) | Login | Notes |
|--------|--------------------|------------------|-------|-------|
| `bing` | `https://www.bing.com/search?q=<q>` | `li.b_algo h2 a`, `.b_caption p` | no | Generic fallback; no login needed |
| `duckduckgo` | `https://html.duckduckgo.com/html/?q=<q>` | `div.result a.result__a`, `a.result__snippet` | no | HTML endpoint; still may CAPTCHA headless |
| `google-scholar` | `https://scholar.google.com/scholar?hl=en&q=<q>` | `.gs_r .gs_ri h3 a`, `.gs_a`, `.gs_rs` | no | Anti-bot may show CAPTCHA; retry or switch to in-app browser |
| `cnki` | `https://kns.cnki.net/kns8s/defaultresult/index?kw=<q>` | `.result-table-list tbody tr`, `.list-item` | yes (institutional) | Login once in the CDP Chrome; keep session; **verified: 53/53 full pagination** |
| `wanfang` | `https://s.wanfangdata.com.cn/paper?q=<q>` | `div.normal-list` (title/author/journal/abstract/id) | yes | **verified: 2,417 total, 60/60 across 3 pages**; URLs built from `title-id-hidden` |
| `vip` | `https://qikan.cqvip.com/Qikan/Search/Index?key=<q>` | `.result-list li`, `.list-item` | yes | 维普; **当前网络连接受阻(502/ERR_CONNECTION_CLOSED)** - 网络恢复后直接可用 |
| `medjournals` | `https://www.yiigle.com/Paper/Search?searchType=pt&q=<q>` | POST `/apiVue/search/searchList` (pageSize 50, auto-pagination) | no | 中华医学期刊全文数据库(medjournals.cn 跳转)。**verified: API 全字段(标题/DOI/作者/期刊/卷期/页码/摘要/关键词/阅读/下载/引用)** |
| `pubmed-web` | `https://pubmed.ncbi.nlm.nih.gov/?term=<q>` | `.docsum-content a.docsum-title`, `.full-journal-citation`, `.docsum-snippet` | no | Real biomedical website; works headless (verified) |
| `ciinii` | `https://cir.nii.ac.jp/all?q=<q>` | `a[href*="/crid/"]` + name/short-title filter | no | Japanese CiNii Research; verified (10 real papers, English keywords) |
| `ndl` | `https://ndlsearch.ndl.go.jp/search?cs=bib&q=<q>` | `a[href*="/books/"]` (client-rendered) | no | NDL サーチ(日本国立国会图书馆); **当前网络 503 - 网络允许时自动可用**,日本期刊覆盖优先用 CiNii |
| `base` | `https://www.base-search.net/Search/Results?lookfor=<q>` | `div.result` | no | German BASE; **403-blocked from this network** - rely on OpenAlex/DOAJ for German coverage |
| `cyberleninka` | `https://cyberleninka.ru/search?q=<q>` | `a[href*="/article/n/"]` | no | Russian OA library; verified (10 real Russian papers) |
| `elibrary` | `https://elibrary.ru/query_results.asp?query=<q>` | `tr a[href*="item.asp?id="]` | yes (session) | eLIBRARY.RU(俄罗斯); **强制登录会话**,未登录跳转 start_session.asp;在 CDP Chrome 登录后可用 |

Selectors change when sites update. If extraction returns 0 results but the page opened, inspect the page manually (in-app browser or Chrome) and update the selectors in `scripts/browser_search.mjs`.

Verified end-to-end (CNKI, 2026-08): after the user completes the slider verification once in a visible CDP Chrome window, `browser-search --engine cnki` returns real records (title/authors/journal/date/abstract URL). The CNKI engine auto-triggers the SPA search (sets the input and dispatches Enter), waits until the results counter (`共找到 N 条结果`) appears, parses the result table columns (序号/题名/作者/来源/发表时间/...), and **auto-paginates** through all pages (clicks `下一页` until collected >= `--max` or the last page). Verified: platform total 53, extracted 53 unique records (3 pages, no duplicates). Expect one manual verification (slider) per browser session.

Verified end-to-end (中华医学期刊, 2026-08): `browser-search --engine medjournals --query "radiomics lung cancer prognosis"` auto-translates to `放射组学肺癌预后`, calls the site's own search API from the page context (localStorage `_login-token` + cookies apply automatically), and paginates `pageSize=50`. Each record carries title/DOI/authors/journal/year/volume-issue/pages/article URL/docType/abstract. The platform total is returned honestly (`平台共 N 条`).

Verified end-to-end (万方, 2026-08): `browser-search --engine wanfang` parses `div.normal-list` blocks (title, authors, journal, year/issue, abstract, record id), builds canonical detail URLs (`d.wanfangdata.com.cn/periodical/<id>`), reports `找到 N 条文献`, and **auto-paginates** by clicking the `>` control (verified: platform total 2,417, extracted 60 unique records over 3 pages).

## Query translation by target language

`browser-search` auto-translates the query into the engine's language before searching (via the free Google Translate endpoint; `--no-translate` disables it). `translate-query --text "..." --to ja` does standalone translation.

| Engine | Target language | Example |
|--------|----------------|---------|
| `cnki`, `wanfang`, `vip` | zh-CN | `radiomics lung cancer prognosis` -> `放射组学肺癌预后` |
| `medjournals` | zh-CN | `radiomics lung cancer prognosis` -> `放射组学肺癌预后` |
| `ciinii`, `ndl` | ja | `radiomics` -> `ラジオミクス` |
| `cyberleninka`, `elibrary` | ru | `radiomics` -> `радиомика` |
| HAL / French (API 侧) | fr | ... |

Verified translations (medical term): zh-CN `放射组学肺癌预后`, ja `ラジオミクスによる肺がんの予後`, de `Radiomics-Lungenkrebsprognose`, fr `pronostic du cancer du poumon radiomique`, ru `радиомиктический прогноз рака легких`.

Multilingual live tests (2026-08): CiNii (Japanese) and CyberLeninka (Russian) both return real results via the visible CDP Chrome; BASE returns HTTP 403 from this network. Sentence-form auto-translations work best on free-text engines (CiNii/CyberLeninka); for field-syntax engines prefer keyword-style queries. CiNii mixes author profile links into results - the extractor filters them by strict all-capitalized name patterns and URL/title dedupe.

## Headless Chrome and anti-bot reality

Headless Chrome from this network is CAPTCHA-blocked by Bing, DuckDuckGo, Google Scholar, and Mojeek (`Please solve the following puzzle` / `Select all squares containing a duck`). PubMed's website works headless (verified: 5 real records extracted). For the blocked engines:

- Use a **visible** Chrome window (the module drives the same CDP Chrome; you complete the CAPTCHA once in the window, then re-run - the session persists).
- Or use the in-app browser fallback described below.
- Never hammer the sites; moderate volumes only.

## Chrome CDP setup (one-time)

Windows PowerShell:

```powershell
# fully quit Chrome first, then:
& "C:\Program Files\Google\Chrome\Application\chrome.exe" --remote-debugging-port=9222 --user-data-dir="D:\chrome-cdp"
```

macOS:

```bash
/Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome --remote-debugging-port=9222 --user-data-dir="$HOME/chrome-cdp"
```

Linux:

```bash
google-chrome --remote-debugging-port=9222 --user-data-dir="$HOME/chrome-cdp"
```

Then in that Chrome open `chrome://inspect/#remote-debugging` and confirm remote debugging is active. The script auto-detects port 9222 or the `DevToolsActivePort` file.

## Manual / in-app browser fallback

When CDP is unavailable or a site blocks automation:

1. Print the URL: `python scripts/literature.py browser-search --engine cnki --query "..." --print-url`
2. Open it in the in-app browser or Chrome; complete login/CAPTCHA if needed.
3. Collect records manually and save them as standard JSON (one object per record):

```json
{
  "id": "url or stable id",
  "source_platform": "cnki",
  "title": "标题",
  "url": "https://...",
  "snippet": "摘要或来源信息",
  "journal": "期刊",
  "pubDate": "2025",
  "authors": ["作者甲", "作者乙"],
  "doi": "",
  "abstract": "完整摘要(若可得)",
  "pmid": ""
}
```

4. Re-run `extract` / `overview` on that JSON; results merge with API-source records in `search-multi`.

## Troubleshooting

- `No Chrome CDP endpoint found` - Chrome is not running with `--remote-debugging-port`; run the setup command above.
- 0 results but page loaded - site changed its HTML; update selectors, or use the manual fallback.
- CAPTCHA / anti-bot page - complete it in the visible Chrome window, then re-run; or use the in-app browser fallback.
- Login required (CNKI/Wanfang/VIP/eLibrary) - log in once in the CDP Chrome; the session persists for the run. eLibrary has no anonymous search: the site redirects unauthenticated visitors to `start_session.asp`.
- NDL / VIP / BASE may be unreachable from some networks (503/502/403). The engines stay configured; when the network allows, re-run and they work. Coverage is then supplemented by CiNii / OpenAlex / DOAJ / CyberLeninka.
- Never bypass paywalls or scrape at high volume: browser-assisted search is for verification and moderate volumes; large harvesting risks account bans.
