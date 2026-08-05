---
name: pubmed-live
description: Real-time PubMed literature search and abstract retrieval via the NCBI E-utilities API. Use when the user asks to search, look up, or retrieve PubMed/MEDLINE biomedical literature, abstracts, PMIDs, or citations while writing or revising a manuscript, review, grant, or article; when enriching writing with current, citable references; or when the user asks for live/real-time literature retrieval.
---

# PubMed Live Search

## Core workflow

1. Run `scripts/pubmed.py` with Python 3 (stdlib only; works with the Codex bundled runtime or any system Python).
2. Use `search` to find literature, then `fetch` by PMID for full metadata and abstracts (or pass `--abstracts` to search).
3. Ground every literature claim in real results: keep the returned PMID/DOI and quote only actual titles, authors, and abstracts. Never invent or guess records.

## Commands

```powershell
python scripts/pubmed.py search "radiomics lung cancer prognosis" --max 10 --sort relevance
python scripts/pubmed.py search "federated learning medical imaging" --from 2023/01/01 --to 2025/12/31 --max 20
python scripts/pubmed.py search "artificial intelligence" --sort pub_date --max 30
python scripts/pubmed.py fetch 28418006 40181378
```

## Notes

- Output is JSON (pmid, title, authors, journal, pubDate, volume/issue/pages, doi, pmcId, abstract); pass `--format text` for a compact listing.
- NCBI allows roughly 3 requests/second without an API key; the script paces itself. Optionally set an NCBI API key later for 10 requests/second.
- The database is live: searches hit NCBI in real time, so coverage includes the newest records (verified through 2026-08). Use `--sort pub_date --max 30` to surface the most recent literature; `--from/--to` filters by publication date and re-checks each returned record.
- PubMed includes "epub ahead of print" records whose official issue date can be months in the future; sort by pub_date may therefore show upcoming-issue dates before regular 2026 records.
- Empty results usually mean the query or date filter is too narrow: broaden terms or drop filters before concluding anything.
- When building a reference list, export the returned DOI/PMID metadata instead of retyping citations.
- For a full topic pipeline (multi-query search, merge/dedupe, standard overview table, screening), use the `literature-analysis` skill; this skill provides the underlying real-time retrieval.
- Queries follow native PubMed syntax, so field tags (`[tiab]`, `[Mesh]`, `[dp]`, `[pt]`), Boolean operators, and quoted phrases all work; the `literature-analysis` skill can auto-generate validated PubMed-syntax queries from a topic.
