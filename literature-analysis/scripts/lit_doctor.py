#!/usr/bin/env python3
"""doctor: one command that explains why a search or a scrape is not working.

Most support questions for this skill are environment questions: is Node
installed, is openpyxl missing, is PubMed rate-limiting us, is Chrome actually
listening on a CDP port, which engines are known. `doctor` answers them in one
pass and prints a report the user can paste into an issue.

Exit codes: 0 = usable, 1 = at least one failure (with --strict), 2 = nothing
could be checked. Without --strict it always exits 0 after reporting.
"""

import json
import os
import platform
import re
import shutil
import socket
import subprocess
import sys
import time
import urllib.parse

from lit_common import REPO_URL, __version__, http_json, openpyxl_available

OK, WARN, FAIL, SKIP = "ok", "warn", "fail", "skip"

#: One cheap request per API. Keep the payloads tiny: doctor must stay fast.
ENDPOINTS = [
    ("PubMed", "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi?db=pubmed&term=pubmed%5Bsb%5D&retmax=1&retmode=json&tool=doctor"),
    ("OpenAlex", "https://api.openalex.org/works?per-page=1&select=id"),
    ("Crossref", "https://api.crossref.org/works?rows=0&select=DOI"),
    ("arXiv", "http://export.arxiv.org/api/query?search_query=all:electron&max_results=1"),
    ("Europe PMC", "https://www.ebi.ac.uk/europepmc/webservices/rest/search?query=test&format=json&pageSize=1"),
    ("DOAJ", "https://doaj.org/api/search/articles/test?pageSize=1"),
    ("HAL", "https://api.archives-ouvertes.fr/search/?q=test&rows=0&wt=json"),
    ("Semantic Scholar", "https://api.semanticscholar.org/graph/v1/paper/search?query=test&limit=1&fields=title"),
]

CDP_PORTS = (9222, 9223, 9224)


class Report(object):
    def __init__(self):
        self.rows = []

    def add(self, check, status, detail, ms=None):
        self.rows.append({"check": check, "status": status, "detail": str(detail), "ms": ms})

    def counts(self):
        out = {OK: 0, WARN: 0, FAIL: 0, SKIP: 0}
        for row in self.rows:
            out[row["status"]] = out.get(row["status"], 0) + 1
        return out


def check_python(report):
    version = platform.python_version()
    ok = sys.version_info >= (3, 9)
    report.add("Python", OK if ok else FAIL, version + " (" + platform.platform() + ")")
    if not ok:
        report.add("Python requirement", FAIL, "Python 3.9 or newer is required")


def check_node(report):
    node = shutil.which("node")
    if not node:
        report.add("Node.js", WARN, "not on PATH; browser-search and --xlsx fallbacks are unavailable")
        return
    try:
        out = subprocess.run([node, "--version"], capture_output=True, text=True, timeout=15)
        version = (out.stdout or "").strip()
        major = int(version.lstrip("v").split(".")[0]) if version.startswith("v") else 0
        if major >= 22:
            report.add("Node.js", OK, version + " at " + node)
        else:
            report.add("Node.js", WARN, version + " at " + node + " (22+ required: built-in fetch/WebSocket)")
    except Exception as exc:
        report.add("Node.js", WARN, "found but not runnable: " + str(exc))


def check_openpyxl(report):
    if openpyxl_available():
        try:
            import openpyxl
            report.add("openpyxl", OK, "installed (" + str(openpyxl.__version__) + "); --xlsx enabled")
        except Exception:
            report.add("openpyxl", OK, "installed; --xlsx enabled")
    else:
        report.add("openpyxl", WARN, "missing; --xlsx writes are skipped (pip install openpyxl)")


def check_env(report):
    email = os.environ.get("NCBI_EMAIL") or os.environ.get("LIT_EMAIL") or ""
    report.add("NCBI_EMAIL", OK if email else WARN,
               "set" if email else "not set; NCBI's usage policy asks for a contact address")
    report.add("NCBI_API_KEY", OK if os.environ.get("NCBI_API_KEY") else SKIP,
               "set (10 req/s)" if os.environ.get("NCBI_API_KEY") else "not set (3 req/s, still fine)")


