# Streamlit UI implementation

Implemented `app.py`, `ui/common.py`, `ui/explore.py`, `ui/learn.py`, `ui/sources.py`, and `tests/test_app_flows.py` against the shared `ExplorerService` facade. Uses the supplied real Amgen logo, #0063C3 branding, a consistent sidebar, vivid blue hero, cyan medicine cards, native controls, and responsive columns.

- Explore derives its 36-medicine, 37-document, 1,439-page counts from the real local XML. Search supports brand/generic names and A–Z/Z–A. Cards distinguish published learning content from sources awaiting review/publication.
- Learning scopes every explicit request to medicine and optional document. Multiple published document scopes require a source choice. Native chat renders cited passages, source revision/variant, PDF downloads, and original page images; citations pass their pinned XML hash to the resolver. Plain/technical controls make no requests on change. An explicit Re-explain last answer button uses the response’s hidden, pinned EvidenceBundle without repeating retrieval. Guided lessons, extractive source quizzes, and progress remain in session state.
- Sources provides inventory, explicit XML build, extraction result, local XML download/preview, hash-scoped passage review, original PDF/page inspection, local chunk presets, conservative UTF-8 byte budget controls, exclusions, exact prepared embedding text, matching overlap highlighting, and provenance.
- Explicit Load Pinecone and Build test index stage content. Uploaded-record progress uses backend counts. Verification remains separate from publication. Pending runs cannot publish; changing local chunk controls disables publication until the matching preview is restored. The workshop also supports explicit connection tests, retrieval comparisons, publication, and rollback.
- Provider calls and mutations occur only on explicit control events. Caught exception payloads are never displayed; credentials remain server-side. Download paths are restricted to the configured project root, and PDF resolution is delegated to the facade.

Verification: `.venv-corpus/bin/python -m pytest tests/test_app_flows.py -q` → **14 passed**. These cover empty sources, missing credentials, explicit successful/failed builds, exception redaction, no rerun replay, explicit connection tests, reviewer requirement, scoped chat, document variants, local mode changes, explicit same-evidence re-explanation, empty previews, pending verification, explicit publication, stale settings, and quiz progress. Compilation of app/UI modules passed.

Real-facade AppTest smoke rendered Explore and Manage sources without exceptions and confirmed 37 PDFs / 36 medicines / 1,439 pages. Native Chrome screenshot inspection confirmed the catalog layout and real branding. Browser-specific CUA calls failed with a tool `timeoutMs` error; native Chrome inspection worked. The temporary UI QA server on port 8502 was stopped; root owns the user-facing server on port 8501. Root is performing further visual/narrow-screen/PDF-page QA.

Dependency needs: Streamlit and pytest, installed by root. No backend, configuration, requirements, or Git files were changed by this worker. Clinical source acceptance and cloud publication were not performed by the UI worker.

## Final-review correction — source page cache identity

Fixed the Important finding in `final-review.md`: a reused chat/quiz view key can no longer relabel a cached image as another original PDF page. Every cached image now carries the document ID, pinned XML hash (or working-source state), 1-based physical PDF page, and SHA-256 of the verified PDF bytes already fetched for download. The renderer clears and suppresses mismatched or legacy unbound entries. If the current PDF cannot be verified/downloaded, it suppresses the image and disables page rendering. An unchanged verified identity reuses its cached image without rerendering the PDF.

Regression verification first reproduced six stale-image failures (changed document/XML/page/working-PDF bytes, legacy unbound bytes, and unavailable PDF); the unchanged-identity case passed. After the fix:

- `.venv-corpus/bin/python -m pytest tests/test_app_flows.py -q -k 'source_page_cache or legacy_unbound or unavailable_pdf'` → **7 passed, 14 deselected**.
- `.venv-corpus/bin/python -m pytest tests/test_app_flows.py -q` → **21 passed**.
- `.venv-corpus/bin/python -m py_compile app.py ui/*.py` → passed.

This correction changes only `ui/common.py`, the focused regression cases in `tests/test_app_flows.py`, and this report. It makes no cloud calls and changes no backend, review, or publication state.
