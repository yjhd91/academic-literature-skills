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

Generate the fixed comprehensive schema (study design, population, sample size, modality/data, method/model, validation, performance metrics, main findings, limitations, topic relevance, decision, reason, evidence):

```powershell
python scripts/literature.py overview --in results.json --out overview.csv
```

Then fill every cell **only from the abstract text**, with these precision rules:

- Write `未提及 / Not stated` when the abstract does not mention a field. Never infer, estimate, or impute numbers.
- Put the verbatim supporting phrase in the `evidence` column for every filled cell (e.g., `"112 patients (mean age 75 years)"` for sample size).
- Keep original numbers, units, and confidence intervals; distinguish reported results from author interpretation.
- Score `topic relevance` as High / Medium / Low based on how directly the paper matches the user's topic (state the reason).

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
