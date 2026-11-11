# Independent final implementation review

Reviewed 2026-11-11 against `contracts.md`, the implementation plan, worker reports, and the current files directly. This directory has no Git baseline. Review covered the corpus loader/review/chunker, service orchestration and source snapshots, ingestion/publication/rollback, retrieval and teaching, and Streamlit source/learning state. The latest content-addressed manifest validation and exact-source fallback were present during inspection. Also inspected `scripts/live_smoke.py`, `scripts/test_features.py`, and the evaluation fixture checks.

## Initial verdicts (superseded by the follow-up below)

**Spec verdict: substantially compliant for the explicitly limited local pilot, pending the source-image identity fix below.** Extraction, raw-passage review, separate staging/publication, product/document scoping, immutable citation resolution and conservative abstention are implemented. This is not approval for broad clinical release. The four reviewed mechanism passages, conservative byte bound, existing index truncation setting and no-OCR limitation are disclosed departures/limits, rather than hidden completeness claims.

**Code-quality verdict: changes requested for one Important correctness finding; no Critical findings identified.** The backend generally fails closed: exact record contents are bound to run identity; changed source/review/configuration prevents normal publication; search results must match pinned local records; current review status is checked again before teaching; source downloads are hash-verified against the pinned snapshot. Provider errors are sanitized and paid calls are explicit. The local process lock and atomic active-pointer replacement fit the single-host scope.

## Important finding — cached PDF image can be relabeled as a different source page (resolved)

- Location: `ui/common.py:111–116`; key reuse originates in `ui/learn.py:84`, `ui/learn.py:97–108`, and the reusable quiz citation key.
- `source_view()` stores rendered bytes under `page_image_{key}` without binding that entry to `document_id`, `xml_hash`, or `page`. Citation keys are based on session scope and history/citation indexes. Clearing the conversation removes the history but preserves these image entries. A subsequent answer can reuse the same key with a different page or source snapshot. Recreating a quiz similarly reuses its citation key.
- The renderer immediately displays the old bytes under the new caption, even when the new page button was not clicked. Thus the displayed original page can disagree with the citation and verified PDF download. This is a source-provenance correctness issue, not merely stale cosmetic state.
- A provider-free reproduction called `source_view(..., key='reused', page=9, xml_hash='new-xml-hash')` with `session_state['page_image_reused'] = b'OLD PDF PAGE 2'`, a false page-button return, and a mocked page resolver. Observed output: `('OLD PDF PAGE 2', 'Original PDF · page 9')`; the new page resolver was never called.
- Fix: bind cached rendered bytes to the complete source identity (document, pinned XML hash, physical page; include PDF hash for mutable working-source views), or retain that identity with each cache entry and suppress a mismatch. Clearing chat alone is insufficient because quizzes and source revisions can also reuse keys. Add a focused regression proving a changed source identity never displays the previous image.

## Evidence and coverage limits

The root supplied the completed whole-suite result of 121 tests plus 21 subtests, the live six-record Pinecone verification, and three live teaching outcomes (two supported, one abstained). Those existing suites were not rerun. This review independently inspected failure paths and executed the focused image-cache reproduction above; it did not make cloud calls or alter review/publication state.

The source snapshot resolver checks pinned XML/PDF hashes, and its tests cover changed working PDFs and corrupted retained PDFs. The latest indexing checks reconstruct the run digest from the exact retained records, scope and profile before publication, rollback or retrieval. Teaching withholds an unverified paraphrase and labels the newer direct-source fallback as an abstention with `explanation_verified=false`. These inspected controls support the local demonstration; they do not prove semantic recall or clinical correctness.

Only four mechanism passages are reviewed, producing six chunks across Aimovig, Tezspire and the two distinct Repatha files. The 50 evaluation fixtures establish source coverage and case categories; their clinical expected answers are explicitly pending review. Broad warning/indication coverage, OCR/layout reconciliation, exact hosted-tokenizer parity, browser accessibility and general semantic teaching quality remain outside this signoff. The historical live report predates the newer source-fallback behavior; do not describe that report as a live validation of the fallback.

README/handoff updates were still being prepared by the root while this review ran, so their final consistency is not included in this verdict. No implementation files were edited by this reviewer.


## Scoped follow-up review — 2026-11-11

**Final spec verdict: passes review for the explicitly limited local pilot. Final code-quality verdict: approved within the reviewed scope; no unresolved Critical or Important findings.** The original source-image provenance finding is addressed.

Inspected the corrected `ui/common.py` and all seven focused source-cache regression cases in `tests/test_app_flows.py`. The cache now binds each rendered image to document ID, pinned XML hash, physical page, and SHA-256 of the verified PDF bytes. It clears mismatched and legacy entries, suppresses images when the current PDF cannot be verified, and retains reuse only for an identical source identity. Rendering remains an explicit button action. This resolves reused chat/quiz positions as well as changed working PDFs, without relying on conversation cleanup. No new breakage was identified in the changed path.

The UI worker reports six regression failures before the fix, then seven focused passes and 21 complete UI-suite passes, plus successful compilation. Per the scoped re-review instruction, these tests were inspected but not rerun by this reviewer.

A quick consistency inspection of the updated README and configuration guide found that they now describe the implemented app, current existing index profile, local execution, four reviewed passages/six chunks, no OCR, conservative token bounds, and limited clinical/evaluation coverage consistently. `output/live-smoke.json` was inspected: status is `passed`, generation is enabled, and all four source-specific checks contain a supported answer (`abstained=false`) with citations. This is stronger live pilot evidence than the earlier historical three-outcome report; it still does not validate broad clinical coverage or force the newer fallback path.

This follow-up is limited to the finding, its regression coverage, and the requested quick handoff consistency check. Alternate-configuration publication/rollback verification was still being conducted by the root and is not represented here as independently reviewed evidence. The coverage limits from the original review continue to apply.

## Bounded source-validation follow-up — 2026-11-11

**Verdict: approved; no new Critical or Important findings in this addition.** Inspected only `xml_store.validate_source_files()`, its `--validate-only` CLI invocation, and the two added regression tests. The CLI first loads and validates the canonical XML, then requires an exact current PDF inventory, matches PDF hashes, and compares the physical page counts and complete extracted page strings with the XML archives. PDF parsing uses the same in-memory bytes that were hashed. It rechecks each file hash after extraction and the inventory before reporting success. The path is read-only: it neither rebuilds XML nor changes review, snapshot, ingestion or publication state.

The regression tests cover added/missing/changed PDFs, restoration, archive-text mismatch and unchanged canonical XML bytes. Supplied verification evidence is 23 corpus tests, 145 whole-suite tests plus 21 subtests, and the real validation of 37 current PDF hashes and 1,439 page-text comparisons with unchanged XML/reviews. Per the bounded instruction, this reviewer did not rerun those checks. The addition establishes current-file/source-text fidelity at validation time; it does not extend the existing clinical/OCR completeness claims. The final limited-pilot approval above remains in effect.
