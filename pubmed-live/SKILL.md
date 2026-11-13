---
name: pubmed-live
description: Real-time PubMed literature search and abstract retrieval via the NCBI E-utilities API. Use when the user asks to search, look up, or retrieve PubMed/MEDLINE biomedical literature, abstracts, PMIDs, or citations while writing or revising a manuscript, review, grant, or article; when enriching writing with current, citable references; or when the user asks for live/real-time literature retrieval. Includes strict handling of unknown PMIDs (a missing record is an error, never an empty citation).
license: MIT (see LICENSE at the repository root)
compatibility: Python 3.9+ (standard library only); network access to eutils.ncbi.nlm.nih.gov; NCBI_EMAIL and NCBI_API_KEY are optional but recommended.
metadata:
  version: "2.0.0"
  repository: https://github.com/yjhd91/academic-literature-skills
---

# PubMed Live Search

## Core workflow

1. Run `scripts/pubmed.py` with Python 3 (standard library only; no install step).
2. `search` to find literature, then `fetch` by PMID for full metadata and abstracts.
3. Ground every literature claim in real results: keep the returned PMID/DOI and quote only
   actual titles, authors, and abstracts. Never invent or guess a record.

## Commands

```powershell
python scripts/pubmed.py search "radiomics lung cancer prognosis" --max 10 --sort relevance
python scripts/pubmed.py search "federated learning medical imaging" --from 2023/01/01 --to 2026/11/01 --max 20
python scripts/pubmed.py search "artificial intelligence" --sort pub_date --max 30
python scripts/pubmed.py fetch 28418006 40181378
```

## Output

JSON by default: `pmid, title, authors, journal, pubDate, volume, issue, pages, doi, pmcId,
abstract`. `--format text` prints a compact listing. Records are returned in the order
requested.

## Behaviour you can rely on

- **An unknown PMID is an error, not a record.** `fetch 99999999` prints
  `Unknown PMID(s): 99999999` to stderr and exits 1 when nothing was found. It never emits a
  blank record that could be mistaken for a citation. (This was a real bug before 2.0.0.)
- **NCBI rate limits**: roughly 3 requests/second without a key, 10/second with one. The
  script paces itself; set `NCBI_API_KEY` to use a key. Set `NCBI_EMAIL` to identify yourself
  as NCBI's usage policy asks.
- **Dates**: `--from/--to` filter on the publication date, then each returned record's own
  date is re-checked, because ahead-of-print records can carry a future issue date.
- **Empty results usually mean the query is too narrow** — broaden terms or drop the date
  filter before concluding that nothing exists.
- Queries use native PubMed syntax: `[tiab]`, `[Mesh]`, `[Majr]`, `[dp]`, `[pt]`, `[au]`,
  `[ad]`, `[auid]`, Boolean operators, quoted phrases.

## When to use the sibling skill

For multi-database search, deduplication, screening, reference verification, PRISMA counts and
export, use `literature-analysis`. It contains its own PubMed client, so the two skills can be
installed independently.
