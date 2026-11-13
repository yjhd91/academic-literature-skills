#!/usr/bin/env node
// Unified browser search via Chrome DevTools Protocol (CDP).
// Drives a real Chrome with remote debugging to search platforms that have no public API.
//
// Usage:
//   node browser_search.mjs --engine bing --query "radiomics lung cancer" [--max 20] [--port 9222]
//   node browser_search.mjs --engine cnki --query "肺结节" --print-url 1
//
// Engines: bing, duckduckgo, google-scholar, pubmed-web, cnki, wanfang, vip,
//          medjournals (yiigle), ciinii, ndl, base, cyberleninka, elibrary
// Requires: Chrome started with --remote-debugging-port (see references/browser-patterns.md).

import { readFileSync } from "node:fs";
import path from "node:path";
import os from "node:os";

const args = process.argv.slice(2);
function opt(name, def) {
  const i = args.indexOf("--" + name);
  return i >= 0 && args[i + 1] ? args[i + 1] : def;
}
const engine = opt("engine", "bing");
const query = opt("query", "");
const max = parseInt(opt("max", "20"), 10);
const port = parseInt(opt("port", "0"), 10);
const urlOverride = opt("url", "");

const ENGINES = {
  "bing": {
    url: (q) => "https://www.bing.com/search?q=" + encodeURIComponent(q) + "&count=20",
    extract: `Array.from(document.querySelectorAll('li.b_algo')).slice(0, ${max}).map(li => {
      const a = li.querySelector('h2 a');
      const p = li.querySelector('.b_caption p, p');
      return { title: a ? a.innerText.trim() : '', url: a ? a.href : '', snippet: p ? p.innerText.trim() : '' };
    }).filter(x => x.title)`,
    waitMs: 3500,
    probe: "li.b_algo",
    needsLogin: false,
  },
  "duckduckgo": {
    url: (q) => "https://html.duckduckgo.com/html/?q=" + encodeURIComponent(q),
    extract: `Array.from(document.querySelectorAll('div.result')).slice(0, ${max}).map(r => {
      const a = r.querySelector('a.result__a');
      const s = r.querySelector('a.result__snippet');
      return { title: a ? a.innerText.trim() : '', url: a ? a.href : '', snippet: s ? s.innerText.trim() : '' };
    }).filter(x => x.title)`,
    waitMs: 4000,
    probe: "div.result",
    needsLogin: false,
  },
  "pubmed-web": {
    url: (q) => "https://pubmed.ncbi.nlm.nih.gov/?term=" + encodeURIComponent(q),
    extract: `Array.from(document.querySelectorAll('.docsum-content')).slice(0, ${max}).map(r => {
      const a = r.querySelector('a.docsum-title');
      const m = r.querySelector('.full-journal-citation');
      const s = r.querySelector('.docsum-snippet');
      return { title: a ? a.innerText.trim() : '', url: a ? a.href : '', meta: m ? m.innerText.trim() : '', snippet: s ? s.innerText.trim() : '' };
    }).filter(x => x.title)`,
    waitMs: 10000,
    probe: ".docsum-content",
    needsLogin: false,
  },
  "ciinii": {
    url: (q) => "https://cir.nii.ac.jp/all?q=" + encodeURIComponent(q),
    extract: `(() => {
      const seen = new Set();
      const seenTitles = new Set();
      return Array.from(document.querySelectorAll('a[href*="/crid/"], a[href*="/articles/"]')).map(a => {
        const block = a.closest('div, li');
        return { title: a.innerText.trim(), url: a.href, snippet: block ? block.innerText.slice(0, 220) : '' };
      }).filter(x => {
        const t = (x.title || '').replace(/\u00A0/g, ' ').replace(/[，,]/g, ',').replace(/　/g, ' ').trim();
        x.title = t;
        const isName = /^[A-Z][a-z]+,\\s*[A-Z][a-z]+$/.test(t) || /^[A-Z][a-z]+(?:\\s+[A-Z][a-z]+)+$/.test(t);
        return t.length > 12
          && !isName
          && !seen.has(x.url.toLowerCase()) && seen.add(x.url.toLowerCase())
          && !seenTitles.has(t.toLowerCase()) && seenTitles.add(t.toLowerCase());
      }).slice(0, ${max});
    })()`,
    waitMs: 12000,
    probe: () => `document.querySelectorAll('a[href*="/crid/"], a[href*="/articles/"]').length > 0`,
    needsLogin: false,
  },
  "base": {
    url: (q) => "https://www.base-search.net/Search/Results?lookfor=" + encodeURIComponent(q),
    extract: `Array.from(document.querySelectorAll('.result, .result-item, li.list-item')).slice(0, ${max}).map(r => {
      const a = r.querySelector('a[href*="base-search"], h2 a, a.result-title');
      const s = r.querySelector('.result-text, .snippet');
      return { title: a ? a.innerText.trim() : '', url: a ? a.href : '', snippet: s ? s.innerText.trim() : '' };
    }).filter(x => x.title)`,
    waitMs: 10000,
    probe: ".result, .result-item",
    needsLogin: false,
  },
  "cyberleninka": {
    url: (q) => "https://cyberleninka.ru/search?q=" + encodeURIComponent(q),
    extract: `Array.from(document.querySelectorAll('a[href*="/article/n/"]')).slice(0, ${max}).map(a => ({
      title: a.innerText.trim(), url: a.href, snippet: ''
    })).filter(x => x.title)`,
    waitMs: 12000,
    probe: () => `document.querySelectorAll('a[href*="/article/n/"]').length > 0`,
    needsLogin: false,
  },
  "google-scholar": {
    url: (q) => "https://scholar.google.com/scholar?hl=en&q=" + encodeURIComponent(q),
    extract: `Array.from(document.querySelectorAll('.gs_r.gs_or')).slice(0, ${max}).map(r => {
      const a = r.querySelector('.gs_ri h3 a');
      const m = r.querySelector('.gs_a');
      const s = r.querySelector('.gs_rs');
      return { title: a ? a.innerText.trim() : '', url: a ? a.href : '', meta: m ? m.innerText.trim() : '', snippet: s ? s.innerText.trim() : '' };
    }).filter(x => x.title)`,
    waitMs: 4500,
    probe: ".gs_r",
    needsLogin: false,
  },
  "cnki": {
    url: (q) => "https://kns.cnki.net/kns8s/defaultresult/index?kw=" + encodeURIComponent(q),
    postNav: (q) => `(() => {
      const inp = document.querySelector('input[type="text"], input.txt-input, #txt_search');
      if (!inp) return false;
      const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
      setter.call(inp, ${JSON.stringify(q)});
      inp.dispatchEvent(new Event('input', { bubbles: true }));
      inp.focus();
      inp.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', keyCode: 13, which: 13, bubbles: true }));
      inp.dispatchEvent(new KeyboardEvent('keyup', { key: 'Enter', keyCode: 13, which: 13, bubbles: true }));
      return true;
    })()`,
    extract: `Array.from(document.querySelectorAll('table tbody tr, #gridTable tr, .result-table-list tr')).slice(0, ${max}).map(r => {
      const a = r.querySelector('td a, .name a, a');
      const cells = Array.from(r.querySelectorAll('td')).map(c => c.innerText.trim());
      const title = a ? a.innerText.trim() : '';
      if (!title || cells.length < 2) return null;
      const pick = (i, j) => cells[i] || cells[j] || '';
      return { title, url: a.href, authors: pick(2, 1), journal: pick(3, 2), pubDate: pick(4, 3), snippet: '' };
    }).filter(Boolean)`,
    waitMs: 15000,
    probe: () => `document.body.innerText.includes('共找到')`,
    totalExpr: () => `(() => { const m = document.body.innerText.match(/共找到\\s*(\\d+)\\s*条结果/); return m ? m[1] : ''; })()`,
    nextPage: `(() => {
      const b = Array.from(document.querySelectorAll('a, button')).find(x => x.innerText && x.innerText.trim() === '下一页')
                || document.querySelector('#PageNext, .page-next');
      if (!b || b.getAttribute('aria-disabled') === 'true' || b.disabled) return false;
      b.click();
      return true;
    })()`,
    needsLogin: true,
  },
  "wanfang": {
    url: (q) => "https://s.wanfangdata.com.cn/paper?q=" + encodeURIComponent(q),
    extract: `Array.from(document.querySelectorAll('div.normal-list')).slice(0, ${max}).map(r => {
      const t = r.querySelector('.title-area .title');
      const idEl = r.querySelector('.title-id-hidden');
      const abs = r.querySelector('.abstract-area');
      const authEls = Array.from(r.querySelectorAll('.author-area .authors')).map(a => a.innerText.trim()).filter(Boolean);
      const j = r.querySelector('.periodical-title');
      const id = idEl ? idEl.innerText.trim().replace(/^periodical_/, '') : '';
      return {
        title: t ? t.innerText.trim().replace(/^\\d+\\.\\s*/, '') : '',
        url: id ? 'https://d.wanfangdata.com.cn/periodical/' + id : '',
        authors: authEls.length > 1 ? authEls.slice(0, -1).join('; ') : '',
        journal: j ? j.innerText.trim() : '',
        pubDate: authEls.length ? authEls[authEls.length - 1] : '',
        snippet: abs ? abs.innerText.trim().replace(/^摘要：/, '') : '',
      };
    }).filter(x => x.title)`,
    waitMs: 10000,
    probe: () => `document.querySelectorAll('div.normal-list').length > 0 || document.body.innerText.includes('找到')`,
    totalExpr: () => `(() => { const m = document.body.innerText.match(/找到([\\d,]+)条文献/); return m ? m[1] : ''; })()`,
    nextPage: `(() => {
      const b = Array.from(document.querySelectorAll('span.ctrl-btn, a.ctrl-btn, .ctrl-btn')).find(x => (x.innerText || '').trim() === '>');
      if (b) { b.click(); return true; }
      return false;
    })()`,
    needsLogin: true,
  },
  "vip": {
    url: (q) => "https://qikan.cqvip.com/Qikan/Search/Index?key=" + encodeURIComponent(q),
    extract: `Array.from(document.querySelectorAll('.result-list li, .list-item, .result-item')).slice(0, ${max}).map(r => {
      const a = r.querySelector('a.title, h3 a, a');
      const abs = r.querySelector('.abstract, .summary');
      return { title: a ? a.innerText.trim() : '', url: a ? a.href : '', snippet: abs ? abs.innerText.trim() : '' };
    }).filter(x => x.title)`,
    waitMs: 6000,
    probe: ".result-list li, .list-item, .result-item",
    needsLogin: true,
  },
  "medjournals": {
    // 中华医学期刊全文数据库 (medjournals.cn -> www.yiigle.com/Paper/Search)
    // Public-facing Vue app; results come from POST /apiVue/search/searchList.
    // We call the API from the page context so cookies/localStorage token apply.
    url: (q) => "https://www.yiigle.com/Paper/Search?searchType=pt&q=" + encodeURIComponent(q),
    extractAsync: `(async () => {
      const token = localStorage.getItem('_login-token') || '';
      const q = ${JSON.stringify("__QUERY__")};
      const limit = ${max};
      const pageSize = 50;
      const pageCap = Math.min(200, Math.ceil(limit / pageSize) + 1);
      const out = [];
      let total = '';
      for (let page = 1; out.length < limit && page <= pageCap; page++) {
        // Be a polite client: one request per page with a gap, capped by --max.
        if (page > 1) await new Promise(r => setTimeout(r, 900));
        const r = await fetch('/apiVue/search/searchList', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            sortField: '', page, searchType: 'pt', pageSize,
            queryString: q, query: '', searchText: q, searchLog: q,
            isAggregations: 'N', logintoken: token
          })
        });
        if (!r.ok) break;
        const j = await r.json();
        const res = j && j.data && j.data.result;
        if (!res) break;
        if (page === 1) total = String(res.searchTotal || '');
        const items = (res.infos || []);
        for (const x of items) {
          const authors = (x.authorNames || []).join('; ');
          const date = x.artPubYear ? String(x.artPubYear) : (x.artPubDate || '').slice(0, 10);
          out.push({
            title: x.artTitle || '',
            url: x.artUrl || '',
            doi: x.artDoi || '',
            authors,
            journal: x.journalCn || '',
            pubDate: date,
            meta: [x.docType, x.journalCn, x.vol ? x.vol + '卷' : '', x.issue ? x.issue + '期' : '', x.startPage ? x.startPage + '-' + (x.endPage || '') : ''].filter(Boolean).join(' '),
            snippet: x.artAbstract || '',
            total
          });
          if (out.length >= limit) break;
        }
        if (items.length < pageSize) break;
      }
      if (out.length && out[0].total) total = out[0].total;
      return { items: out, total };
    })()`,
    waitMs: 12000,
    probe: () => `document.body.innerText.includes('找到') || location.href.includes('yiigle.com/Paper/Search')`,
    needsLogin: false,
  },
  "ndl": {
    // NDL Search (国立国会図書館サーチ). Best effort: some networks/IPs get 503.
    // Results are rendered client-side; record links look like /books/R100000002-*.
    url: (q) => "https://ndlsearch.ndl.go.jp/search?cs=bib&q=" + encodeURIComponent(q),
    extract: `(() => {
      const seen = new Set();
      return Array.from(document.querySelectorAll('a[href*="/books/"], a[href*="/R/"], [class*="record"] a, [class*="result"] a')).slice(0, ${max * 4}).map(a => {
        const block = a.closest('li, article, div');
        return { title: a.innerText.trim(), url: a.href, snippet: block ? block.innerText.slice(0, 220) : '' };
      }).filter(x => x.title && x.title.length > 5 && !seen.has(x.url) && seen.add(x.url)).slice(0, ${max});
    })()`,
    waitMs: 12000,
    probe: () => `document.querySelectorAll('a[href*="/books/"], a[href*="/R/"]').length > 0`,
    needsLogin: false,
  },
  "elibrary": {
    // eLIBRARY.RU (俄罗斯). 强制登录会话:未登录会被重定向到 start_session.asp。
    // 登录一次后(在可见 CDP Chrome 窗口),结果页 query_results.asp 的表格可被解析。
    url: (q) => "https://elibrary.ru/query_results.asp?query=" + encodeURIComponent(q) + "&where_name=1&where_abstract=1&type_article=1",
    extract: `(() => {
      const seen = new Set();
      const rows = Array.from(document.querySelectorAll('tr')).map(tr => {
        const a = tr.querySelector('a[href*="item.asp?id="]');
        if (!a) return null;
        const cells = Array.from(tr.querySelectorAll('td')).map(c => c.innerText.trim());
        return { title: a.innerText.trim(), url: 'https://elibrary.ru/' + a.getAttribute('href'), snippet: cells.join(' | ').slice(0, 260) };
      }).filter(Boolean);
      return rows.filter(x => x.title && !seen.has(x.url) && seen.add(x.url)).slice(0, ${max});
    })()`,
    waitMs: 12000,
    probe: () => `document.querySelectorAll('a[href*="item.asp?id="]').length > 0 || document.body.innerText.includes('Вход в библиотеку') || document.body.innerText.includes('Результаты')`,
    needsLogin: true,
  },
};

