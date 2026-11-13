# Evals

These are behaviour tests for the skill, not unit tests for the code (those live in
`../tests/`). Each case is a realistic request that should produce a specific, checkable
outcome.

## How to run

1. Snapshot the current skill: `cp -r literature-analysis /tmp/skill-current`.
2. For each case, start a **fresh session** (no leftover context) and send the prompt.
3. Run the same prompt in a session without the skill (or with the previous version) as the
   baseline.
4. Grade every assertion from the case against the actual outputs and the transcript:
   PASS only with concrete evidence. A section that merely has the right heading does not pass.
5. Record `pass_rate` per configuration and the delta. A skill that raises the pass rate but
   triples the tokens is a different trade-off than one that is both better and cheaper.

Network-dependent cases are marked `"network": true`; run them only when the APIs are
reachable, and record the date.

## Current baseline (2026-11-13)

Not yet collected. The 1.x version was not evaluated with this harness, so the only recorded
evidence is the unit-test suite (66 tests) plus the manual smoke tests described in the
CHANGELOG. Treat the skill as `needs-verification` until the first eval pass is recorded.

## Why these cases

| Case | What it protects against |
|---|---|
| 1 | Skipping hit-count validation; inventing records; screening without reasons |
| 2 | Citing a fabricated DOI; confusing "DOI exists" with "paper supports the claim" |
| 3 | Retyping PRISMA numbers; presenting an incomplete screening as final |
| 4 | Silently merging different studies; failing to dedupe CJK titles |
| 5 | "Reinstall everything" instead of diagnosing a rate limit |
| 6 | Retyping citations; duplicate BibTeX keys |
| 7 | Following instructions embedded in retrieved text (prompt injection) |