def check_endpoints(report, timeout=8):
    for name, url in ENDPOINTS:
        started = time.time()
        try:
            if "arxiv.org" in url or "doaj.org" in url or "archives-ouvertes" in url:
                from lit_common import http_get
                body = http_get(url, timeout=timeout, retries=1)
                ok = bool(body and len(body) > 20)
            else:
                http_json(url, timeout=timeout, retries=1)
                ok = True
            elapsed = int((time.time() - started) * 1000)
            report.add(name, OK if ok else WARN, "reachable" if ok else "empty response", elapsed)
        except Exception as exc:
            elapsed = int((time.time() - started) * 1000)
            text = str(exc)
            if "429" in text:
                # Semantic Scholar rate-limits anonymous callers by design; this
                # is a degraded source, not a broken environment.
                report.add(name, WARN, "rate limited (HTTP 429) - retry later or use an API key", elapsed)
            else:
                report.add(name, FAIL, _short_error(exc), elapsed)


def _short_error(exc):
    text = str(exc)
    if "404" in text:
        return "HTTP 404 (endpoint moved?)"
    if "403" in text:
        return "HTTP 403 (blocked or needs a key)"
    if "429" in text:
        return "HTTP 429 (rate limited)"
    if "timed out" in text.lower():
        return "timeout"
    return text[:120]


def cdp_ports():
    found = []
    for port in CDP_PORTS:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=1.0):
                found.append(port)
        except Exception:
            continue
    return found


def check_cdp(report):
    ports = cdp_ports()
    if ports:
        report.add("Chrome CDP", OK, "listening on " + ", ".join(str(p) for p in ports))
    else:
        report.add("Chrome CDP", WARN,
                   "no port 9222/9223/9224 listening; browser-search needs "
                   "chrome --remote-debugging-port=9222")


def engines():
    """Read the engine list from browser_search.mjs so doctor cannot drift.

    Parses the keys of the ``ENGINES`` object with a regex rather than scanning
    lines: an engine body may itself contain a line that starts with ``};``.
    """
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "browser_search.mjs")
    try:
        with open(path, "r", encoding="utf-8") as handle:
            text = handle.read()
    except OSError:
        return []
    start = text.find("const ENGINES")
    if start < 0:
        return []
    end = text.find("\n};", start)
    block = text[start:end if end != -1 else len(text)]
    names = re.findall(r'\n\s{2}"([a-z0-9\-]+)"\s*:\s*\{', block)
    return names


def check_engines(report):
    names = engines()
    if names:
        report.add("Browser engines", OK, ", ".join(names))
    else:
        report.add("Browser engines", WARN, "could not read engine list from browser_search.mjs")


def render(report):
    print("literature-analysis doctor  v" + __version__)
    print(REPO_URL)
    print("")
    width = max(len(row["check"]) for row in report.rows)
    for row in report.rows:
        timing = ("  (" + str(row["ms"]) + " ms)") if row["ms"] is not None else ""
        print("  [" + row["status"].upper().ljust(4) + "] " + row["check"].ljust(width)
              + "  " + row["detail"] + timing)
    counts = report.counts()
    print("")
    print("Summary: ok=" + str(counts[OK]) + " warn=" + str(counts[WARN])
          + " fail=" + str(counts[FAIL]) + " skip=" + str(counts[SKIP]))
    if counts[FAIL]:
        print("Fix the FAIL rows first; WARN rows only disable an optional feature.")


def run(args):
    report = Report()
    check_python(report)
    check_node(report)
    check_openpyxl(report)
    check_env(report)
    if args.no_network:
        report.add("Network checks", SKIP, "--no-network given")
    else:
        check_endpoints(report, timeout=args.timeout)
    check_cdp(report)
    check_engines(report)
    if args.json:
        with open(args.json, "w", encoding="utf-8") as handle:
            json.dump({"version": __version__, "rows": report.rows, "summary": report.counts()},
                      handle, ensure_ascii=False, indent=2)
        print("JSON -> " + args.json)
    render(report)
    counts = report.counts()
    if args.strict and counts[FAIL]:
        return 1
    return 0


def add_parser(subparsers):
    parser = subparsers.add_parser(
        "doctor",
        help="Diagnose the environment: Python/Node/openpyxl, API reachability, CDP, engine list",
        description="One-shot environment self-check; paste the output into a bug report.",
    )
    parser.add_argument("--json", help="write the checks as JSON")
    parser.add_argument("--no-network", action="store_true", help="skip API reachability checks")
    parser.add_argument("--timeout", type=int, default=8, help="per-endpoint timeout in seconds")
    parser.add_argument("--strict", action="store_true", help="exit 1 when any check fails")
    parser.set_defaults(func=run)
    return parser


if __name__ == "__main__":
    # Direct use: `python lit_doctor.py --no-network` behaves like
    # `literature.py doctor --no-network`.
    import argparse
    top = argparse.ArgumentParser(description="environment doctor")
    subs = top.add_subparsers(dest="command")
    add_parser(subs)
    parsed = top.parse_args(["doctor"] + sys.argv[1:])
    sys.exit(parsed.func(parsed))
