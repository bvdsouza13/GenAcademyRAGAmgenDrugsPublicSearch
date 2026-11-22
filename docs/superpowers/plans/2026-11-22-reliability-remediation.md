# Reliability and Learning-Quality Remediation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Implementation requires the user's approval first. Steps use checkbox syntax for tracking.

**Goal:** Resolve every demonstrated failure case, improve learner usefulness and whole-library recovery, and verify the result without weakening source safeguards.

**Architecture:** Keep the existing application and add focused query interpretation, evidence eligibility, readiness and recovery components. Separate immutable source identity from current provider health and runtime ranking policy. Source/parser changes produce isolated candidates; exact repair restores the original pinned records.

**Tech Stack:** Python 3.12 environment, Streamlit, PyMuPDF, lxml/XML, SQLite FTS5 plus token fallback, current Pinecone Documents API profile, OpenAI Responses API, pytest/AppTest. No replacement cloud service or mandatory OCR dependency.

**Spec:** [Reliability remediation design](../specs/2026-11-22-reliability-remediation-design.md).

**Status:** Approved by the user on 2026-11-22 ("Fix all the 8"); implemented and verified; see the [release report](../../implementation/reliability-remediation-release.md). OpenAI authentication and one verified three-citation answer have already recovered following the user's credential update; software readiness improvements remain in scope.

## Global constraints

- Implementation starts only after the user approves this proposal.
- Keep the existing local Streamlit, single consolidated XML, Pinecone Documents API and OpenAI Responses API architecture.
- Preserve whole-library administration and global content search; do not introduce individual medicine or passage approvals.
- Keep chunk defaults at 600/80 until controlled evaluation supports a change; chunk and evidence controls use conservative UTF-8 byte budgets, not exact model tokens.
- Preserve exact PDF/XML hashes, source spans, document/device distinctions, immutable artifacts and run-pinned citations.
- Never publish a generated medicine claim without its exact supporting quote and the existing independent entailment check.
- Keep unresolved layout, missing-context and unsupported-source restrictions; do not remove them to improve an answer-success percentage.
- Opening or rerendering a page must not initiate provider calls, uploads, repairs, reindexing or deletion.
- Use isolated candidates for source, parser, eligibility or chunk changes; preserve the prior active library until verification succeeds.
- Restore missing or mismatched remote records only from an intact pinned local record set, using identical IDs/content and the unchanged provider profile.
- Keep credentials and raw provider responses out of logs, artifacts, UI and Git.
- Retain published/active/rollback/reference-held versions; cleanup is explicit, previewed and never index-wide.
- Keep the server bound to 127.0.0.1; hosted authorization is a separate product change.

## Review focus

1. A generic name that maps to multiple products, or a multi-product question, must not be silently narrowed (Task 2).
2. Retained v1 search artifacts and conversations must survive a query-ranking upgrade with their checksums unchanged (Task 2).
3. A provider outage during repair must not be mistaken for missing records, and a concurrent second repair must not race (Task 4).
4. A general label question mentioning pregnancy or age must remain distinguishable from an individual treatment request, including follow-ups (Task 7).
5. A table caption, repeated passage or multi-column page must not gain unsupported certainty through layout segmentation (Task 9).

## Delivery order and responsibilities

| Stage | Tasks | Independently reviewable outcome |
|---|---|---|
| A — Baseline and honest checks | 1, 3 | Representative evaluation; real generation readiness and bounded failures |
| B — Relevant global search | 2 | Useful named/content queries, no-results behavior and migration compatibility |
| C — Whole-library recovery | 4, 5 | Verified remote repair and reachable local recovery |
| D — Reliable learning | 6, 7, 8 | Scoped outage fallback, complete evidence, safe follow-ups and stable varied quizzes |
| E — Coverage and operations | 9, 10 | Accurate layout/page coverage, controlled experiments and retention visibility |
| F — Release verification | 11 | Passing regressions, live evidence, refreshed docs and local launch |

Tasks 2, 4–5 and 6–8 can be developed in parallel after their contracts are agreed. Shared files (`service.py`, `models.py`, `config.py`, `app.py`) have one integration owner. Each package is reviewed and committed after its targeted checks pass; do not publish a partially validated migration.

## Task 1 — Evaluate the actual learner experience

