# Changelog

All notable changes to this repository are documented here. The version applies to both
skills (`literature-analysis`, `pubmed-live`) and follows semantic versioning for the CLI.

## 2.0.0 — 2026-11-13

This release is about **verifiability**: the pipeline can now prove that a reference exists,
recompute the numbers of a systematic review, and say why a source failed.

### Added

- **`verify`** — cross-checks each reference against Crossref, PubMed and OpenAlex and assigns
  one of five verdicts (`verified`, `partial`, `mismatch`, `not_found`, `no_identifier`).
  Reads records JSON, BibTeX, DOI/PMID lists or single identifiers; writes CSV/JSON/Markdown;
  `--strict` turns it into a pre-submission gate. A DOI that resolves nowhere is reported as
  fabricated until proven otherwise.
- **`prisma`** — recomputes PRISMA 2020 flow counts (identified, duplicates removed, screened,
  excluded with reasons, included, uncertain, undecided) from the search files and a screening
  table. Refuses to call an incomplete screening "complete"; `--strict` enforces that.
- **`dedupe`** — merges several record files with an auditable report: how many records were
  folded by identifier, how many by title (flagged for review), which fields were rescued from
  duplicates, and which same-title/different-DOI pairs were deliberately **not** merged.
- **`doctor`** — one-shot environment diagnosis: Python/Node/openpyxl, `NCBI_EMAIL`/
  `NCBI_API_KEY`, reachability and latency of eight APIs, Chrome CDP ports, and the browser
  engine list (read from `browser_search.mjs`, so it cannot drift).
- **Built-in PubMed client** (`lit_pubmed.py`) — `literature-analysis` no longer shells out to
  the sibling skill, so both skills can be installed independently. Sends `email`/`api_key`
  per NCBI policy.
- **Language-aware topic relevance** — CJK bigrams and Cyrillic words, plus a literal-match
  shortcut. Chinese, Japanese and Russian records are no longer scored 0 and excluded.
- **Chinese/Japanese extraction markers** for study design, sample size, validation and
  limitations.
- **Tests** — 66 offline unit tests covering identifier normalisation, dedupe accounting,
  field merging, PRISMA counting, verification verdicts, BibTeX parsing, CJK extraction and
  the CLI contract.
- **CI** — GitHub Actions runs the test suite on Python 3.9/3.12/3.13, validates the skill
  frontmatter and internal links, and syntax-checks the Node module.
- **`evals/`** — realistic prompts with assertions, following the Agent Skills evaluation
  pattern.
- **Reference documentation** — `references/commands.md` (every flag), `references/
  record-schema.md` (the shared record and decision schema).

### Changed

- `SKILL.md` rewritten for the Agent Skills specification: `license`, `compatibility` and
  `metadata` frontmatter, a workflow checklist, hard rules, a gotchas section, explicit
  "do not use for…" boundaries, and the detailed command reference moved to
  `references/commands.md` (progressive disclosure).
- `search-multi` now tolerates a failing source instead of aborting, merges fields from every
  platform that returned a paper, and reports how many duplicates were folded.
- Crossref search filters out peer-review artefacts ("Review for …") and restricts results to
  citable types, so relevance ranking returns literature rather than referee reports.
- Citation counts are stored per platform with a retrieval timestamp
  (`citation_sources.openalex = {count, retrieved_at, id}`) and are never summed.
- HTTP retries are bounded (3 attempts, 30 s per URL, `Retry-After` honoured) and share one
  User-Agent with an optional polite-pool `mailto`.
- Browser search: unknown engine ids fail loudly, a login/CAPTCHA wall returns
  `login_or_captcha_required` with exit code 3 instead of an empty list, medjournals pagination
  is capped by `--max` with a per-page delay, and the Node run has a hard timeout.
- `browser-patterns.md`: engine matrix now carries ✅/⚠️/❌ status, the verification date, a
  politeness/legal boundary section, a troubleshooting table and a repair log.
- README rewritten: capability matrix with verification dates, quick start, environment
  variables, testing instructions and honest limitations.

### Fixed

- `extract --topic "肺结节 放射组学"` crashed with
  `TypeError: unsupported format string passed to NoneType.__format__`.
- Chinese/Japanese/Russian records were systematically judged "low relevance" and excluded,
  breaking Step 3 → Step 4 for every no-API database.
- `pubmed.py fetch 99999999` returned a fabricated blank record instead of an error.
- Duplicate DOIs in different spellings (`https://doi.org/…`, `DOI:`, trailing punctuation,
  trailing slash) were counted as different papers.
- `merged.setdefault` kept the first copy's empty fields, so a PubMed record arriving before
  Crossref lost its citation count, OA status and PDF link.
- `extract --xlsx` crashed when openpyxl was missing; `overview --xlsx` already degraded
  gracefully. Both now share one fallback.
- `search-all` without `--queries` crashed with `AttributeError` instead of a usage message.
- The Node path was hardcoded to one machine's install directory.
- `first_str(0)` dropped a citation count of zero from tables.
- `--max-mesh` was accepted but ignored.
- Crossref received `mailto: research@example.com`, which cannot enter the polite pool.

### Removed

- The generated `npm-publish-github-packages.yml` workflow. It ran `npm ci`/`npm test`/
  `npm publish` on a repository with no `package.json`, so every release failed. Replaced by a
  real Python/Node CI workflow.
- The hard dependency of `literature-analysis` on `../pubmed-live/scripts/pubmed.py`.

### Credits

Design reviewed against the Agent Skills specification (agentskills.io, current as of
2026-11), [anthropics/skills](https://github.com/anthropics/skills),
[ustc-ai4science/academic-search](https://github.com/ustc-ai4science/academic-search),
[openags/paper-search-mcp](https://github.com/openags/paper-search-mcp),
[K-Dense-AI/scientific-agent-skills](https://github.com/K-Dense-AI/scientific-agent-skills)
and Imbad0202/academic-research-skills' `sr-screener`. No code was copied from projects under
non-permissive licences; the ideas adopted are: per-platform citation provenance, "title
matches are candidates, not merges", bounded retry budgets, and PRISMA counts recomputed from
files rather than retyped.

## 1.x — 2026-08

- Initial public release: `pubmed-live` and `literature-analysis`, multi-platform strategy
  generation, eight API sources, twelve browser engines (CNKI/Wanfang/VIP/medjournals/CiNii/
  NDL/BASE/CyberLeninka/eLibrary/Google Scholar/PubMed web/Bing/DuckDuckGo), extraction and
  screening, xlsx/BibTeX/RIS export, legal OA PDF download.
