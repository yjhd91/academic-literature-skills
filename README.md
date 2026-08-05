# Codex PubMed Literature Skills

Two [Codex](https://openai.com/codex) skills for real-time PubMed retrieval and precise literature analysis:

- **pubmed-live** - real-time PubMed search and abstract retrieval via the NCBI E-utilities API (Python standard library only, no pip packages).
- **literature-analysis** - a topic-to-table pipeline that auto-generates PubMed-syntax query strategies (MeSH + `[tiab]` + Boolean + `[dp]` date ranges), runs multi-query searches with PMID deduplication, builds standard literature-overview tables with verbatim evidence, screens papers against inclusion/exclusion criteria, and supports directed author/institution search.

## Install

Copy each skill folder into your Codex skills directory:

- Windows: `C:\Users\<you>\.codex\skills\`
- macOS / Linux: `~/.codex/skills/`

Start a new Codex conversation (or restart Codex) and the skills are auto-discovered.

## Requirements

- Python 3 (standard library only)
- Network access to `eutils.ncbi.nlm.nih.gov`

## Usage

### pubmed-live

```powershell
python scripts/pubmed.py search "radiomics lung cancer prognosis" --max 10 --sort relevance
python scripts/pubmed.py search "artificial intelligence" --sort pub_date --max 30
python scripts/pubmed.py fetch 28418006 40181378
```

- Queries follow native PubMed syntax: field tags (`[tiab]`, `[Mesh]`, `[dp]`, `[pt]`), Boolean operators, quoted phrases.
- Output is JSON (pmid, title, authors, journal, pubDate, doi, pmcId, abstract); use `--format text` for a compact listing.
- NCBI allows roughly 3 requests/second without an API key; the script paces itself.

### literature-analysis

```powershell
# 1. Build a PubMed-syntax search strategy from topic concepts
python scripts/literature.py strategy --concepts "radiomics|lung cancer|prognosis" --dates "2023/01/01:2026/08/05" --test --out queries.txt

# 2. Run all variants, merge and deduplicate by PMID
python scripts/literature.py search-all --queries-file queries.txt --max 15 --out results.json

# 3. Build the standard overview table (13 fixed columns including evidence)
python scripts/literature.py overview --in results.json --out overview.csv

# 4. Keyword first-pass triage (semantic review is still required)
python scripts/literature.py screen --in results.json --out triage.csv --include "external validation|prospective" --exclude "review|animal|editorial"

# Directed author / institution search
python scripts/literature.py author-search --author "Aerts HJWL" --affiliation "Harvard Medical School" --dates "2020/01/01:2026/08/05" --max 20 --out author_results.json
```

Every extracted cell is filled only from the abstract text with a verbatim evidence quote; missing information is marked `Not stated`, never invented.

## Optional

- Set an [NCBI API key](https://www.ncbi.nlm.nih.gov/account/settings/) (10 requests/second) via `PUBMED_API_KEY` for higher rate limits.
- For native MCP tools, the skills document a `@ncukondo/pubmed-mcp` server configuration inside their `SKILL.md` files.

## License

MIT
