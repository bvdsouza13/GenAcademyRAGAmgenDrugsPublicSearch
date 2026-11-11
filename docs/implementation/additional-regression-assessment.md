> Historical pilot report. Current bulk-library behavior and release evidence are in [the bulk refactor release report](bulk-refactor-release-report.md). Original observations below are retained for traceability.

# Additional regression assessment — 2026-11-11

Engineering confidence: **8/10 for the current local, single-user educational pilot**. This is a judgment based on the tested behavior and source protections; it is not a measured availability or clinical-accuracy percentage. Shared/public hosting and clinical production use remain outside the validated scope.

## New regression coverage

The complete offline suite now passes **250 tests and 21 subtests**, up from 190 tests. The 60 added cases are:

| Area | Added cases | Coverage |
|---|---:|---|
| Indexing and transport | 22 | Wrong saved-run identities; 408/429/503 and permanent errors; bounded retries; partial response/status failures; interrupted-load resume; lock release; failed atomic publication; corrupt SQLite/JSON. |
| Corpus and chunks | 15 | Source replacement during extraction; unrecognized headings; exact span coverage; seeded Unicode/whitespace/quotes; overlap and determinism; byte limits; mixed filenames, blank pages and ID collisions. |
| Evidence and provider envelopes | 15 | Malformed generation responses; preserving source fallback; file replacement between verification and download/render/snapshot; XML identity changes before snapshot. |
| UI navigation and sessions | 8 | Quiz answer persistence; medicine/document isolation; citations and progress; reruns after failures; quiz replacement; independent sessions; demo exit/reentry/restart and missing sources. |

The five existing PyMuPDF SWIG deprecation warnings remain. New failure scenarios use synthetic files, temporary storage and fake providers. They do not alter the real source documents, review decisions, active namespace or published corpus.

The complete suite also passed with shuffled test order (seed `271828`) and socket connections blocked: **250 tests, 21 subtests, zero attempted connections**. This checks for some test/session state leaks without depending on provider availability. Compilation and whitespace checks passed.

The real corpus still validates against all **37 PDF hashes and 1,439 physical-page text round trips**; the canonical XML identity is unchanged. Both provider connection checks passed. Four live source-specific teaching checks returned **four supported answers, four citations and zero abstentions**, with observed elapsed times between **5.457 and 7.411 seconds**. These checks used the existing published pilot and made no indexing or publication changes.

## Defects reproduced and fixed

1. A different valid manifest copied into a saved run's filename could be reused or published. The stored identity must now match the requested run.
2. Truncated HTTP reads and malformed HTTP status lines bypassed normal error handling. They now become sanitized, retryable provider errors.
3. PDF extraction could read text from one file version and hash a later version. Text and hash now come from the same byte snapshot; a changed working source prevents build publication.
4. Highlights-only derived fragments could suppress the remaining page archive when full sections were not recognized. The complete archive now remains eligible in that case.
5. PDF downloads, rendering and snapshots re-read a file after checking its hash. They now use the same verified bytes, and XML snapshots check the plan identity before writing.
6. Malformed OpenAI output items could raise an unhandled attribute error. Explicit envelope checks now preserve the controlled, cited source fallback.
7. Learning and demo quizzes lost their selected answer when Streamlit removed off-screen widget state. Answers now persist separately within their own session and source scope.

Each affected behavior had a failing regression before its fix. An independent review found no critical or important defects in these changes. The full-suite result above was obtained after integration.

## What supports confidence, and what does not

| Area | Assessment | Limits |
|---|---|---|
| Local demo and navigation | High | Automated navigation and session sequences cover the fixes; this pass did not repeat visual testing across browsers or mobile devices. |
| Source identity and chunk integrity | High for tested text-layer PDFs | Exact text and byte bounds are checked. OCR, complex table interpretation and clinical completeness are not established. |
| Upload/recovery/publication | High for tested local persistence invariants | Fault injection verifies preservation and retries. Hard process termination, disk exhaustion, power loss and distributed concurrency still need dedicated testing. |
| Educational explanations | Guarded but not clinically quantified | Closed citations, exact quotes and an entailment check help. The generator and verifier can share failure modes; a clinician-reviewed benchmark is still needed. |
| Shared/public deployment | Not ready | Authentication, role enforcement, durable shared storage, production monitoring and recovery procedures are not implemented. |

The current published pilot has four reviewed mechanism passages: Aimovig, Tezspire and both Repatha documents. The 50 evaluation fixtures are useful test scaffolding, not a completed clinical quality benchmark. A broader catalog does not imply broader reviewed answer coverage.

## Reproduce

```sh
.venv-corpus/bin/python scripts/test_features.py regression
.venv-corpus/bin/python scripts/test_features.py all
.venv-corpus/bin/python scripts/build_amgen_xml.py --validate-only
```

Live checks are explicit and may incur provider charges:

```sh
.venv-corpus/bin/python scripts/check_connections.py
.venv-corpus/bin/python scripts/live_smoke.py --generate --output output/additional-regression-live-smoke.json
```

See the [prioritized future-feature roadmap](../future-features.md) for the next milestones.