**Files:** Modify `amgen_explorer/evaluation.py`, `evals/global-search.jsonl`, `evals/README.md`, `tests/test_evaluation_metrics.py`, `tests/test_evaluations.py`, `tests/test_failure_operations.py`, `ui/chunk_experiments.py`; add `evals/learner-search.jsonl` and `tests/test_learner_evaluation.py`.

**Interfaces:** `score_discovery(case: dict, hits: list[dict], *, k: int) -> dict` scores the visible search results before teaching-budget clipping. Case fields separate `requested_filters` from expected source identities/spans and carry relevance judgments plus development/holdout partition. Preserve `score_case(..., evidence_budget=...)` for teaching coverage.

- [x] Add failing tests showing a relevant-first/noisy-tail result list scores worse on precision/graded relevance than a focused list; expected sources must never become hidden home-page filters.
- [x] Run `python -m pytest -q tests/test_learner_evaluation.py tests/test_evaluation_metrics.py` and confirm the missing behavior fails.
- [x] Add unfiltered versions of all 37 source questions and conversational brand, typo, generic ambiguity, multi-product, semantic paraphrase, nonsense, unrelated, safety/overview and follow-up cases. Keep each suite within the existing 100-case input bound, or explicitly update/test that bound if necessary. Bind judgments to source/page/span, not chunk IDs; distinguish unjudged hits from irrelevant ones.
- [x] Implement precision@5/@10, graded relevance, no-answer correctness, suggestion correctness and judgment coverage. Retain citation resolution, quote coverage, latency and usage as distinct measures. Execute behavioral assertions instead of merely counting retained behavioral fixtures.
- [x] Measure and save the current baseline before changing ranking; freeze the holdout partition before calibration. Do not invent aggregate precision targets before labeling and baseline measurement. The named failure examples have unconditional acceptance requirements.
- [x] Run the evaluation tests and independently review/commit this package. Update the characterization test documenting the old metric blind spot to require the new metric to detect it.

## Task 2 — Query interpretation, relevance ranking and no-results behavior

**Files:** Create `amgen_explorer/query_intent.py`; modify `amgen_explorer/search.py`, `service.py`, `evaluation.py`, `ui/explore.py`, `ui/search_results.py`; extend `tests/test_failure_search.py`, `test_global_search.py`, `test_search_artifacts.py`, `test_search_experience.py`.

**Interfaces:** `analyze_query(query: str, corpus: Corpus) -> QueryIntent`, with meaningful terms, recognized product candidates, ambiguity, section intent and suggestions. Extend `SearchResults` compatibly with `outcome` (`results`, `no_results`, `clarification`) and `suggestions`. Add `search_local(query, run, config, corpus, *, product_ids=None, document_ids=None, limit=20) -> SearchResults`, which cannot contact Pinecone.

- [x] Remove the six search xfail markers and run `python -m pytest -q tests/test_failure_search.py`; confirm the three failure families fail under both lexical engines.
- [x] Add retained-v1-artifact, ambiguous `denosumab`, multi-product, meaningful negation, numeric/unit, no-literal-overlap semantic paraphrase, and local typo-suggestion tests.
- [x] Recognize catalog aliases inside questions using token boundaries; remove conversational filler from lexical queries while retaining meaningful qualifiers. Keep the original query for semantic retrieval. Names influence relevance; only explicit filters impose hard scope.
- [x] Replace unconditional document round-robin with relevance-first selection and diversity among relevant candidates. Calibrate a relevance gate on the development cases using lexical/name/section/semantic features; do not use RRF as confidence or apply an arbitrary universal vector threshold. Suggest catalog typos without silently substituting another medicine.
- [x] Separate immutable artifact-format identity from runtime ranking-policy version. Existing v1 paths/checksums/pins remain authoritative; old descriptors continue validating. Evaluation controls record the actual query ranking policy. A ranking-only change must make zero upsert calls.
- [x] Run `python -m pytest -q tests/test_failure_search.py tests/test_global_search.py tests/test_search_artifacts.py tests/test_search_experience.py tests/test_learner_evaluation.py`. Require both known named-question examples, all negative examples, variants and body-content cases to pass; review held-out tradeoffs and commit.

## Task 3 — Provider readiness, truthful smoke tests and bounded work

**Files:** Create `amgen_explorer/readiness.py` and `amgen_explorer/reliability.py`; modify `connectivity.py`, `teaching.py`, `retrieval.py`, `service.py`, `config.py`, `config/app.toml`, setup examples, `ui/library_admin.py`, `scripts/check_connections.py`, `scripts/live_library_check.py`; extend connectivity/config/operations tests and add `tests/test_reliability.py`.

