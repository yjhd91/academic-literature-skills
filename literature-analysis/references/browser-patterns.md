# Browser-assisted search: engines, CDP setup, repair log

Command: `python scripts/literature.py browser-search --engine <id> --query "<topic>" --max 20 --out results.json`

Drives a real Chrome through the DevTools Protocol (CDP) for platforms that have no public
API, then converts results into the standard record JSON so they flow into `extract` /
`overview`. **Run `literature.py doctor` first** — it reports whether Chrome is listening and
prints the exact engine list read from `browser_search.mjs`.

Status legend: ✅ verified end-to-end · ⚠️ engine ready, blocked by this network or needs a
manual step · ❌ not working.

> **Verification date.** The rows marked ✅ were verified end-to-end in **2026-08**. They were
> **not** re-verified in 2026-11 (site access from the maintainer's network was unavailable).
> Treat ✅ as "worked at the last check", not "works today": if a run returns nothing, read
> the troubleshooting section before editing selectors.

## Engine matrix

| Engine | Search URL template | Login | Status | Notes |
|--------|--------------------|-------|--------|-------|
| `bing` | `https://www.bing.com/search?q=<q>` | no | ✅ | Generic fallback only |
| `duckduckgo` | `https://html.duckduckgo.com/html/?q=<q>` | no | ⚠️ | HTML endpoint; may CAPTCHA headless |
| `google-scholar` | `https://scholar.google.com/scholar?hl=en&q=<q>` | no | ⚠️ | **Automated access conflicts with Google's Terms of Service.** Use manually / low volume only |
| `cnki` | `https://kns.cnki.net/kns8s/defaultresult/index?kw=<q>` | yes (institutional) | ✅ 2026-08 | 53/53 full pagination verified; session persists after one login |
| `wanfang` | `https://s.wanfangdata.com.cn/paper?q=<q>` | yes | ✅ 2026-08 | 2,417 total, 60/60 over 3 pages; detail URLs built from `title-id-hidden` |
| `vip` | `https://qikan.cqvip.com/Qikan/Search/Index?key=<q>` | yes | ⚠️ | 维普; 502/connection-closed from this network at the last check |
| `medjournals` | `https://www.yiigle.com/Paper/Search?searchType=pt&q=<q>` | no | ✅ 2026-08 | 中华医学期刊; calls the site's own `POST /apiVue/search/searchList`, pageSize 50, now capped by `--max` with a per-page delay |
| `pubmed-web` | `https://pubmed.ncbi.nlm.nih.gov/?term=<q>` | no | ✅ | Works headless; useful when the API is blocked |
| `ciinii` | `https://cir.nii.ac.jp/all?q=<q>` | no | ✅ 2026-08 | CiNii Research (Japanese); 10 real records verified |
| `ndl` | `https://ndlsearch.ndl.go.jp/search?cs=bib&q=<q>` | no | ⚠️ | NDL Search; 503 from this network at the last check |
| `base` | `https://www.base-search.net/Search/Results?lookfor=<q>` | no | ⚠️ | 403 from this network; German coverage via OpenAlex/DOAJ meanwhile |
| `cyberleninka` | `https://cyberleninka.ru/search?q=<q>` | no | ✅ 2026-08 | Russian OA library; 10 real records verified |
| `elibrary` | `https://elibrary.ru/query_results.asp?query=<q>` | yes (session) | ⚠️ | Redirects unauthenticated visitors to `start_session.asp`; log in once in the CDP Chrome |

An unknown engine id now **fails with exit 2** and lists the valid ids. It used to fall back
to Bing, which silently returned the wrong database.

## What the engine does on a login wall

The probe waits for a positive results signal. If the timeout expires, the page is inspected
for login/CAPTCHA markers (`登录`, `验证码`, `captcha`, `Access Denied`, `start_session`, …).
If any is found the engine returns:

```json
{"engine": "cnki", "error": "login_or_captcha_required", "detail": "page shows: 登录", "results": []}
```

and `literature.py` exits with code **3**. Zero results and a login wall are different
outcomes and must not be reported the same way.

## Politeness and legal boundary

- Search volumes are for verification and normal literature work, not bulk harvesting.
  `--max` caps every engine; pagination stops at `--max`.
- Never bypass paywalls, never share institutional credentials, never use Sci-Hub/LibGen.
- Google Scholar, CNKI, Wanfang, VIP and eLibrary are used through a **normal logged-in
  browser session the user controls**. You are responsible for complying with each site's
  terms. If a site forbids automated access, stop using that engine and use the manual
  fallback below.
- The module adds a delay between pages and does not retry aggressively. Do not remove those
  delays to "make it faster".

## Query translation by target language

`browser-search` auto-translates the query into the engine's language (free translate
endpoint; `--no-translate` disables it). `translate-query --text "..." --to ja` does it
standalone. `--topic` for `extract` should stay in the language of the records you screen.

