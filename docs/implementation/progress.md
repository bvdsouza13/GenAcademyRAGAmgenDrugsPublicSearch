> Historical pilot report. Current bulk-library behavior and release evidence are in [the bulk refactor release report](bulk-refactor-release-report.md). Original observations below are retained for traceability.

# SDD ledger — plan: docs/superpowers/plans/2026-11-11-amgen-medicine-explorer.md

Implementation authorized by user; build full app and tests, start with live connectivity. Credentials now saved; two unquoted strings fixed locally, no values logged.

Ruling: work in the supplied non-git workspace, retaining snapshots — no repository/worktree exists; avoid inventing a version-control workflow.
Ruling: parallel workers use distinct owned files and shared contracts — developer asks proactive delegation; root owns integration and dependency installation.

| Plan checks | Result |
|---|---|
| Task 1 within task | Preserve raw text; schema validates structure, not clinical content |
| Task 2 within task | Accepted raw passage distinct from normalized facts; token cap enforced |
| Task 3 within task | Staging and publication separate, persistent IDs and jobs |
| Task 4 within task | Product scoped cited answers; evaluation review status explicit |
| Task 5 within task | Streamlit mandated; reuse mockups with native widgets |
| Task 6 within task | Report live failures honestly; clinical broad release requires reviews |
| 1→2→3 | Shared dataclasses; hash-bound review→chunk fingerprint→manifest |
| 3→4 | Active namespace and XML hash pinned for each answer |
| 1/2/3/4→5 | Root facade isolates UI from providers, contracts.md authoritative |
| All→6 | Root integration suite and independent code review after worker tests |

## Completed implementation and verification

- Tasks 1–2: reusable lossless extraction, local structural XSD/tag guide, atomic snapshots, hash-bound SQLite review, section/sentence chunking and exclusions implemented. Corpus report records 37 PDFs /36 products /1439 pages /4634 archived/candidate blocks.
- Tasks 3–4: authenticated provider checks, deterministic staged ingestion, checkpoints/locks, fetch+search verification, publication/rollback, scoped retrieval, quoted citations, entailment checks, extractive fallback and quiz implemented. Services report records fake-provider evidence and explicit limitations.
- Task 5: branded Streamlit Explore/Learn/My learning/Manage sources implemented, source PDF rendering, saved chunk presets, comparison and explicit publication. UI report records AppTest and visual checks.
- Task 6: local server running on127.0.0.1:8501; 4 source-fidelity-reviewed MOA passages produce6 published chunks. All four live source-specific teaching checks returned supported cited answers. Alternate900/80 configuration produced5 chunks; live compare, publication and rollback succeeded.
- Final independent review: one Important stale PDF-image-cache identity finding. Fix wave binds document/XML/page/PDF hash, with7 focused regressions. Scoped re-review accepted; no remaining Critical/Important findings within limited-pilot scope.
- Final offline verification: `python scripts/test_features.py all` → **145 passed,21 subtests passed**; five pre-existing PyMuPDF SWIG deprecation warnings only. `build_amgen_xml.py --validate-only` passed; local health HTTP200. Source/manifest/report credential-value scan found no leaked values.

Ruling: use the user's existing ready `amgenproduct` index and immutable END profile, with an independent UTF-8-byte+8 ≤2048 guard on every uploaded/query text — avoids creating a second paid index; a confirmed exact tokenizer could permit larger chunks later.
Ruling: use conservative byte-based token bounds and disclose them rather than assert unverified hosted-tokenizer parity — retrieval chunks are smaller; optional hash-pinned local tokenizer remains subject to the same hard guard.
Ruling: publish a narrow assistant source-fidelity pilot, not an unreviewed entire label corpus — user gets working examples now; broader learning requires curator review, particularly indications/safety/tables.

Remaining domain/deployment limits (not hidden feature claims): most passages unreviewed; no OCR; broad semantic/clinical50-case review pending; no public hosting/auth. Narrow/mobile visual and full accessibility audit not completed. Live latency/usage observations are small samples, not performance guarantees. No git repository or public deployment created.

Final source-validation followup: `--validate-only` now compares the current full PDF inventory,37 PDF SHA-256 values and1439 exact page text streams with the canonical XML, read-only. Two additional regressions pass; independent scoped review accepted. Canonical XML and approved review scopes unchanged.
