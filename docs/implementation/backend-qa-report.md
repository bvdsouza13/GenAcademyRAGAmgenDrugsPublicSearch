# Backend QA report

Completed 2026-11-11. Backend edits are limited to `amgen_explorer/service.py`, `amgen_explorer/extraction.py`, and their regression tests. No public service signature changed. This pass did not change credentials, original PDFs, canonical XML, actual review decisions, local live manifests, or provider data.

## Reproduced defects and fixes

1. **Uppercase PDF inventory:** extraction and canonical-source verification already included `.PDF` and mixed-case extensions, while the management inventory only globbed `*.pdf`. Inventory now uses the same case-insensitive suffix rule. Regression creates uppercase and mixed-case files and checks the actual inventory.
2. **Clock-only rebuild invalidation:** identical PDFs rebuilt on different dates produced different XML hashes because `extractedAt` changed. That invalidated evaluation fixture pins and current chunk plans despite identical source data. After complete extraction, schema and source-roundtrip verification, a candidate identical to the existing XML except for `extractedAt` preserves the exact previous XML bytes/hash. Source, parser, template, tool-version, or other artifact changes still replace the XML. Regression forces two distinct dates, verifies byte/hash stability, then changes the PDF and verifies identity changes.
3. **Missing source directory:** building a fresh/misconfigured checkout with no source directory leaked a raw `FileNotFoundError` instead of the documented build error/report. Directory-read failures now raise a sanitized `CorpusBuildError` with a zero-input `BuildReport`, preserving previous XML. Regression verifies the exception/report and untouched prior bytes.

Each defect regression was run and observed failing before the corresponding implementation change; all three subsequently passed.

## Integration checks

Added real local orchestration tests using an artificial one-page PDF, real XML/review SQLite/snapshot code, and a fake Documents provider. They verify:

- Revoking a synthetic review after preview prevents load and creates no run.
- Replacing source bytes prevents both a new review and loading a previously previewed plan.
- Loading/publishing pins original PDF bytes and rendered pages across working-copy changes; tampered pinned XML is rejected.
- Revoking a synthetic published passage prevents both retrieval and re-explanation of previously captured evidence.
- Fresh repository browsing/answer abstention works without credentials or source XML and creates no runtime state.

Existing backend tests also cover tampered provider matches/manifests, publication and rollback profile pins, resumed batch ingestion, review scope/content/parser provenance, exact source spans, safe table/qualifier handling, provider request/error shaping, and credential/configuration validation.

## Verification evidence

- `.venv-corpus/bin/python -m pytest tests/test_service.py tests/test_xml_pipeline.py tests/test_evaluations.py tests/test_indexing.py tests/test_retrieval.py tests/test_review_and_chunking.py tests/test_config.py tests/test_connectivity.py tests/test_teaching.py tests/test_pinecone_setup.py -q`: **132 passed, 21 subtests passed**.
- `.venv-corpus/bin/python -m pytest -q` after integrated UI fixes: **163 passed, 21 subtests passed**, exit 0, 2.66 seconds. Five existing PyMuPDF/SWIG deprecation warnings remain.
- An earlier integrated run reported `test_unpublished_selected_scope_disables_chat_and_quiz` failing because a positional radio selector targeted the explanation widget. This was reported to the root/UI owner and passed in the final run.
- Rebuilt all actual supplied sources into a temporary copy of canonical XML: **37 documents, 1,439 pages, structural schema valid, exact canonical XML identity preserved**. The original canonical artifact and sources were only read.

## Limits

Backend provider behavior was tested with deterministic fakes; this worker performed no live provider writes or actual medical passage approvals. Clinical validity, up-to-date labeling, OCR completeness, and semantic answer accuracy are not established by these tests. Live provider checks, browser QA and publication remain with the root task. The stable rebuild rule intentionally preserves identity only for timestamp-only differences; actual extraction/dependency/schema changes still require new source review/publication and refreshed evaluation pins where applicable.
