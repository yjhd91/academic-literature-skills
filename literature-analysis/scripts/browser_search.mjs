#!/usr/bin/env node
// Unified browser search via Chrome DevTools Protocol (CDP).
// Drives a real Chrome with remote debugging to search platforms that have no public API.
//
// Usage:
//   node browser_search.mjs --engine bing --query "radiomics lung cancer" [--max 20] [--port 9222]
//   node browser_search.mjs --engine cnki --query "肺结节" --print-url 1
//
// Engines: bing, google-scholar, cnki, wanfang, vip
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
    extract: `Array.from(document.querySelectorAll('.result-table-list tbody tr, .list-item, .result-item')).slice(0, ${max}).map(r => {
      const a = r.querySelector('a[href*="detail"], .name a, a');
      return { title: a ? a.innerText.trim() : r.innerText.trim().split('\\n')[0], url: a ? a.href : '', snippet: '' };
    }).filter(x => x.title)`,
    waitMs: 6000,
    probe: ".result-table-list tbody tr, .list-item",
    needsLogin: true,
  },
  "wanfang": {
    url: (q) => "https://s.wanfangdata.com.cn/paper?q=" + encodeURIComponent(q),
    extract: `Array.from(document.querySelectorAll('.title, .result-item')).slice(0, ${max}).map(r => {
      const a = r.querySelector('a');
      return { title: r.innerText.trim().split('\\n')[0], url: a ? a.href : '', snippet: '' };
    }).filter(x => x.title)`,
    waitMs: 6000,
    probe: ".title, .result-item",
    needsLogin: true,
  },
  "vip": {
    url: (q) => "https://qikan.cqvip.com/Qikan/Search/Index?key=" + encodeURIComponent(q),
    extract: `Array.from(document.querySelectorAll('.result-list li, .list-item')).slice(0, ${max}).map(r => {
      const a = r.querySelector('a');
      return { title: a ? a.innerText.trim() : '', url: a ? a.href : '', snippet: '' };
    }).filter(x => x.title)`,
    waitMs: 6000,
    probe: ".result-list li, .list-item",
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
  if (opt("print-url", "") === "1") {
    const cfg = ENGINES[engine] || ENGINES.bing;
    console.log(cfg.url(query));
    process.exit(0);
  }
  const cfg = ENGINES[engine] || ENGINES.bing;
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
  const start = Date.now();
  while (Date.now() - start < cfg.waitMs) {
    const probeRes = await send("Runtime.evaluate", {
      expression: `document.querySelectorAll('${cfg.probe}').length > 0`,
      returnByValue: true,
    });
    if (probeRes.result && probeRes.result.result && probeRes.result.result.value === true) {
      await new Promise((r) => setTimeout(r, 800));
      break;
    }
    await new Promise((r) => setTimeout(r, 1200));
  }
  if (opt("debug", "") === "1") {
    const dbg = await send("Runtime.evaluate", {
      expression: `JSON.stringify({ title: document.title, url: location.href, algo: document.querySelectorAll('li.b_algo').length, docsum: document.querySelectorAll('article.docsum, .docsum-title, .docsum-content').length, body: (document.body ? document.body.innerText.slice(0, 600) : '') })`,
      returnByValue: true,
    });
    console.error("[debug] " + (dbg.result && dbg.result.result && dbg.result.result.value));
  }
  const evalRes = await send("Runtime.evaluate", { expression: cfg.extract, returnByValue: true });
  const items = (evalRes.result && evalRes.result.result && evalRes.result.result.value) || [];
  const results = items.slice(0, max);
  console.log(JSON.stringify({
    engine, query, targetUrl, port: usedPort, needsLogin: cfg.needsLogin,
    count: results.length, results,
  }, null, 2));
  ws.close();
}

run().catch((e) => {
  console.error(JSON.stringify({ error: String((e && e.message) || e) }));
  process.exit(1);
});