function discoverPorts() {
  const ports = new Set();
  if (port > 0) ports.add(port);
  ports.add(9222);
  const candidates = [];
  if (os.platform() === "win32") {
    candidates.push(path.join(process.env.LOCALAPPDATA || "", "Google/Chrome/User Data/DevToolsActivePort"));
  } else if (os.platform() === "darwin") {
    candidates.push(path.join(os.homedir(), "Library/Application Support/Google/Chrome/DevToolsActivePort"));
  } else {
    candidates.push(path.join(os.homedir(), ".config/google-chrome/DevToolsActivePort"));
  }
  for (const c of candidates) {
    try {
      const first = readFileSync(c, "utf8").split("\n")[0].trim();
      if (/^\d+$/.test(first)) ports.add(parseInt(first, 10));
    } catch { /* ignore */ }
  }
  return [...ports];
}

async function openTarget(port) {
  for (const host of ["127.0.0.1", "localhost", "[::1]"]) {
    const base = `http://${host}:${port}`;
    try {
      const target = await fetch(base + "/json/new?about:blank", { method: "PUT" }).then((r) => r.json());
      if (target.webSocketDebuggerUrl) return target.webSocketDebuggerUrl;
    } catch { /* try next host */ }
  }
  throw new Error("no CDP target");
}

