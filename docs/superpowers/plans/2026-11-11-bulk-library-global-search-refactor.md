# Bulk Library and Global Search Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Implementation requires the user's approval of this proposal first.

**Goal:** Load the whole medicine library through one admin workflow, remove individual-review gating for this version, search all document text from home, and make chunk configuration experiments easy to compare and reverse.

**Architecture:** Retain the Streamlit/OpenAI/Pinecone application and its single canonical XML. Introduce a versioned automated source-eligibility policy, complete-library build orchestration, global lexical-plus-semantic discovery, and controlled full-library chunk experiments. Preserve the current immutable manifests, source snapshots, retry/resume and atomic activation mechanisms.

**Tech Stack:** Python 3.12, Streamlit, PyMuPDF, XML/lxml, SQLite, existing Pinecone Documents API profile, OpenAI Responses API, pytest/AppTest. No new cloud service is proposed.

**Spec:** [Bulk library administration and global content search](../specs/2026-11-11-bulk-library-global-search-design.md).

**Status:** Approved; implementation and release verification are underway. See [the release report](../../implementation/bulk-refactor-release-report.md) for measured results.

## Global constraints

- The new policy is `bulk_source_verified_v1`; absent policy markers identify `manual_review_v1` legacy runs.
- Do not convert automatic extraction checks into human `accepted` review decisions.
- Every new build/experiment covers the entire selected source inventory; for the supplied corpus this is 37 documents and 36 products.
- No per-passage approval workflow is required to make readable text searchable.
- Preserve exact PDF/XML hashes, source spans, source variants and citations; never silently truncate or discard text to meet an embedding limit.
- Keep the existing 2,048-unit conservative UTF-8-byte-plus-reserve guard, 1,024-dimension embedding profile and explicit-action provider calls.
- Default chunk controls remain 600/80 in their accurately labeled byte-budget units until evaluation supports another choice.
- Reset changes draft controls only; failure preserves the active library. Publication requires complete coverage plus verified remote and local search artifacts.
- Do not delete existing namespaces, reviews, source files or snapshots during migration or reset.
- Keep credentials out of artifacts, logs, Git and UI. This remains a local application.

## Review focus

1. Empty review storage must not prevent bulk-mode search, and legacy review revocations must still take effect.
2. A table flag, very long Unicode sentence, missing section or new document must not silently reduce searchable coverage.
3. Global results must never mix source identities, reuse stale snippets or open a conversation against the wrong Repatha document.
4. Interrupted builds, local-index failures and repeated clicks must preserve the current complete library and avoid duplicate work.
5. Reset and A/B evaluation must preserve all medicines and keep source/evaluation settings comparable.

## Task 1 — Versioned eligibility and complete coverage

**Files:** Create `amgen_explorer/eligibility.py`; modify `models.py`, `chunking.py`, `indexing.py`, `retrieval.py`, `teaching.py`, `service.py`, `config.py`; add `tests/test_bulk_eligibility.py` and `tests/test_bulk_coverage.py`.

**Interfaces:** `assess_corpus(corpus: Corpus, source_dir: Path, policy: str, reviews: ReviewStore | None = None) -> EligibilityReport`. The report includes eligible span units, limitations, expected document/product inventory, coverage accounting and an eligibility fingerprint. Source-directory access is explicit so configuration overrides do not get replaced by inferred paths. Extend ChunkPlan and manifests with defaulted schema/policy fields for backward compatibility. All evidence consumers use the same policy validator.

- [ ] Write failing tests for an empty review database, legacy review revocation, changed hashes/spans, known layout flags, missing section intervals and oversized Unicode units.
- [ ] Run the new tests and confirm the missing policy/coverage behavior fails.
- [ ] Implement policy dispatch, interval-based nonduplicate coverage, archived-gap fallback and continuation-aware splitting. Keep limitations searchable while constraining unsupported explanations.
- [ ] Update all downstream eligibility gates together; retain legacy validation without relabeling old data.
- [ ] Run new coverage tests plus existing XML/chunk/index/retrieval/teaching/service tests. Assert every expected character interval is accounted for and each chunk respects the byte cap.
- [ ] Independently review and commit the completed unit after approval to implement.

## Task 2 — Global text and semantic discovery

**Files:** Create `amgen_explorer/search.py`; modify `models.py`, `service.py`, `connectivity.py` only as needed for optional search filters; add `tests/test_global_search.py` and `tests/test_search_artifacts.py`.

