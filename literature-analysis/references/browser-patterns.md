# Browser-Assisted Search Patterns

Unified command: `browser-search --engine <engine> --query "<topic>" --max 20 --out results.json`

Drives a real Chrome (via DevTools Protocol) to search platforms that have no public API, then converts results into the standard record JSON so they flow into `extract` / `overview`.

## Engine matrix

| Engine | Search URL template | Extractors (CSS) | Login | Notes |
|--------|--------------------|------------------|-------|-------|
| `bing` | `https://www.bing.com/search?q=<q>` | `li.b_algo h2 a`, `.b_caption p` | no | Generic fallback; no login needed |
| `duckduckgo` | `https://html.duckduckgo.com/html/?q=<q>` | `div.result a.result__a`, `a.result__snippet` | no | HTML endpoint; still may CAPTCHA headless |
| `google-scholar` | `https://scholar.google.com/scholar?hl=en&q=<q>` | `.gs_r .gs_ri h3 a`, `.gs_a`, `.gs_rs` | no | Anti-bot may show CAPTCHA; retry or switch to in-app browser |
| `cnki` | `https://kns.cnki.net/kns8s/defaultresult/index?kw=<q>` | `.result-table-list tbody tr`, `.list-item` | yes (institutional) | Login once in the CDP Chrome; keep session |
| `wanfang` | `https://s.wanfangdata.com.cn/paper?q=<q>` | `.title`, `.result-item` | yes | May require captcha/login |
| `vip` | `https://qikan.cqvip.com/Qikan/Search/Index?key=<q>` | `.result-list li` | yes | 维普/中华医学期刊 |
| `pubmed-web` | `https://pubmed.ncbi.nlm.nih.gov/?term=<q>` | `.docsum-content a.docsum-title`, `.full-journal-citation`, `.docsum-snippet` | no | Real biomedical website; works headless (verified) |

Selectors change when sites update. If extraction returns 0 results but the page opened, inspect the page manually (in-app browser or Chrome) and update the selectors in `scripts/browser_search.mjs`.

Verified end-to-end (CNKI, 2026-08): after the user completes the slider verification once in a visible CDP Chrome window, `browser-search --engine cnki` returns real records (title/authors/journal/date/abstract URL). The CNKI engine auto-triggers the SPA search (sets the input and dispatches Enter), waits until the results counter (`共找到 N 条结果`) appears, parses the result table columns (序号/题名/作者/来源/发表时间/...), and **auto-paginates** through all pages (clicks `下一页` until collected >= `--max` or the last page). Verified: platform total 53, extracted 53 unique records (3 pages, no duplicates). Expect one manual verification (slider) per browser session.

## Query translation by target language

`browser-search` auto-translates the query into the engine's language before searching (via the free Google Translate endpoint; `--no-translate` disables it). `translate-query --text "..." --to ja` does standalone translation.

| Engine | Target language | Example |
|--------|----------------|---------|
| `cnki`, `wanfang`, `vip` | zh-CN | `radiomics lung cancer prognosis` -> `放射组学肺癌预后` |
| (future) `ciinii` | ja | `radiomics` -> `ラジオミクス` |
| (future) HAL / French | fr | ... |

Verified translations (medical term): zh-CN `放射组学肺癌预后`, ja `ラジオミクスによる肺がんの予後`, de `Radiomics-Lungenkrebsprognose`, fr `pronostic du cancer du poumon radiomique`, ru `радиомиктический прогноз рака легких`.

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
- Login required (CNKI/Wanfang/VIP) - log in once in the CDP Chrome; the session persists for the run.
- Never bypass paywalls or scrape at high volume: browser-assisted search is for verification and moderate volumes; large harvesting risks account bans.