async function run() {
  if (opt("list", "") === "1") {
    // Machine-readable engine list, used by lit_doctor and by the CLI help.
    console.log(JSON.stringify({ engines: Object.keys(ENGINES) }, null, 2));
    process.exit(0);
  }
  const cfg = ENGINES[engine];
  if (!cfg) {
    // Never fall back to Bing: a typo would silently return the wrong database.
    console.error(JSON.stringify({ error: "unknown engine: " + engine, engines: Object.keys(ENGINES) }));
    process.exit(2);
  }
  if (opt("print-url", "") === "1") {
    console.log(cfg.url(query));
    process.exit(0);
  }
  if (!query) {
    console.error(JSON.stringify({ error: "missing --query" }));
    process.exit(1);
  }
  const targetUrl = urlOverride || cfg.url(query);
  let wsUrl = null;
  let usedPort = null;
  for (const p of discoverPorts()) {
    try {
      wsUrl = await openTarget(p);
      usedPort = p;
      break;
    } catch { /* try next port */ }
  }
  if (!wsUrl) {
    console.error(JSON.stringify({ error: "No Chrome CDP endpoint found. Start Chrome with --remote-debugging-port=9222 (see references/browser-patterns.md).", needsLogin: cfg.needsLogin }));
    process.exit(1);
  }

  const ws = new WebSocket(wsUrl);
  await new Promise((res, rej) => { ws.onopen = res; ws.onerror = () => rej(new Error("ws connect failed")); });
  let id = 0;
  const pending = new Map();
  ws.onmessage = (ev) => {
    const msg = JSON.parse(ev.data);
    if (msg.id && pending.has(msg.id)) {
      pending.get(msg.id)(msg);
      pending.delete(msg.id);
    }
  };
  const send = (method, params = {}) =>
    new Promise((res) => {
      const mid = ++id;
      pending.set(mid, res);
      ws.send(JSON.stringify({ id: mid, method, params }));
    });

  await send("Page.enable");
  await send("Runtime.enable");
  await send("Page.navigate", { url: targetUrl });
  if (cfg.postNav) {
    await new Promise((r) => setTimeout(r, 1500));
    await send("Runtime.evaluate", { expression: cfg.postNav(query), returnByValue: true });
  }
  const probeExpr = typeof cfg.probe === "function" ? cfg.probe() : cfg.probe;
  const start = Date.now();
  let probeHit = false;
  while (Date.now() - start < cfg.waitMs) {
    const probeRes = await send("Runtime.evaluate", {
      expression: probeExpr,
      returnByValue: true,
    });
    if (probeRes.result && probeRes.result.result && probeRes.result.result.value === true) {
      probeHit = true;
      await new Promise((r) => setTimeout(r, 800));
      break;
    }
    await new Promise((r) => setTimeout(r, 1200));
  }
  if (opt("debug", "") === "1") {
    const dbg = await send("Runtime.evaluate", {
      expression: `JSON.stringify({ title: document.title, url: location.href, body: (document.body ? document.body.innerText.slice(0, 900) : '') })`,
      returnByValue: true,
    });
    console.error("[debug] " + (dbg.result && dbg.result.result && dbg.result.result.value));
  }
  // A timeout is not the same as "zero results". Detect the login/CAPTCHA wall
  // explicitly so the caller can tell the user to log in instead of silently
  // reporting that this database has no relevant literature.
  if (!probeHit) {
    const wall = await send("Runtime.evaluate", {
      expression: `(() => {
        const t = document.body ? document.body.innerText : '';
        const u = location.href;
        const marks = ['登录', '登入', 'Sign in', 'Log in', '验证码', 'captcha', '安全验证', '请完成验证',
                       'Access Denied', 'Forbidden', '人机验证', 'start_session'];
        const hit = marks.filter(m => t.includes(m) || u.includes(m));
        return JSON.stringify({ hit, url: u, excerpt: t.slice(0, 300) });
      })()`,
      returnByValue: true,
    });
    const raw = (wall.result && wall.result.result && wall.result.result.value) || "{}";
    let info = {};
    try { info = JSON.parse(raw); } catch { /* ignore */ }
    if (info.hit && info.hit.length) {
      console.log(JSON.stringify({
        engine, query, error: "login_or_captcha_required",
        detail: "page shows: " + info.hit.join(", "),
        url: info.url, excerpt: info.excerpt, needsLogin: cfg.needsLogin,
        results: [],
      }, null, 2));
      ws.close();
      return;
    }
  }
  let items = [];
  let total = "";
  if (cfg.extractAsync) {
    const expr = cfg.extractAsync.replace("__QUERY__", query.replace(/\\/g, "\\\\").replace(/"/g, '\\"'));
    const evalRes = await send("Runtime.evaluate", { expression: expr, returnByValue: true, awaitPromise: true });
    const val = (evalRes.result && evalRes.result.result && evalRes.result.result.value) || null;
    if (val && Array.isArray(val.items)) items = val.items;
    if (val && val.total) total = val.total;
  } else {
    const evalRes = await send("Runtime.evaluate", { expression: cfg.extract, returnByValue: true });
    items = (evalRes.result && evalRes.result.result && evalRes.result.result.value) || [];
  }
  let all = items.slice();
  if (cfg.nextPage) {
    let guard = 0;
    const seen = new Set(all.map((x) => x.url));
    while (all.length < max && guard < 50) {
      const nx = await send("Runtime.evaluate", { expression: cfg.nextPage, returnByValue: true });
      const clicked = nx.result && nx.result.result && nx.result.result.value;
      if (!clicked) break;
      await new Promise((r) => setTimeout(r, 4200));
      const more = await send("Runtime.evaluate", { expression: cfg.extract, returnByValue: true });
      const moreItems = (more.result && more.result.result && more.result.result.value) || [];
      let added = 0;
      for (const it of moreItems) {
        if (!seen.has(it.url)) {
          seen.add(it.url);
          all.push(it);
          added++;
        }
      }
      if (added === 0) break;
      guard++;
    }
  }
  const results = all.slice(0, max);
  if (!total && cfg.totalExpr) {
    const t = await send("Runtime.evaluate", { expression: cfg.totalExpr(), returnByValue: true });
    total = (t.result && t.result.result && t.result.result.value) || "";
  }
  console.log(JSON.stringify({
    engine, query, targetUrl, port: usedPort, needsLogin: cfg.needsLogin,
    count: results.length, total, results,
  }, null, 2));
  ws.close();
}

run().catch((e) => {
  console.error(JSON.stringify({ error: String((e && e.message) || e) }));
  process.exit(1);
});