**Interfaces:** `check_readiness(service, *, require_generation=False) -> ReadinessReport` separates model access, semantic retrieval and verified generation, with time/configuration identity and sanitized status. `Deadline(seconds, *, clock)` exposes `remaining()` and expiry. `ProviderError` gains an optional sanitized retry delay; no raw response is persisted.

- [x] Remove OPS-03's xfail marker and add tests for model-access success with generation 401/429/refusal, expected layout fallback, numeric/date/malformed Retry-After, and fake-clock deadline exhaustion.
- [x] Run the new operations/reliability tests and confirm missing readiness/deadline behavior fails.
- [x] Make `live_library_check.py --chat` require designated supported cases to generate and pass entailment; grade deliberately restricted cases as source-fallback contracts. Model-list success alone cannot satisfy generation readiness. Do not call providers on page render.
- [x] Add a 60-second total learning-response budget, pass remaining time into retrieval/generation/verification, and reject late/unverified output. Preserve safe quotations on timeout. Preserve four total upload attempts; use exponential backoff with jitter and bounded Retry-After. Do not retry 401/403. Interrupted/ambiguous provider usage remains explicitly unknown where appropriate.
- [x] Add optional `[reliability]` settings with validated compatibility defaults: `response_deadline_seconds=60`, `max_attempts=4`, `retry_budget_seconds=60`, `backoff_base_seconds=1`, `backoff_cap_seconds=8`. Existing config files continue loading; don't rewrite the user's secrets. Show last-checked readiness, and distinguish stale/unchecked from current failure.
- [x] Run `python -m pytest -q tests/test_failure_operations.py tests/test_reliability.py tests/test_config.py tests/test_connectivity.py tests/test_teaching.py`. Keep unrelated operational xfails until their owning tasks land; review and commit.

## Task 4 — Verify and repair the entire remote library

**Files:** Create `amgen_explorer/library_health.py`; modify `indexing.py`, `library.py`, `service.py`, `ui/library_admin.py`, `scripts/manage_corpus.py`, `scripts/assess_failure_modes.py`; extend `tests/test_failure_recovery.py`, `test_indexing.py`, `test_library_build.py`, admin AppTests.

**Interfaces:** `ExplorerService.verify_library(run_id=None, *, repair=False, on_progress=None) -> LibraryVerificationReport`. Report fields include run/time, outcome (`verified`, `drift`, `unavailable`, `local_invalid`), expected/matched/missing/mismatched counts, document visibility and sanitized errors. Reports live under `data/health/`; they do not overwrite historical immutable identity. `library_status()` reads reports locally.

- [x] Remove REC-01/02's xfail markers; add all-missing, one-missing, metadata-drift, intact-library/no-upsert, outage-not-data-loss, concurrent repair and interrupted repair tests.
- [x] Run targeted recovery/indexing tests and confirm the recovery defects fail.
- [x] Validate the pinned source snapshots, record set, artifact and unchanged provider profile before remote checks. Fetch expected IDs in bounded batches, compare fields, and check each document's search visibility. Label the scope as expected-record verification, not proof of absence of extra records.
- [x] Repair only missing/mismatched expected records in the original namespace with identical IDs/content. Reconcile historical checkpoints against current observations. Hold library/index locks in consistent order, checkpoint repair work, and fully reverify. Healthy records are not uploaded again. Source/parser/chunk/profile changes still use isolated candidates.
- [x] Make an explicit unchanged Build reverify and reconcile instead of trusting its old verified status. Keep verification read-only until repair is requested; show repairing/degraded states and update the last-verified timestamp only after success. Never activate an incomplete candidate.
- [x] Run `python -m pytest -q tests/test_failure_recovery.py tests/test_indexing.py tests/test_regression_indexing.py tests/test_library_build.py tests/test_admin_library_experience.py`; independently review and commit. Destructive cases use temporary providers only.

## Task 5 — Recover damaged local state without losing navigation

**Files:** Create `ui/recovery.py`; modify `source_import.py`, `library.py`, `indexing.py`, `service.py`, `app.py`, `ui/explore.py`, `ui/library_admin.py`; extend source-import/library/UI/operations/recovery tests.

