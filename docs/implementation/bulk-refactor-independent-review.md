# Independent review: bulk library and global search

Reviewed on 2026-11-11 against the approved bulk-library/global-search design and implementation plan. The review used the tracked diff and new-file review bundle to establish scope, then treated live source files as authoritative. Work was still being integrated during review; the findings below state which fixes were observed.

## Assessment

No critical defect was identified. The implementation substantially follows the architecture and core safety requirements: explicit policy dispatch, automatic exact-source coverage, immutable run records and snapshots, one active pointer for lexical and semantic artifacts, all-document orchestration, source-scoped learning pinned to the result version, isolated configuration experiments, and retained legacy review behavior. One important source-update/evaluation workflow gap remains in the version reviewed. Two smaller source-inspection/import issues are listed below.

This is a code and isolated offline review, not confirmation of the in-progress real provider build. No real data files were changed or locked, and no providers were called by this reviewer. The coordinating agent's full-suite and live-build results are separate release evidence.

## Findings

### Important — Updating the library makes the saved evaluation suite unusable without an unimplemented refresh workflow

Location: `amgen_explorer/evaluation.py:73`, together with `test_chunk_configuration()` at the end of the module and the fixed `global-search` suite in `ui/chunk_experiments.py`.

Every suite row must have the exact current XML hash before any source-span validation occurs. Adding a valid new source changes the consolidated XML hash. After the administrator successfully performs **Build / update entire library**, **Test settings** therefore still fails with “The evaluation suite targets a different XML source version. Refresh fixtures before testing.” There is no refresh operation in the Admin UI or `scripts/manage_corpus.py`. This affects even an addition that leaves every expected document, PDF hash, quote, and span unchanged.

Reproduced using a temporary repository configuration, real generated PDFs/XML, and a filter-aware fake Documents client:

1. Import ALPHA and BETA; build and activate both.
2. Save a valid one-question BETA/Latex suite and confirm `_suite()` accepts it.
3. Import GAMMA; build and activate the complete three-document library successfully.
4. Test a different chunk size against that active library.
5. Observe the XML-version mismatch above, before candidate upload.

The mismatch refusal itself is appropriate; the missing supported refresh path is the defect. The design explicitly tells administrators to update changed sources before comparing chunk settings, so that operation needs to lead to a usable next step. Provide an explicit local suite refresh/rebind operation that revalidates all expected document hashes and exact quotes/spans, preserves the prior suite, and records the new version/hash. Unresolved changed expectations should remain unavailable with precise case identifiers. Do not merely remove source pinning or silently omit failed cases.

Classification: spec compliance and practical workflow, important.

### Minor — Invalid multi-file imports do not identify the offending filename

Location: `amgen_explorer/source_import.py:_identity()` and its call in `import_documents()` (around lines 85–107 and 137).

The newly introduced `UserFacingError` makes local validation text visible, but errors such as “One uploaded PDF is invalid…” and “A PDF title has unresolved medicine identity…” still omit the filename. In a batch of 37 uploads, the administrator cannot identify which input to repair. Batch validation correctly avoids partial writes, but recovery is unnecessarily difficult and falls short of the requested precise batch error.

Wrap identity-validation errors at the call site with the supplied upload filename, and use the inventory filename for disk-source validation. Keep raw provider exceptions on the sanitized path.

Classification: spec compliance and usability, minor.

### Minor — View source opens only the first passage's page in each document group

Location: `ui/search_results.py:34–45`.

All passage excerpts in a document group are displayed, but the single **View source** action uses `meta` from `hits[0]`. If a group contains passages on pages 2 and 18, the displayed page action always targets page 2; the page-18 result has no direct original-page action. The full PDF can still be downloaded, so citations are not lost, but the result-specific inspection promised by the design is incomplete, especially for layout-limited passages.

Render an original-page action for each distinct result page (with a hit/page-specific widget key), or let the grouped source viewer select among the matched pages. Keep the group-level learning action if desired, because it intentionally scopes to the document.

Classification: source-inspection UX, minor.

## Finding resolved during review

