# Evaluation and historical pilot evidence

The evaluation contract separates global discovery from source-scoped teaching. Current verification outcomes are recorded in the [bulk-refactor release report](../docs/implementation/bulk-refactor-release-report.md); a test fixture's existence does not mean its live evaluation has been run.

`questions.jsonl` retains the 50 provenance fixtures: one mechanism question per supplied PDF plus scope, safety, missing-evidence, qualifier and source-instruction cases. These support source integrity and regression testing. Global cases additionally need name-free content queries with expected documents and exact quotes/spans. Expected evidence is independent of a chunk configuration's IDs.

Evaluation materializes a source-bound suite for the selected collection. When source documents change, original fixture literal quotes are rebound only when the exact quote occurs uniquely in the same document. Missing or ambiguous expected evidence stays in the coverage denominator with zero quote coverage and an explicit warning; it is not dropped to improve a score. Newly added documents receive automatically source-bound coverage cases, clearly labeled as coverage fixtures rather than clinical evaluations. The materialized suite binds the template hash, XML identity, binding version and cases, and is saved under `data/evaluation-suites/<suite-hash>.json`. Both chunk configurations use that same saved suite. Updating sources still requires updating the active full-library baseline before comparing settings.

A controlled chunk experiment pins the PDF/XML version, complete inventory, eligibility policy/fingerprint, question-suite hash, embedding profile, search/ranking version, retrieval settings and equal evidence budget. Only chunk configuration varies. Source changes or mismatched contracts make the comparison unavailable. A full-library active baseline is required; the historical pilot is not a comparable full-library baseline.

| Measurement | Meaning |
|---|---|
| Expected-document Recall@k and reciprocal rank | Whether discovery retrieves expected sources and how early |
| Expected quote/span coverage | Unique expected source intervals covered under an equal evidence budget |
| Searchable coverage/exclusions | Which registered sources and readable page intervals actually entered the run |
| Citation/scope checks | Whether source pages resolve and medicines/documents remain isolated |
| Observed latency | Recorded elapsed time, with cold/warm conditions identified |
| Provider-reported usage | Actual returned usage; absence remains unavailable rather than estimated as zero |
| Optional generated-answer checks | Citation/claim support, separately labeled from retrieval measures |

Overlapping text, chunk counts, source-block touches and raw similarity scores cannot substitute for expected-span coverage or clinical accuracy. Evaluation runs on explicit submission and may consume provider usage; rerendering does not rerun it.

`pilot-live.json` and `pilot-report.md` are **historical, superseded for current workflow and coverage claims**. They record a small manual-source-fidelity pilot involving four mechanism passages across Aimovig, Tezspire and the two Repatha sources. Preserve their original observations; they are not a new full-library build, a clinician-reviewed answer evaluation or proof that supplied labels are current. New bulk verification does not manufacture individual human approvals.

Offline checks use fake providers and require no keys. Authenticated connection, retrieval and generation checks remain explicit; consult the current script help before making provider requests.