**Interfaces:** `ExplorerService.recover_working_xml() -> BuildReport` regenerates working XML from validated registry/PDFs. `list_recoverable_versions() -> dict` returns separately validated entries and sanitized warnings. `restore_library_version(run_id: str)` validates selected local assets plus remote readiness before atomic activation. Quarantine actions occur only during explicit recovery.

- [x] Remove REC-03/04/05 and OPS-01/02 xfail markers. Add malformed JSON/object type, manifest filename/run mismatch, bad config, damaged selected snapshot, invalid registry, no recoverable version and failed restoration tests.
- [x] Run `python -m pytest -q tests/test_failure_recovery.py tests/test_failure_operations.py` and confirm remaining cases fail for the intended reasons.
- [x] Hash existing PDFs before classifying uploads as duplicates. Honor explicit replacement to restore original registered bytes transactionally; preserve identity and traversal checks.
- [x] Regenerate malformed working XML via a temporary file from the validated complete registry and intact PDFs, validate it, preserve damaged bytes in quarantine and replace atomically. Never mutate published source snapshots or guess an inventory when trusted registry copies are unavailable.
- [x] Render a recovery-capable shell before active-state loading. Isolate malformed historical entries; contain Home/Admin status failures. Active/selected versions remain strictly validated. Offer validated retained versions for recovery and keep Demo independent; no repair or quarantine on rerender.
- [x] Run source-import, library, regression-UI, search-experience and new fault tests. Require active snapshots and prior learning references to remain intact; review and commit.

## Task 6 — Shared evidence rules, local chat fallback and context allocation

**Files:** Create `amgen_explorer/evidence_policy.py` and `amgen_explorer/evidence_selection.py`; modify `retrieval.py`, `teaching.py`, `service.py`, `models.py`; extend teaching/retrieval/evidence/service tests.

**Interfaces:** `assess_evidence(evidence: EvidenceBundle) -> EvidenceAssessment` provides validated sources, generation/quiz eligibility and reason codes. `select_evidence(question, records, ranked_ids, *, budget_bytes, intent) -> EvidenceSelection` returns selected records plus explicit omissions/completeness reasons. Task 2's `search_local` supplies a scoped, provider-free fallback.

- [x] Remove FT-05/06 xfail markers; add atomic continuation-group, misleading missing-sibling, wrong variant/run, corrupted local artifact, and mechanism/indications/safety allocation tests.
- [x] Confirm current chat-outage and warning-starvation tests fail. At the current 4,000-byte budget, the supplied overview fixture must retain its relevant indication passage alongside relevant safety evidence.
- [x] Introduce shared eligibility checks without weakening source/record validation. Pack continuation groups atomically; keep requested facts and required qualifiers together. If full required context cannot fit, state the limitation and withhold unsupported generation.
- [x] Route Pinecone outage retrieval to verified local search scoped to the same run/product/document. Do not recurse into global search and call the failed provider again. Label degraded mode and preserve the existing service evidence validator.
- [x] Compare 4,000/6,000/8,000 budgets on the fixed suite after selection changes. Include prefix bytes consistently in packing and evaluation. Report completeness, qualifier retention, answer eligibility, latency and usage before choosing a new default.
- [x] Run `python -m pytest -q tests/test_failure_teaching.py tests/test_retrieval.py tests/test_regression_evidence.py tests/test_service.py tests/test_bulk_eligibility.py`; independently review and commit.

## Task 7 — Learning intent and vetted follow-up suggestions

**Files:** Create `amgen_explorer/learning_policy.py`; modify `teaching.py`, `service.py`, `ui/learn.py`; extend teaching/service/AppTest tests.

**Interfaces:** `route_learning_question(question: str, history=None) -> LearningRoute` distinguishes educational, personal-treatment, unsupported and clarification outcomes. `suggest_followups(assessment: EvidenceAssessment, intent) -> list[str]` chooses vetted, source-appropriate educational prompts.

- [x] Remove FT-01 and all three FT-02 xfail markers. Add indirect/third-person/age/breastfeeding, multi-turn “what about me?”, general pregnancy-label questions and harmless first-person learning requests.
- [x] Confirm injected unsafe follow-ups and the three known paraphrases fail under current behavior; retain positive educational controls.
- [x] Route personal-treatment intent before retrieval in the service, with a matching defensive gate for direct teaching callers. Preserve educational access to general source warnings. Use fixed educational follow-up templates; ignore model-supplied follow-up text rather than publishing it after a phrase-only filter.
- [x] Keep exact citation and independent entailment checks for generated answers. Add injection, product-switch and alternate-reading-depth tests; do not claim exhaustive natural-language safety from finite tests.
- [x] Run `python -m pytest -q tests/test_failure_teaching.py tests/test_teaching.py tests/test_service.py tests/test_regression_ui.py`; review and commit.

