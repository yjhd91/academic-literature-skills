# Command reference

All commands: `python scripts/literature.py <command> [flags]` (Windows, Linux, macOS alike).
`--version` prints the tool version. Run `doctor` first whenever a command misbehaves.

Common conventions
- `--in` reads a records file produced by any command here: a JSON list, a JSON object
  with a `records`/`results`/`data` key, or JSON Lines. See
  [record-schema.md](record-schema.md).
- `--out` is always written as UTF-8; `--xlsx` needs `openpyxl` and degrades to CSV otherwise.
- Exit codes: `0` ok, `1` strict failure, `2` bad usage, `3` login/CAPTCHA wall.

---

## doctor

```
literature.py doctor [--json PATH] [--no-network] [--strict] [--timeout N]
```

Checks Python/Node/openpyxl, `NCBI_EMAIL`/`NCBI_API_KEY`, reachability and latency of
PubMed, OpenAlex, Crossref, arXiv, Europe PMC, DOAJ, HAL, Semantic Scholar, Chrome CDP
ports, and the browser engine list (read from `browser_search.js` at run time).
`--strict` exits 1 if any check fails. `--no-network` gives a fast offline view.

---

## strategy / translate

```
literature.py strategy --concepts "radiomics|lung cancer|prognosis" \
    [--sources pubmed,openalex,crossref,arxiv,semanticscholar,europepmc,doaj,hal] \
    [--dates "2023/01/01:2026/11/01"] [--test] [--max-mesh 3] \
    [--out pubmed_queries.txt] [--strategy-out strategy.json]
```

Writes one native query per platform. `--test` prints a hit count per variant: **zero hits
usually means broken syntax or an over-narrow field**. `--strategy-out` feeds
`search-multi --strategy-file`.

`translate` is the same conversion without saving a full strategy.

## search-multi

```
literature.py search-multi --query "…" | --strategy-file strategy.json \
    --sources pubmed,openalex,crossref [--max 10] [--from 2023/01/01] [--to 2026/11/01] \
    [--sort relevance|citations|date] --out results.json
```

Searches the selected APIs, merges duplicates by DOI → PMID → provider id, fills missing
fields from whichever copy has them, and keeps `sources: [...]`. **One failing source does
not abort the run**; failures are listed at the end. Records with no identifier are matched
on a normalised title and flagged for review; records with different DOIs and the same title
are reported, not merged. A `report` is not written here — use `dedupe --report`.

## search-all / fetch

```
literature.py search-all --queries "q1|q2|q3" | --queries-file queries.txt --max 10 --out results.json
literature.py fetch --query "…" --max 10 --out results.json
```

`search-all` merges PubMed query variants by PMID. `fetch` is a single PubMed query.

## browser-search

```
literature.py browser-search --engine cnki --query "肺结节 放射组学" [--max 50] \
    [--port 9222] [--no-translate] [--print-url] [--url URL] [--timeout 600] \
    [--out cnki.json] [--xlsx cnki.xlsx]
```

Engine ids: `bing`, `duckduckgo`, `google-scholar`, `pubmed-web`, `cnki`, `wanfang`, `vip`,
`medjournals`, `ciinii` (CiNii Research), `ndl`, `base`, `cyberleninka`, `elibrary`.
Unknown ids fail loudly (exit 2) instead of silently falling back to Bing.

Query translation is automatic per engine language (zh-CN / ja / de / ru). A login wall or
CAPTCHA returns `{"error": "login_or_captcha_required"}` and exit 3 — **not** an empty list.
`--timeout` bounds the whole Node run so a dead CDP socket cannot hang the CLI.

## dedupe

```
literature.py dedupe --in pubmed.json --in cnki.json --out merged.json [--report dedupe.json]
```

Prints: input → unique, how many merged by identifier, how many by title (for review), how
many records still have no identifier, which fields were rescued from duplicates, and every
"same title, different identifier" pair that was deliberately **not** merged.

## verify

```
literature.py verify --in merged.json --out verify.csv --md verify.md --strict
literature.py verify --bib references.bib [--no-title-lookup] [--strict]
literature.py verify --doi 10.1186/s12967-024-06057-y
literature.py verify --pmid 40181378
literature.py verify --dois-file dois.txt | --pmids-file pmids.txt
```

Verdicts: `verified` (≥2 registries, title similarity ≥0.90, year within ±1),
`partial` (one registry, or similarity 0.70–0.90), `mismatch` (identifier resolves but the
metadata does not match, or the year is off by more than one), `not_found` (nothing resolves —
treat the identifier as fabricated), `no_identifier`. A DOI-only input is judged on
resolution only and says so in `notes`.

`--strict` exits 1 when any reference is `mismatch`, `not_found` or `no_identifier`, which
makes it usable as a pre-submission gate.

## prisma

```
literature.py prisma --in pubmed.json --in cnki.json --decisions screen.csv \
    [--source-label PubMed --source-label CNKI] [--stage title_abstract|full_text] \
    [--label "review title"] [--out prisma.md] [--json-out prisma.json] \
    [--decisions-out excluded.csv] [--strict]
```

Decisions CSV/JSON columns (case-insensitive, extra columns ignored): `doi`, `pmid`, `title`,
`decision`, `reason`, `stage`. Decision values accept include/exclude/uncertain in English or
Chinese. Counts are **recomputed**, not transcribed: duplicates are recomputed from the record
files. The report flags `No decision` and unmatched decisions; `--strict` exits 1 while the
screening is incomplete. `records ≠ reports ≠ studies`: one study may have several reports
(preprint, journal version, follow-up) — link those by trial ID or cohort manually.

## lite / extract / screen / overview / template

```
literature.py lite --in results.json
literature.py extract --in results.json --out overview.csv [--xlsx overview.xlsx] \
    [--topic "radiomics lung cancer"] [--include "external validation|prospective"] \
    [--exclude "review|animal|editorial"]
literature.py screen --in results.json --out triage.csv --include … --exclude …
literature.py overview --in results.json --out overview.csv [--xlsx overview.xlsx]
literature.py template --in results.json --out template.csv [--fields "study design,sample size"]
```

`extract` fills 16 overview columns from titles/abstracts with rules. Topic relevance is
language-aware (Latin words, CJK bigrams, Cyrillic words), so Chinese records are no longer
scored 0. Every row keeps an `evidence` column of auto-detected snippets. **Review each row.**

`screen` is deterministic keyword triage only; it is a first pass, never the final decision.

## enrich / export / download-pdf

```
literature.py enrich --in results.json --out enriched.json
literature.py export --in enriched.json --format bib|ris --out references.bib
literature.py download-pdf --in results.json --dir pdfs [--timeout 60]
```

`enrich` stores OpenAlex counts as `citation_sources.openalex = {count, retrieved_at, id}`.
Counts from different platforms are **not summed** — they disagree, and the number must stay
traceable to a registry and a date. `download-pdf` fetches only OA links that the APIs expose,
verifies the `%PDF` magic bytes, and writes a manifest.

## author-search

```
literature.py author-search --author "Aerts HJWL" [--affiliation "Harvard Medical School"] \
    [--dates "2020/01/01:2026/11/01"] [--max 20] [--out author.json]
```

Prints total matches, year distribution and the newest records. Disambiguate homonyms with
affiliation, co-authors and topic before attributing papers to a person; prefer ORCID or
`[auid]` when the identity matters.
