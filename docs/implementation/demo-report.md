> Historical pilot report. Current bulk-library behavior and release evidence are in [the bulk refactor release report](bulk-refactor-release-report.md). Original observations below are retained for traceability.

# Guided demo implementation report

Implemented the binding design in `docs/implementation/qa-demo-publish-plan.md`: a five-stop, approximately three-minute read-only Streamlit tour from source PDF through canonical XML, chunk preview, cited lesson and prepared quiz.

## Files added

- `ui/demo.py` — exports `render(service, corpus, active)`; blue shared hero; five steps; original PDF preview/download; actual canonical XML; passage/provenance display; prepared lesson and quiz; Back/Next/Restart/Exit controls. Service/corpus/active can all be `None`; the page makes no service calls.
- `amgen_explorer/demo.py` — portable local loader; validates included XML/PDF hashes, canonical source structure, document/product scope, exact archive/block spans, actual PDF page text, supporting quote and citation pages. Missing or changed sources fail closed with a sanitized message. No SQLite, manifest, cloud client or provider dependency.
- `demos/repatha-mechanism.json` — sanitized prepared Repatha physical-page-10 example derived from the existing real cited smoke response. Includes only the saved question/answer, source identity/hash/quote/spans and prepared quiz. No namespace, host, credentials, local user path or review approval.
- `tests/test_demo.py` — 19 focused unit/AppTest cases, including a minimal copied source bundle, source identity/quote/span failures, five-step navigation, wrong/correct answer handling, answer-change feedback reset, Back/Restart, Exit/query preservation, source changes mid-tour and recovery controls. HTTP/socket/SQLite access is blocked; all service accesses fail the tests.
- `docs/demo.md` — launch instructions, three-minute script, preparation/provenance semantics, source restoration behavior and test command.
- `docs/implementation/demo-report.md` — this report.

## Verification

Command: `.venv-corpus/bin/python -m pytest tests/test_demo.py -q`

Result: **19 passed in 13.57 seconds**. Five warnings are existing PyMuPDF/SWIG import deprecations. No demo network calls, SQLite connections or service calls occurred. Test-only first-run mismatch about AppTest query-parameter representation was corrected, then the entire focused suite reran successfully.

Source pins:

- XML SHA-256: `94dfcc3aea57dfab6f2cf6df57d01d8655bcca0d0ac60784c0099e74b01df572`
- PDF SHA-256: `7cd077380de177a50ea2dc253abd095a6a91904a7cbc6cf673acdc4218b5c0b9`
- Source document: `repatha_not_made_with_natural_rubber_latex_prescribing_information.pdf`, physical page 10, section 12.1.

Root owns `app.py`/navigation integration and browser QA. The demo should route before constructing `ExplorerService` so direct `?demo=1` entry needs no database. Exit removes the demo query parameter and invokes `navigate('Explore medicines')`. No existing application, common UI, source, configuration, review, corpus, index or provider-state files were edited by this worker. No git operations were performed.