**Interfaces:** `build_search_artifact(run, records, corpus) -> SearchArtifact`; `ExplorerService.search_library(query: str, *, run_id: str | None = None, product_ids: list[str] | None = None, document_ids: list[str] | None = None, limit: int = 20) -> SearchResults`. Results carry query/run identity, verified hits, group identities, source spans and warnings. Existing scoped `EvidenceBundle` remains distinct.

- [ ] Write failing tests for body-text-only queries, brand/generic aliases, multi-medicine discovery, Repatha variant separation, overlapping hits and stale/altered records.
- [ ] Implement run-pinned lexical artifacts, deterministic rank fusion with semantic hits, bounded name boosting and balanced document grouping. Verify SQLite FTS5 availability and provide the specified deterministic fallback.
- [ ] Validate semantic and lexical hits against the same immutable records and policy; bind the artifact to the active manifest's version.
- [ ] Test empty/long queries, semantic outage with lexical fallback, citation resolution across rebuilds and rollback, and cache invalidation.
- [ ] Independently review and commit.

## Task 3 — Whole-library source import and build orchestration

**Files:** Create `amgen_explorer/library.py` and `amgen_explorer/source_import.py`; modify `service.py`, `models.py`, `indexing.py`, `extraction.py`, `xml_store.py` as needed for identity handling; add `tests/test_library_build.py` and `tests/test_source_import.py`.

**Interfaces:** `import_documents(files: list[SourceUpload]) -> ImportReport`; `ExplorerService.build_library(chunk_config: ChunkConfig, *, activate: bool, on_progress=None) -> LibraryBuildResult`. A SourceUpload carries a filename and bytes. A versioned source registry pins expected documents, identities and source hashes independently of current folder contents. Results expose plain-language stage, source counts, run ID, coverage and recoverable errors. A build always takes the complete registered inventory plus validated imports, never the learner's current medicine filter.

- [ ] Write failing tests for all-document import, duplicate/renamed bytes, sanitized filename collisions, unresolved source-title identity, invalid PDFs, source replacement, repeated clicks, interruption and a registered PDF missing before the first build.
- [ ] Implement the authoritative registry, validated multi-file imports and explicit replacements inside the configured source directory; preserve known product/document identity and prevent path traversal, accidental scope loss and silent filename collisions.
- [ ] Orchestrate XML reuse/build, eligibility, chunks, snapshots, namespaced upload, matching lexical-artifact construction and verification. Activation waits for both search artifacts and the expected inventory.
- [ ] Preserve and resume jobs using the existing checkpoints; make failed attempts leave the active pointer unchanged.
- [ ] Test using temporary PDFs and fake providers. Require failed local-search construction to prevent activation even if Pinecone upload succeeded.
- [ ] Independently review and commit.

## Task 4 — Search-first learner experience

**Files:** Modify `app.py`, `ui/explore.py`, `ui/learn.py`, `ui/common.py`, `amgen_explorer/service.py`, `amgen_explorer/models.py`; add `ui/search_results.py` and `tests/test_search_experience.py`.

**Interfaces:** Extend navigation to carry medicine ID, document ID, `run_id` and an optional pending query. Extend `ExplorerService.answer(..., run_id=None)` and `quiz(..., run_id=None)` compatibly: new conversations without an explicit run resolve the active version once; existing/result-origin conversations retain their run. Session scope keys include run ID. Resolve eligibility from the pinned manifest, including re-explanation, rather than from current global configuration. A result action opens a source-scoped learning session; it must not automatically submit a second paid request.

- [ ] Write AppTest failures proving global search is submitted explicitly, works without a selected medicine and retains its result version across reruns.
- [ ] Replace the homepage name-filter input with the full-content search form, grouped cited excerpts, optional filters and truthful searchable-library counts.
- [ ] Add View source and Ask about this source; carry the source context and query reliably into chat. Retain scoped evidence checks, quizzes and existing session isolation.
- [ ] Test name-free ACTIMMUNE discovery, both Repatha scopes, no repeated calls on rerender, unavailable-library states, pinned source downloads and activation between search/result click/follow-up/quiz. Old conversations stay version-labeled; new conversations can choose the latest library.
- [ ] Independently review and commit.

## Task 5 — Simplified admin import experience

**Files:** Add `ui/admin.py`, `ui/library_admin.py`; refactor `ui/sources.py`, `app.py`, `ui/common.py`; add `tests/test_admin_library_experience.py`.

