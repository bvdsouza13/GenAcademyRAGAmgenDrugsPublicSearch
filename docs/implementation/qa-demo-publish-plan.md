> Historical pilot report. Current bulk-library behavior and release evidence are in [the bulk refactor release report](bulk-refactor-release-report.md). Original observations below are retained for traceability.

# QA, demo and GitHub publication

User authorized thorough testing, automatic fixes, a short demo, local launch and upload to https://github.com/bvdsouza13/GenAcademyRAGWeek2.git.

Design decision: a three-minute read-only guided tour within the existing Streamlit app. Prepared source-backed examples are explicitly labeled; entering or navigating the tour never calls paid providers, approves content, changes reviews or publishes a corpus. An optional live action must be explicit. The tour should work in a fresh clone with the supplied source XML/PDFs and no credentials, using a portable prepared example. Session-only Next/Back/Restart/Exit controls. Route `?demo=1` opens it directly.

Work ownership:
- Backend QA worker: amgen_explorer backend (except new demo module), tests backend/service/evaluation. Find concrete defects, reproduce then fix; no live state changes.
- UI QA worker: ui/common.py, explore.py, learn.py, sources.py, tests/test_app_flows.py. Fix text, scope/status, edge-state/rerun bugs. Root owns app.py and demo navigation integration.
- Demo worker: new ui/demo.py, amgen_explorer/demo.py if needed, demo fixtures, tests/test_demo.py, docs/demo.md. Root wires navigation/app. Avoid other workers' files.
- Root: Git initialization/publication, ignore/secrets checks, app.py/nav integration, browser QA, live source/connection tests, packaging/CI/docs and final verification.

Verification: existing suite baseline; focused regressions per finding; all tests after integration; validate original37PDF/1439pages read-only; actual provider smoke; fresh-clone/no-key demo smoke; browser catalog, search, chat, source PDF, management and demo controls; remote commit matches local.

Publication: preserve the current local live corpus and credentials; never push secrets, virtual environments, local SQLite/manifests/runtime snapshots, temporary files or logs. Include application/tests/docs/portable demo and supplied source artifacts needed to reproduce the app. Scan staged blobs for actual saved secret values and key-like patterns before committing. No force push or remote deletion.

Progress: baseline started; GitHub confirmed public empty repository with push permission; no local git repository yet. Implementation/review in progress.