## Task 8 — Grounded quizzes with stable shuffled answers

**Files:** Modify `teaching.py`, `ui/learn.py`, `service.py`; extend `tests/test_failure_teaching.py`, `test_teaching.py`, `test_regression_ui.py`, `test_search_experience.py`.

**Interfaces:** `make_quiz(evidence, config, *, rng=None) -> dict` calls Task 6's shared eligibility policy, chooses a supported extractive/section-matching template, and shuffles once. Existing session quiz state retains displayed choices, answer index, rationale and source/run identity.

- [x] Remove FT-03/04 xfail markers. Replace the probabilistic 20-draw position test with controlled-RNG assertions demonstrating answer-position variation and correct remapping.
- [x] Add rerun/navigation persistence, correct grading after shuffle, source-switch isolation and shared layout/continuation-restriction tests; confirm current behavior fails.
- [x] Generate only source-grounded quizzes, avoid invented medicine/dosing distractors, remove position-dependent rationale wording and persist the complete generated quiz. Ineligible evidence yields an explanation/source-reading option, not a scored quiz.
- [x] Run teaching plus UI/quiz regression suites, review and commit. All nine teaching diagnostic failure instances should now pass normally.

## Task 9 — Precise layout restrictions and visible page coverage

**Files:** Modify `extraction.py`, `xml_store.py`, `models.py`, `eligibility.py`, `chunking.py`, the XML schema/extensions if required, `ui/library_admin.py`, `ui/chunk_experiments.py`; extend XML/bulk-coverage/teaching/admin tests.

**Interfaces:** `coverage_summary(corpus: Corpus) -> dict` exposes total pages, pages with searchable text, no-text pages and limitation reasons. Layout spans preserve original archive offsets and extraction/parser/policy version; no OCR text is silently substituted for native text.

- [x] Add failures for clean narrative adjacent to a separable table/figure, heading-only references, ambiguous multicolumn/continuing tables, repeated strings and mixed readable/image-only pages.
- [x] Split demonstrably separable native-text narrative from restricted layout regions while keeping exact archive coverage. Keep ambiguous row/column/caption relationships restricted. Version extraction changes and validate them as a new candidate.
- [x] Display “pages with searchable text / total pages” and no-text/possible-OCR exceptions before/after build. Distinguish true unreadability from unknown blank-or-image-only status; preserve raw readable-character coverage separately.
- [x] Run `python -m pytest -q tests/test_xml_pipeline.py tests/test_bulk_coverage.py tests/test_bulk_eligibility.py tests/test_failure_recovery.py tests/test_teaching.py tests/test_admin_library_experience.py` and exact-span round-trip validation.
- [x] Repeat the same 37-document mechanism probe against baseline/candidate. Report each fallback reason; resolve validated avoidable cases without requiring unsupported 37/37 generation. Preserve the old active version until complete candidate verification; review and commit.

## Task 10 — Experiment cost, retention and local capacity controls

**Files:** Create `amgen_explorer/retention.py`; modify `library.py`, `indexing.py`, `connectivity.py` only after API-contract verification, `ui/chunk_experiments.py`, Admin Details and management CLI; add `tests/test_retention.py` and expand experiment tests.

**Interfaces:** `plan_cleanup(config, *, selected_run_ids: list[str]) -> CleanupPlan` produces a dry-run inventory and protected references. `apply_cleanup(plan: CleanupPlan) -> CleanupReport` revalidates the plan and performs only explicitly selected safe actions. Default selection is empty; published/active/rollback/reference-held versions are protected.

