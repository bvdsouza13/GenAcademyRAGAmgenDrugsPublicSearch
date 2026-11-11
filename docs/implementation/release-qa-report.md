> Historical pilot report. Current bulk-library behavior and release evidence are in [the bulk refactor release report](bulk-refactor-release-report.md). Original observations below are retained for traceability.

# Release QA — 2026-11-11

The local prototype and guided demo passed the checks below. This report records observed results, not a guarantee that every possible input or future provider response has been tested.

## Automated verification

| Check | Observed result |
|---|---|
| Complete offline suite | 190 tests and 21 subtests passed |
| Clean Git-tree export, without credentials or runtime state | Same 190 tests and 21 subtests passed |
| Canonical XML/source validation | XSD valid; 37 PDF hashes and 1,439 physical-page text round trips verified; 4,634 archived/candidate blocks |
| Unchanged corpus rebuild | Fresh extraction of all PDFs into temporary storage retained the exact canonical XML identity |
| Compilation | Application, UI, scripts and tests compile successfully |
| Direct demo entry | No service initialization, SQLite connection or network access; no runtime data created |
| Fresh-export catalog | 36 medicines and 37 source documents visible; unpublished learning correctly disabled |
| Independent code review | No unresolved Critical or Important findings in the reviewed release changes |

Five PyMuPDF SWIG dependency deprecation warnings remain; they did not fail tests. Offline tests use fake providers and temporary data. They cover configuration, connectivity failures, XML preservation, corrupt/missing/changed sources, review revocation, sentence/section chunking and limits, retry/resume, verification, explicit publication, rollback, source scoping, teaching checks, exact citation text, page-image cache identity, session progress and demo navigation.

## Live verification

Both configured credentials authenticated. The existing Pinecone `amgenproduct` index was ready and matched the configured Documents API embedding schema. OpenAI reported the configured model available. Four source-specific searches and generated answers passed citation/source validation: Aimovig, both Repatha documents, and Tezspire. Observed elapsed times were 7.067, 6.151, 6.683 and 5.976 seconds respectively. All four generated answers were supported rather than abstained. These checks read the published pilot and did not upload, approve or publish additional content.

Commands:

```sh
.venv-corpus/bin/python scripts/test_features.py all
.venv-corpus/bin/python scripts/build_amgen_xml.py --validate-only
.venv-corpus/bin/python scripts/check_connections.py
.venv-corpus/bin/python scripts/setup_pinecone.py --check
.venv-corpus/bin/python scripts/live_smoke.py --generate --output output/release-live-smoke.json
```

The full live report stays in ignored `output/` on the development machine. The portable prepared demo is independently checked against the committed XML and PDF.

## Browser verification and fixes

Chrome inspection exercised all five demo screens, original PDF rendering, exact XML and chunk text, citation provenance expansion, wrong and correct quiz feedback, clearing feedback after changing an answer, restart and exit to the catalog. A live Aimovig chat response displayed its supporting quote and correctly scoped PDF-page citation. The final walkthrough also exposed a repeated revision label; that label is now normalized and covered by four regression cases. The server was restarted after implementation so imported modules matched the tested files.

Fixed reproduced issues include PDF extension casing in inventory; timestamp-only XML identity changes; missing-directory build failures; repeated filenames and quotes; whitespace loss in exact source text; inaccurate abstention labels; unpublished document scopes enabling learning; review decision defaults; whitespace in catalog searches; and stale quiz feedback. New regressions cover these cases. Details are in the backend, UI and demo QA reports in this directory.

## Repository boundaries and remaining limits

The release includes source PDFs, canonical XML, code, pinned dependencies, configuration templates, architecture diagrams, mockups, demo and tests. Git excludes real credentials, local review/ingestion databases, published manifests, runtime snapshots, reports, caches and virtual environments. Staged blobs were checked against both actual saved API keys and common private-key/API-token patterns before publication.

Live learning still covers the four reviewed mechanism passages in the original machine's pilot. The remaining source passages need review before publication. Source-fidelity review is not clinician sign-off. OCR and shared-host authentication are not implemented. The app remains bound to localhost; this release does not deploy a public service or establish clinical production readiness.