Initially, `ui.common.action()` swallowed all local validation messages and showed only a generic configuration/connectivity error. A missing registered document was also absent from the on-disk inventory table, so the administrator could not find the reason the complete build was blocked. The coordinator introduced a dedicated `UserFacingError`, preserved generic handling of provider exceptions, and added missing-source reporting to the library status/UI. Inspection and the targeted `tests/test_user_errors.py` run confirmed the visible missing-filename/provider-sanitization distinction. The narrower batch-filename issue above remains separate.

## Core paths checked

- **Empty reviews and complete coverage:** bulk chunk preparation calls `assess_corpus()` without the review store; physical-source intervals fill archive gaps, and every registered document/product must yield searchable chunks. New records use source verification and `human_review_status=not_assessed`, not synthetic human acceptance.
- **Exact source metadata:** publication revalidates immutable record identities, source text, parent/archive offsets, source ownership, limitation flags, page ranges, and unique interval coverage against the pinned XML. Current PDF hashes/text are checked during preparation, and snapshots are written before upload.
- **Learning version pinning:** search results carry `run_id`; navigation and conversation/quiz keys preserve it; answer, quiz and re-explanation resolve the pinned manifest and corpus. Re-explanation additionally checks its evidence against immutable records. Repatha variants cannot silently combine into one teaching scope.
- **Build failure and retry:** upload checkpoints and content-addressed run identity support retries. Full activation follows remote verification and lexical artifact validation; local artifact failure leaves the previous pointer intact. Complete-inventory checks are independent of learner filters. Registry initialization uses the XML inventory, so a removed expected file cannot silently disappear from an initial build.
- **Source administration:** byte-identical renamed uploads deduplicate; replacements preserve registered identities; batch validation precedes writes; new identities require a supported source title; registry versions are retained. Source-folder edits are detected on the subsequent build.
- **Search:** lexical rows contain exact source text and catalog names from the pinned XML; cloud hits are checked against immutable records; degradation retains local matches. Ranking and document grouping remain deterministic. The concurrent search agent was correcting coordinate-aware deduplication, so its final regression result should accompany this review.
- **Experiments:** both runs must be complete, source/policy/profile-compatible versions; questions and budgets are shared; expected-span coverage uses unions rather than block touches; reset and restore update draft controls only. Candidate builds are isolated; activation and revert retain snapshots.
- **Credentials:** reviewed UI paths do not render configuration secrets or provider exception payloads. Source/build messages now use the explicit safe-local exception boundary. Provider keys were not accessed or printed during review.

## Code-quality assessment

The new domain modules separate source import, build orchestration, policy, search and evaluation reasonably well, and provider clients are replaceable in tests. Content-addressed records plus pinned source validation provide a strong fail-closed boundary. The largest maintainability cost is the densely compressed style in the new modules and bidirectional module dependencies (`library`/`evaluation` import service helpers while the service delegates back through local imports). This did not produce a concrete failure in this review and is not a release blocker; future changes should move shared persistence helpers into a small independent module and favor conventional multi-line control flow.

## Independent validation

- Read the design, implementation plan, changed production modules, relevant new tests, and UI navigation/source rendering paths.
- Ran only the targeted offline command: `.venv-corpus/bin/python -m pytest -q tests/test_user_errors.py tests/test_evaluation_metrics.py` — **6 passed**.
- Ran the isolated three-document source-update diagnostic above, which reproduced the remaining important evaluation workflow failure.
- Did not rerun the full suite, access provider credentials, call providers, mutate application data, or interfere with the live build.

Final release assessment should include the coordinator's live 37-document/36-product coverage verification, actual provider search visibility, controlled chunk comparison, and any fixes made after this review snapshot.


## Resolution after independent review

The implementer reproduced and fixed all findings. Safe local validation errors retain actionable filenames while provider errors remain sanitized. Evaluation suites now materialize against a new source version using unique exact quotations; unavailable expectations remain zero-coverage cases and new documents receive source-bound cases. Every search passage has its own page action. Added tests observed failure before these fixes and passed afterward (`test_user_errors`, `test_source_import`, `test_chunk_experiments`, `test_search_experience`). The final aggregate result is in [the release report](bulk-refactor-release-report.md).

Additional integration hardening verifies immutable bulk evidence before re-explanation, verifies continuation completeness even for direct teaching callers, and keeps long comparison results focused on one selected question. No review finding is intentionally deferred.
