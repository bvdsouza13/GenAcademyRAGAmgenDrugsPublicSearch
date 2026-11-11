# Bulk library and global content search — release verification

Date: 2026-11-11. This report supersedes the earlier manual-review pilot reports for the current workflow. Release verification is in progress; completed observations are distinguished from pending checks below.

## Delivered behavior

- **Search & Learn:** explicit global body-text/heading/name search, grouped medicine/document results, optional filters, exact source excerpts, per-passage PDF page actions and source-scoped learning. Result-origin conversations, quizzes and re-explanation retain their library version across activation.
- **Admin:** multi-PDF batch import and one full-library build/update action. A persistent source registry prevents missing files or learner filters from silently shrinking the collection. Imports validate identity, preserve replacements, skip duplicates and name the failing file. New builds use automatic extraction/source checks without writing human acceptance decisions.
- **Chunk experiments:** local preview, size/overlap controls, Test settings, measured side-by-side comparisons, Use this configuration, Reset defaults, Restore current settings and full-library revert. Reset has no provider or activation side effects. Long comparisons display one selected question at a time.
- **Migration:** existing reviews, pilot manifests/namespaces and citation snapshots are retained. Legacy recovery is separately available through `?legacy=1`. New bulk publication requires complete character coverage, every remote record and document search scope, matching local search artifact and pinned XML/source metadata validation.

## Source and live library evidence

The canonical XML remains `XML/AmgenProducts.xml`, SHA-256 `94dfcc3aea57dfab6f2cf6df57d01d8655bcca0d0ac60784c0099e74b01df572`.

| Observation | Verified result |
|---|---:|
| Supplied PDFs / medicine identities | 37 / 36 |
| Physical PDF pages | 1,439 |
| Archived readable characters covered | 3,398,430 / 3,398,430 |
| Missing intervals / excluded chunks | 0 / 0 |
| Active baseline records at 600/80 | 9,110 |
| Provider-reported baseline embedding usage | 2,693,514 tokens |

Baseline run: `fac1a4e52d6904672ccf1882b520b83beaef77bf581aa729b5d7461e5bb110a6`. All records were fetched and matched to local immutable records; every document scope passed search visibility before activation. The configured citation prefix produces 9,110 chunks; an earlier audit using the shorter default prefix produced 8,854. Neither count is a coverage score.

Source validation separately verified 37 PDF hashes, 1,439 exact page-text round trips, the complete inventory and structural XSD. No OCR or clinical sign-off is claimed.

## Regression evidence

- Full suite: **349 tests passed plus 21 subtests**.
- Randomized full suite, seed `271828`, with socket connections blocked: **349 tests plus 21 subtests passed; zero network attempts**.
- Five upstream PyMuPDF/SWIG deprecation warnings remain nonfailing.
- New tests cover empty review storage, gap/Unicode/continuation coverage, immutable metadata, source replacement/import atomicity, deleted-source restoration, complete build/retry/failure preservation, source artifact tampering, global aliases/body search/variant separation, pinned chat/quiz/re-explanation, reset/revert, controlled evaluation denominators, source-update suite rebinding and actionable safe errors.
- UI AppTests exercise actual Streamlit forms/buttons/reruns. Historical navigation tests use the explicit legacy route rather than weakening their review/publication assertions.

The [independent review](bulk-refactor-independent-review.md) found no critical defects. Its actionable findings were reproduced and fixed with regression tests. Additional peer review fixed coordinate-based deduplication and existing-artifact checksum rebinding. No identified review finding was intentionally deferred.

## Live search and teaching

Pinecone and OpenAI connectivity/model access checks passed. Four explicit live searches passed: `ACTIMMUNE`, `latex`, `storage temperature`, and `interferons bind`. Each returned 20 hits with verified local source citations and no degraded-mode notice. Both Repatha variants remained discoverable. Observed search latency was approximately 1.1–1.6 seconds for these checks; this is not a load test.

Three scoped teaching checks returned citations. ACTIMMUNE and Repatha produced generated explanations that passed the existing citation/entailment validation. Tezspire returned an explicitly labeled source excerpt because retrieved text carried an extraction/layout limitation; no unsupported explanation was generated. Observed times were about 9.4, 8.5 and 1.1 seconds respectively. These observations do not establish clinical accuracy across the corpus.

Raw local smoke output: `output/bulk-live-check.json` (ignored runtime artifact). Reproduce explicitly with `python scripts/live_library_check.py --chat`; this uses provider APIs.

## Chunk comparison and release completion

A separate 900/80 full-library candidate and the source-bound saved-question comparison are running. The baseline remains active. Final measured scores, activate/revert verification, clean-checkout/remote CI and publication status will be recorded here before completion.

The evaluation suite includes 37 source-linked mechanism fixtures, five global discovery queries and 13 retained behavioral fixtures. The 42 retrieval cases use equal evidence budgets and alternating evaluation order. Behavioral cases remain separate regression checks, not unearned generated-answer accuracy scores. Source updates materialize a new pinned suite: unique exact quotations may be rebound, unavailable expectations remain zero-coverage cases, and new documents receive source-bound coverage cases.

## Documentation and operating limits

README, product/technical design, setup/Pinecone instructions, architecture, demo, evaluation notes and roadmap were refreshed. Architecture, data-flow and deployment diagrams have editable Mermaid/renderer sources and regenerated SVG/PNG outputs. Historical reports are marked as such.

This remains a local educational application. The Admin view is not server-side authorization. OCR, clinical review, hosted multi-user isolation, load testing and lifecycle cleanup of retained namespaces are future work. Retained versions consume storage; reset/revert does not delete them. Credentials remain in ignored local secrets/environment variables; no `.env` loader was introduced.