| Engine | Target language | Example |
|--------|----------------|---------|
| `cnki`, `wanfang`, `vip`, `medjournals` | zh-CN | `radiomics lung cancer prognosis` → `放射组学肺癌预后` |
| `ciinii`, `ndl` | ja | `radiomics` → `ラジオミクス` |
| `cyberleninka`, `elibrary` | ru | `radiomics` → `радиомика` |
| `base` | de | `Radiomics-Lungenkrebsprognose` |

Verified translations (2026-08): zh-CN `放射组学肺癌预后`, ja `ラジオミクスによる肺がんの予後`,
de `Radiomics-Lungenkrebsprognose`, fr `pronostic du cancer du poumon radiomique`,
ru `радиомиктический прогноз рака легких`. Sentence-form translations work best on free-text
engines; field-syntax engines prefer keyword-style queries.

## Chrome CDP setup (one-time)

Windows PowerShell (fully quit Chrome first):

```powershell
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

The script auto-detects `--port`, then 9222/9223/9224, then the `DevToolsActivePort` file.
Open `chrome://inspect/#remote-debugging` in that Chrome to confirm.

## Manual fallback (CDP unavailable or automation blocked)

1. Print the URL: `python scripts/literature.py browser-search --engine cnki --query "..." --print-url`
2. Open it in a normal browser, log in / solve the CAPTCHA yourself.
3. Save the records you need as standard JSON (one object per record; see
   [record-schema.md](record-schema.md)):

```json
{
  "id": "url or stable id",
  "source_platform": "cnki",
  "title": "标题",
  "url": "https://...",
  "journal": "期刊",
  "pubDate": "2025",
  "authors": ["作者甲", "作者乙"],
  "doi": "",
  "abstract": "完整摘要（若可得）",
  "pmid": ""
}
```

4. Re-run `extract` / `overview` on that file, or pass it to `dedupe` together with the
   API-search results.

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `No Chrome CDP endpoint found` | Chrome not started with `--remote-debugging-port` | Run the setup command above |
| exit 3, `login_or_captcha_required` | Login wall, slider, or CAPTCHA | Log in / solve it once in the visible CDP Chrome, then re-run |
| exit 3, `login_or_captcha_required` on eLibrary | eLibrary has no anonymous search | Log in first; the site redirects to `start_session.asp` otherwise |
| 0 results, page loaded | Site HTML changed | Update selectors in `scripts/browser_search.mjs`, then note it below |
| 0 results, page loaded, selectors look right | Page still rendering | Increase `waitMs` for that engine, or check `--debug 1` output |
| Timeout after `--timeout` seconds | Dead CDP socket / stuck page | Restart Chrome; the CLI no longer hangs forever |
| NDL 503 / VIP 502 / BASE 403 | Network-level block | Engine stays configured; supplement coverage with CiNii / OpenAlex / DOAJ / CyberLeninka and say so in the report |

When you repair a selector, add one line here with the date, engine and what changed — this
file is the only repair log.

### Repair log

- 2026-11: added login/CAPTCHA detection (returns `login_or_captcha_required` instead of an
  empty list); unknown engines now fail; medjournals pagination capped by `--max` with a
  900 ms delay per page; per-run hard timeout in the Python wrapper.