- [x] Add tests for zero-mutation preview, no automatic cleanup/reset deletion, protected runs, shared snapshots, concurrent reference changes, provider failure and idempotent retries.
- [x] Show prepared chunk volume, retained local storage, previous provider-reported usage and clearly labeled unknown remote/dollar cost. Reuse a healthy retained experiment without uploading again; apply Task 4 verification when checking current remote integrity.
- [x] Implement protected-reference inventory and explicit selection. Verify the current official Pinecone Documents API listing/deletion capability before adding that adapter; do not guess endpoints. Do not delete local provenance until the selected remote cleanup is confirmed. If a safe capability/reference proof is unavailable, retain the version and state exactly what was not cleaned.
- [x] Measure the current corpus under one and five concurrent local read sessions, including cold/warm query and page-render latency and memory. Establish a measured capacity note. Any validation caching must retain checksum/source-identity protections and invalidate on change; no performance claim substitutes for integrity tests.
- [x] Run retention/experiment/indexing tests, review results and commit. Full OCR, public hosting and clinical currency certification remain documented separate capabilities.

## Task 11 — Integrated regression, live verification and release documentation

**Files:** Refresh `README.md`, `docs/configuration-and-pinecone-setup.md`, `docs/architecture.md`, diagrams where flows changed, `docs/demo.md`, `docs/future-features.md`, `evals/README.md`, script help and CI/test grouping. Add a remediation release report under `docs/implementation/`.

- [x] Confirm all 23 diagnostic failure instances are ordinary passing tests with xfail markers removed. Preserve equivalent coverage if a test is replaced for determinism; do not weaken assertions to make the suite green.
- [x] Run `python scripts/test_offline.py --shuffle-seed 20261123` and a clean-checkout run. Require zero unexplained failures, zero unexpected network attempts and no xfails for the repaired gaps. Run `git diff --check` and verify secrets/runtime outputs remain excluded from Git.
- [x] Run explicit live provider readiness plus verified generation, expected source fallback and safe redirects. Run held-out global search and all 37 document retrieval probes, with citations/scopes verified and category-level regressions reviewed.
- [x] Fetch/compare every expected remote record and test every document scope for a new candidate; verify activation/revert and an existing conversation pinned to the previous run. Real active records are never deleted for tests.
- [x] Refresh documentation and demo to show global search, honest readiness, one whole-library repair flow, source limitations and chunk comparison. Record the resolved credential incident separately from software remediation; report remaining capability boundaries accurately.
- [x] Independently review the integrated diff, launch the verified app locally, and provide the release report and commit summary. Remote publication follows the user's approved delivery scope.

## Traceability: every demonstrated failing instance

| Existing failure family | Instances | Owning task |
|---|---:|---|
| Named-question boilerplate pollution, both lexical engines | 2 | 2 |
| Irrelevant semantic neighbors accepted, both engines | 2 | 2 |
| Stopword-only search returns drug results, both engines | 2 | 2 |
| REC-01 active repeat build trusts absent remote records | 1 | 4 |
| REC-02 verified candidate cannot repair remote loss | 1 | 4 |
| REC-03 original-byte reupload does not restore corrupt PDF | 1 | 5 |
| REC-04 malformed working XML prevents rebuild | 1 | 5 |
| REC-05 corrupt historical manifest breaks status | 1 | 5 |
| FT-01 unchecked treatment instruction in follow-ups | 1 | 7 |
| FT-02 personal-treatment paraphrases bypass deterministic routing | 3 | 7 |
| FT-03 fixed quiz answer position | 1 | 8 |
| FT-04 quiz bypasses layout/continuation restrictions | 2 | 6, 8 |
| FT-05 chat retrieval lacks local outage fallback | 1 | 6 |
| FT-06 safety passages starve relevant overview evidence | 1 | 6 |
| OPS-01 status exception escapes Home page | 1 | 5 |
| OPS-02 corrupt active pointer removes recovery navigation | 1 | 5 |
| OPS-03 smoke check passes when generation provider fails | 1 | 3 |
| **Total** | **23** | |

Additional assessment gaps map to Task 1 (evaluation blind spot), Task 2 (typos and migration), Task 3 (retry/deadline/readiness), Task 9 (coverage and overbroad layout flags), Task 10 (usage/retention/capacity), and Task 11 (documentation/demo/live evidence). These are additive acceptance requirements, not excuses to leave a reproduced gap marked expected-failure.

## Approval and completion

The user approved implementing the proposed local-app changes and testing them in stages on 2026-11-22. The proposal does not authorize real destructive fault injection, automatic retention deletion, a public deployment or claims of clinical validation. Full OCR remains a separately described extension.

Completion means every demonstrated defect is resolved, new regressions and migration checks pass, required live checks pass, remaining source limitations are visible and safe, documentation is refreshed, and the application is running locally. If a required outcome cannot be met, report it as outstanding rather than declaring the plan complete.
