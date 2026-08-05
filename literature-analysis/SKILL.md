---
name: literature-analysis
description: Analyze PubMed literature with precision, extracting user-defined information fields from abstracts (study design, sample size, modality, methods, validation, performance, limitations, or any custom field), and screen/select papers against user-defined inclusion/exclusion criteria based on abstract evidence. Use when the user asks to analyze, extract, compare, triage, or shortlist retrieved literature; build literature comparison tables; or select which papers to read/cite from a set of PubMed records or abstracts.
---

# Literature Analysis & Screening

## Workflow

### Step 0 - Turn the topic into a high-recall search strategy

Break the user's topic into concepts (disease/population, intervention/exposure, outcome, modality where applicable), then build PubMed-syntax query variants. Generate them automatically when possible:

```powershell
python scripts/literature.py strategy --concepts "radiomics|lung cancer|prognosis" --dates "2023/01/01:2026/08/05" --test --out queries.txt
```

`strategy` looks up MeSH descriptors for each concept, builds three variants (MeSH-only, [tiab]-only, hybrid MeSH OR [tiab]), optionally adds a `[dp]` date range, prints per-variant hit counts, and flags zero-result or invalid variants. Review the descriptors it picked (e.g., drop `Small Cell Lung Carcinoma` if small-cell is out of scope). Then feed the file to `search-all`:

```powershell
python scripts/literature.py search-all --queries-file queries.txt --max 15 --out results.json
```

For multi-database automation, `strategy` now generates native query variants for every platform at once, and `translate` converts a raw query into each platform's syntax - no manual per-database query writing:

```powershell
# Generate + test the full multi-platform strategy (MeSH/[tiab] for PubMed, field syntax for arXiv/Europe PMC, quoted terms for OpenAlex/Crossref/DOAJ/HAL/S2)
python scripts/literature.py strategy --concepts "radiomics|lung cancer|prognosis" --sources pubmed,openalex,crossref,arxiv,semanticscholar,europepmc,doaj,hal --dates "2023/01/01:2026/08/05" --test --strategy-out strategy.json

# Just show the converted queries (optionally with hit counts)
python scripts/literature.py translate --concepts "radiomics|lung cancer|prognosis" --sources pubmed,arxiv,europepmc --dates "2023/01/01:2026/08/05" --test

# Run the strategy across all platforms and merge
python scripts/literature.py search-multi --strategy-file strategy.json --max 15 --out results.json
```

Platform-native conversions handled automatically: PubMed `[Mesh]/[tiab]/[dp]`, arXiv `all:"..." AND submittedDate:[...]`, Europe PMC `(...) AND PUB_YEAR:[...]`, OpenAlex/Crossref/DOAJ/HAL/Semantic Scholar quoted-term queries with their own date parameters.

## PubMed syntax rules (mandatory when hand-writing queries)

- Boolean: `AND`, `OR`, `NOT` uppercase, spaced, parentheses for grouping: `(a OR b) AND c`.
- Field tags: `[tiab]` title/abstract, `[Mesh]` MeSH descriptor (exploded automatically), `[Majr]` major topic, `[dp]` publication date, `[pt]` publication type, `[la]` language, `[ta]` journal, `[au]` author, `[ad]` affiliation.
- Phrases: quote multi-word terms: `"lung cancer"[tiab]`.
- Dates: `"2023/01/01"[dp] : "2026/08/05"[dp]` (inclusive range).
- Publication types: append `AND review[pt]`, `AND meta-analysis[pt]`, or `NOT review[pt]` to shape the set.
- Truncation: `*` stem wildcard (`radiom*[tiab]`) widens recall but adds noise; use deliberately.
- Validation: test every variant's hit count; a variant with zero hits usually means a typo, wrong tag, or too-narrow field. Never ship an untested query.
- Precision vs recall: MeSH (explosion + synonyms) maximizes recall; `[tiab]` with quoted phrases maximizes precision; hybrids balance both.

Manual example for "radiomics and lung cancer prognosis":

```text
("Radiomics"[Mesh] OR "radiomics"[tiab]) AND ("Lung Neoplasms"[Mesh] OR "lung cancer"[tiab] OR "NSCLC"[tiab]) AND ("Prognosis"[Mesh] OR "prognosis"[tiab] OR "survival"[tiab]) AND ("2023/01/01"[dp] : "2026/08/05"[dp])
```

### Step 1 - Search and merge (find them all)

Run all variants and merge/deduplicate by PMID:

```powershell
python scripts/literature.py search-all --queries-file queries.txt --max 15 --out results.json
```

`search-all` reports per-query hit counts and the final unique record count. If the user wants to limit the table to the newest work, add date-filtered variants (e.g. `--from 2023/01/01 --to 2026/08/05` inside each query via pubmed-live syntax) or filter afterward.