**Interfaces:** Admin Library calls the whole-library facade from Task 3. Initial Build/update activates on success; no individual-review or separate initial Publish action is required. Existing technical diagnostics are placed under Details.

- [ ] Write AppTest failures for an admin loading all sources with no review selections, explicit upload/build execution and truthful failure/coverage messages.
- [ ] Implement inventory/upload, one primary build/update action, simple progress, actual Pinecone record counts and a ready-to-search destination.
- [ ] Remove passage-by-passage review and duplicate Load/Build test index actions from the new default navigation; preserve legacy records for recovery.
- [ ] Test that learner selections never restrict the admin build, credentials are not rendered, failures preserve search, and UI status distinguishes local files from verified searchable content.
- [ ] Independently review and commit.

## Task 6 — Controlled chunk experiments and evaluation

**Files:** Add `amgen_explorer/evaluation.py`, `ui/chunk_experiments.py`, `evals/global-search.jsonl`; modify `service.py`, `scripts/manage_corpus.py`; add `tests/test_chunk_experiments.py`, `tests/test_evaluation_metrics.py` and `tests/test_chunk_experience.py`.

**Interfaces:** `ExplorerService.evaluate_versions(baseline_run_id: str, candidate_run_id: str, suite_id: str, *, generate_answers: bool = False) -> ExperimentReport`; `ExplorerService.test_chunk_configuration(chunk_config: ChunkConfig, suite_id: str, *, on_progress=None) -> ExperimentReport` orchestrates a complete candidate build with `activate=False` followed by controlled evaluation. Report a compatibility fingerprint, measured metrics, source/citation comparisons, latency and usage. Reuse current chunk settings/preset APIs with accurate labels.

- [ ] Write failing tests for reset/no side effects, full-inventory candidate builds, compatible A/B pins, explicit document scopes, excluded expected evidence and exact span/quote coverage metrics.
- [ ] Implement draft controls, Reset defaults, Restore current settings, a local preview, and one explicit Test settings action that builds using `activate=False` and evaluates. Reject source/policy mismatches against the published full-library baseline.
- [ ] Show side-by-side cited results and an understandable coverage/latency/usage summary; provide Use this configuration after successful testing. Reruns must not repeat either phase.
- [ ] Add Revert to previous full-library version; label legacy pilot recovery distinctly. No reset deletes data or silently activates a partial library.
- [ ] Extend the existing 50 provenance fixtures with global content queries and explicit expected spans; do not treat their presence alone as measured quality.
- [ ] Test metric denominators, ranking stability, same-question/source budgets, mismatch rejection, and no paid evaluations on rerenders.
- [ ] Independently review and commit.

## Task 7 — Migration, demo and release validation

**Files:** Update `config/app.toml`, `README.md`, `docs/demo.md`, `docs/architecture.md`, the renderer and SVG/PNG outputs in `docs/diagrams/`, `ui/demo.py`, `demos/`, `scripts/test_features.py` and relevant regression tests. Add migration/release tests and an implementation report.

- [ ] Write migration tests for legacy manifests, retained review history, existing citations, both eligibility policies and rollback to the untouched pilot.
- [ ] Update configuration and documentation for the approved policy and navigation. Keep original source files and XML intact until the explicit bulk build runs.
- [ ] Update the no-network demo to illustrate full-library import, content search, a clearly prepared chunk comparison, and scoped learning; distinguish prepared examples from actual live status.
- [ ] Run the full offline regression suite and a fresh-checkout CI run; repeat the key UI sequences and source-integrity checks.
- [ ] Perform the authorized first full-library live build with a visible preview of document/chunk counts and expected embedding volume; verify all 37 documents/36 products and complete readable-text coverage before activation.
- [ ] Exercise content queries, source-scoped chat, one controlled chunk comparison, reset/revert and failed-build preservation. Record observed outcomes and usage, not invented quality claims.
- [ ] Review, launch locally, and publish the implemented change to Git only after the approved scope passes its checks.

## Reviewable definition of done

An administrator can load the entire collection without reviewing individual passages. A learner can search an arbitrary term found in a PDF from the homepage and open the correct cited source. The administrator can change chunk size/overlap, build and compare a complete candidate library, choose it or revert, and reset defaults without deleting data. All existing source, citation and failure-preservation protections still hold under the explicit new policy.
