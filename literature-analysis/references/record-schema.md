# Record schema

Every command reads and writes the same JSON record, so any source can feed any later step.
A file may be a JSON list, a JSON object wrapping `records` / `results` / `data` / `items` /
`works`, or JSON Lines (one record per line). Field access is tolerant: missing means empty.

## Fields

| Field | Type | Meaning |
|---|---|---|
| `id` | string | Provider id (OpenAlex/S2/arXiv). Not a DOI. |
| `source_platform` | string | Which platform returned this copy: `pubmed`, `openalex`, `crossref`, `arxiv`, `semanticscholar`, `europepmc`, `doaj`, `hal`, or a browser engine id. |
| `sources` | string[] | All platforms that returned this paper after dedupe (filled by merge). |
| `title` | string | Title exactly as returned. Never retyped. |
| `authors` | string[] | `"Last FM"` order (PubMed convention) for PubMed; display names otherwise. |
| `journal` | string | Journal / container title. |
| `pubDate` | string | Publication date as returned (`"2026 Aug 5"`, `"2025-04-03"`, `"2025"`). Do not normalise by hand. |
| `year` | number | Four-digit year when the provider gives one separately. |
| `volume`, `issue`, `pages` | string | Bibliographic details. |
| `doi` | string | Canonical DOI: bare `10.x/...`, lowercase, no `https://doi.org/`. |
| `pmid` | string | PubMed id; empty for sources that do not supply one. |
| `pmcId` | string | PMC id when available (open full text). |
| `abstract` | string | Plain text, HTML/JATS tags stripped, section labels kept (`BACKGROUND: …`). |
| `url` | string | Landing page. |
| `snippet` | string | Short excerpt used by scan tables when no abstract exists. |
| `query` | string | The query that produced this record (set per record by the searcher). |
| `citation_count` | number | Citation count from the platform named in `citation_sources`. |
| `citation_sources` | object | `{"openalex": {"count": 42, "retrieved_at": "2026-11-13T05:00:00Z", "id": "W…"}}`. **Counts are never summed across platforms.** |
| `oa_status` | string | OpenAlex OA status (`gold`, `hybrid`, `green`, `closed`). |
| `oa_pdf_url` | string | Direct OA PDF link when the platform exposes one. |
| `full_text_status` | string | `open_pdf` / `oa_available` / `no_open_pdf`. |
| `dedupe_basis` | string | Set to `title` when a record was merged without an identifier; such merges need human review. |

## Normalisation rules (single source of truth: `scripts/lit_common.py`)

- **DOI** — unquote, strip `https://doi.org/`, `dx.doi.org`, `doi:`, trailing `.`/`,`/`;`
  and whitespace; lowercase. A value that does not match `10.\d{4,9}/…` becomes empty so it
  cannot become a bogus dedupe key.
- **PMID** — digits only; `PMID: 123` is accepted and normalised to `123`.
- **Title** — Unicode NFKC, lowercase, tags removed, all non-alphanumeric replaced with a
  space, whitespace collapsed. CJK characters are preserved.
- **Identity** — DOI → PMID → provider id. Title is used only when no identifier exists, and
  such merges are flagged. Two records with *different* identifiers and the same title are
  reported as review candidates, never merged automatically.
- **Year** — read from `year`, `publication_year`, `pubDate`, `published` or `issued`; the
  first four-digit year wins.

## Screening decisions (input to `prisma`)

CSV (UTF-8 with BOM is fine) or JSON. Column names are case-insensitive; extra columns are
ignored.

| Column | Required | Values |
|---|---|---|
| `doi` / `pmid` / `title` | at least one | Used to match the decision to a record. |
| `decision` | yes | `include`, `exclude`, `uncertain` (also accepted: `included`, `yes`, `纳入`, `排除`, …). Anything unrecognised becomes `uncertain` — never a silent exclusion. |
| `reason` | recommended | Free text; counted verbatim in the PRISMA exclusion table. |
| `stage` | optional | `title_abstract` (default) or `full_text`. |

## PRISMA counts (output of `prisma`)

`prisma.json` contains `identified`, `per_source`, `duplicates_removed`, `screened`,
`included`, `excluded`, `uncertain`, `undecided`, `exclusion_reasons`, `decisions_supplied`,
`decisions_unmatched`, `complete`, plus capped lists for audit. `complete` is false while any
record has no decision or any decision matches no record — do not paste an incomplete flow into
a manuscript.

`records ≠ reports ≠ studies`: one study can produce several reports (preprint, journal
article, follow-up). Deduplication removes duplicate *search hits*; it does not decide that two
reports describe the same study. Link those by trial registration, cohort, site and enrolment
period, and record the link explicitly.