### Multi-source search (PubMed + OpenAlex + Crossref)

For broader coverage, search several sources at once and merge by DOI/title. Each platform has its own query syntax; `search-multi` translates the topic per platform and prints the exact query it used:

```powershell
python scripts/literature.py search-multi --query "radiomics lung cancer prognosis" --sources pubmed,openalex,crossref,arxiv,semanticscholar,europepmc,doaj,hal --max 10 --from 2023/01/01 --to 2026/08/05 --sort citations --out results.json
```

- `--sources` selects any of: `pubmed` (Boolean/MeSH/[tiab]/[dp]), `openalex` (search + from/to_publication_date filters), `crossref` (query.bibliographic + from/until-pub-date), `arxiv` (all:"..." AND submittedDate:[... TO ...]), `semanticscholar` (query; rate-limited without API key, may return 0), `europepmc` (query AND PUB_YEAR:[... TO ...]), `doaj` (fielded search; year filtered client-side), `hal` (q + producedDate_s). Unavailable sources fail gracefully and report why.
- OpenAlex records carry `citation_count`, `oa_status`, `oa_pdf_url`, and `full_text_status`; Crossref/Europe PMC carry citation or OA data where available.
- Full-text search on OpenAlex/Crossref/DOAJ is broader but noisier than PubMed `[tiab]`: expect off-topic hits (e.g., cancer statistics, other diseases) and screen them out in Step 3.
- Follow the two-pass strategy: first run `lite` for a compact scan table, let the user pick core papers, then run `overview` for the deep evidence-anchored extraction:

  ```powershell
  python scripts/literature.py lite --in results.json
  ```

### Platforms without open APIs (browser-assisted)

Google Scholar, CNKI (知网), Wanfang (万方), VIP/中华医学期刊, CiNii/NDL (日本), eLibrary (俄罗斯) have no public bulk API or are anti-bot/login-gated. Do not fake their coverage:

- Use them only through the in-app browser or a user-authenticated session, for verification and specific lookups (e.g., CNKI 机构下载 via the `nature-downloader` skill).
- For language coverage in bulk, rely on OpenAlex/Crossref/DOAJ, which index many Chinese, Japanese, German, French, and Russian journals with original-language titles and abstracts.
- If the user explicitly asks for one of these platforms, say which ones are browser-only and route through the browser instead of claiming API results.

### Unified browser-search command

One command searches those browser-only platforms and converts results into the standard pipeline:

```powershell
# Bing (no login, generic fallback)
python scripts/literature.py browser-search --engine bing --query "radiomics lung cancer" --max 20 --out browser.json

# Google Scholar (may hit CAPTCHA)
python scripts/literature.py browser-search --engine google-scholar --query "radiomics lung cancer prognosis" --max 20 --out gs.json

# CNKI / Wanfang / VIP (need login once in the CDP Chrome window)
python scripts/literature.py browser-search --engine cnki --query "肺结节 AI 诊断" --max 20 --out cnki.json

# Print the URL without driving the browser
python scripts/literature.py browser-search --engine cnki --query "肺结节" --print-url
```

Requirements: Chrome started with `--remote-debugging-port=9222 --user-data-dir="D:\chrome-cdp"` (see `references/browser-patterns.md`), Node.js 22+. If CDP is unavailable or a site blocks automation, use the in-app browser fallback documented in `references/browser-patterns.md`; results saved as standard JSON still merge into `extract` / `overview`.

### Directed search - a specific author or institution

Find everything by a specific author, optionally restricted to an institution:

```powershell
python scripts/literature.py author-search --author "Aerts HJWL" --affiliation "Harvard Medical School" --dates "2020/01/01:2026/08/05" --max 20 --out author_results.json
```

Rules and pitfalls:

- `[au]` uses "Last FM" format; try initial variants when a name has multiple forms (e.g., `Zhang Y` vs `Zhang YC`).
- `[ad]` is free text - combine institution with city when needed (`"Fudan University"[ad] AND "Shanghai"[ad]`), because the same person may list departments differently.
- For unambiguous identity, prefer the Author Identifier (`[auid]`) or ORCID when the user provides one.
- Same-name authors are common: verify that returned records actually belong to the person (co-authors, department, topic) before citing.
- The saved JSON feeds the same `overview` / screening pipeline.

### Step 2 - Build the standard overview table

Generate the fixed comprehensive schema (study design, population, sample size, modality/data, method/model, validation, performance metrics, main findings, limitations, evidence level, topic relevance, decision, reason, evidence), auto-filled from the abstracts in one shot:

```powershell
python scripts/literature.py extract --in results.json --out overview.csv --xlsx overview.xlsx --topic "radiomics lung cancer prognosis" --include "external validation|prospective" --exclude "review|animal|editorial"
```

`extract` fills every column in one shot:

- Study-design / population / sample-size / modality / method / validation / performance / findings / limitations / evidence-level cells come from rule-based extraction of the abstract (and title). It never invents values: anything not found is marked `Not stated`.
- `topic relevance` is scored by token overlap between the topic (or the query stored in the results) and title+abstract: High >= 0.7, Medium >= 0.4, else Low.
- `decision` and `reason` follow the criteria: `--exclude` keywords exclude; `--include` keywords are required for inclusion; without criteria, Low relevance or missing abstracts are excluded/uncertain, and the reason states the basis.

Then run the agent quality-assurance pass - review and refine every cell **only from the abstract text**, with these precision rules:

- Write `未提及 / Not stated` when the abstract does not mention a field. Never infer, estimate, or impute numbers.
- Put the verbatim supporting phrase in the `evidence` column for every filled cell (e.g., `"112 patients (mean age 75 years)"` for sample size).
- Keep original numbers, units, and confidence intervals; distinguish reported results from author interpretation.
- Score `topic relevance` as High / Medium / Low based on how directly the paper matches the user's topic (state the reason).
- Assign `evidence level` for biomedical work using this scale (state the reason):
  1 clinical guideline; 2 systematic review / meta-analysis; 3 randomized controlled trial; 4 prospective cohort with external validation; 5 retrospective study with external validation; 6 retrospective study with internal validation only; 7 cross-sectional / case-control / case series; 8 narrative review / opinion / preprint. Mark `unclear` when the abstract is insufficient.
- Heuristic extraction can misread tricky abstracts (e.g., a random train/test split is not an RCT; "necessitating prospective trials" does not make a study prospective). Fix these during the QA pass; do not let the rules override a careful reading.

For custom fields instead of the default schema, use:

```powershell
python scripts/literature.py template --in results.json --out template.csv --fields "sample size,imaging modality,external validation,AUC,main finding"
```

### Step 3 - Screen precisely

Apply the user's inclusion/exclusion criteria abstract by abstract:

- Decision: `include` / `exclude` / `uncertain`.
- `uncertain` when the abstract lacks the key information (e.g., no external validation mentioned) - do not guess.
- Always record the `reason` and the verbatim `evidence` phrase.
- Keyword triage is only a first pass:

  ```powershell
  python scripts/literature.py screen --in results.json --out triage.csv --include "external validation|prospective" --exclude "review|animal|editorial"
  ```

  Re-verify every row semantically; keyword results may be wrong.

### Step 4 - Deliver

Deliver the completed overview table (CSV, Excel via the spreadsheets skill, or Markdown) plus the screened shortlist with PMID/DOI for citation. Report how many records were found, how many were included/excluded/uncertain, and why. Never add records not in the source set; never change PMIDs, titles, or numbers.

## Output conventions

- CSV files are written with UTF-8 BOM so they open correctly in Excel with Chinese text.
- Keep the evidence column in every deliverable; a table without evidence quotes is not precise enough to use in a manuscript.
- When the user later writes the manuscript, reuse the shortlist's PMID/DOI instead of re-typing references.

### Step 5 - Enrich and export

Add cross-source impact and open-access information from OpenAlex (citation counts, OA status, OA PDF link), then export references:

```powershell
python scripts/literature.py enrich --in results.json --out enriched.json
python scripts/literature.py overview --in enriched.json --out overview_enriched.csv --xlsx overview_enriched.xlsx
python scripts/literature.py export --in enriched.json --out references.bib
python scripts/literature.py export --in enriched.json --format ris --out references.ris
```

- `enrich` matches records by DOI; records without a DOI stay unenriched and are reported.
- Citation counts come from OpenAlex (mirrors Semantic Scholar coverage for most venues); OA status is gold/green/hybrid/bronze/closed.
- BibTeX keeps PubMed author strings verbatim (compound surnames and suffixes like `Jr` are not rewritten).
- `--xlsx` also writes a formatted Excel workbook (bold header, frozen top row, autofilter).

### Step 6 - Batch-download open-access PDFs

```powershell
python scripts/literature.py download-pdf --in results.json --dir pdfs --timeout 40
```

- Downloads only records with a legal OA PDF link (`oa_pdf_url` from OpenAlex/arXiv/HAL/Europe PMC); never bypasses paywalls.
- Verifies the `%PDF` magic bytes, removes non-PDF pages, and writes `download_manifest.csv` (downloaded / skipped_no_open_pdf / failed / not_pdf) so every record's full-text status is auditable.
