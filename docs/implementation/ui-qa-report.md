> Historical pilot report. Current bulk-library behavior and release evidence are in [the bulk refactor release report](bulk-refactor-release-report.md). Original observations below are retained for traceability.

# UI QA report

Scope: `ui/common.py`, `ui/explore.py`, `ui/learn.py`, `ui/sources.py`, and `tests/test_app_flows.py`. App navigation and native-browser inspection remain with the root worker. No live reviews, publications, provider requests, or source changes were performed.

## Reproduced and corrected

| Finding | Cause and correction | Regression coverage |
| --- | --- | --- |
| Source scope repeated its filename | XML source scope can equal the filename. Suppress that redundant hint in the selector, source cards, review details, and citations; preserve real variant hints. | Filename-valued hint renders once. |
| A withheld explanation with a reviewed quotation said “Not found in this library” | `abstained` also represents unavailable/unverified generation and safety declines. Use “Source excerpt · explanation not verified” when citations exist, and “Explanation withheld” otherwise, both immediately and after reruns. | Source fallback and safety-decline UI branches. |
| Identical supporting quote and full passage appeared twice in a citation | Render the full passage separately only when it differs from the supporting quote. | Exact quote appears once, including on rerun. |
| Exact source text lost surrounding whitespace and indentation | Streamlit `st.text` dedents and strips its input. Render escaped, preformatted HTML for source passages and exact embedding text, preserving text content and keeping markup inert. | A quote containing boundary newlines, indentation, angle brackets, ampersands, and a dose/unit survives HTML parsing exactly. Real extracted text retains its final newline. |
| Selecting an unpublished source enabled chat and quizzes | Readiness checked product membership only. Also check explicit published document membership; an explicitly empty document set cannot enable chat. | Unpublished selected document and empty published-document scope disable actions. |
| Review decision defaulted to `needs-review` for accepted passages | Initialize the decision selector from the recorded review status. Viewing the page never saves a review. | Existing accepted status remains selected without a write. |
| Accidental outer spaces hid catalog matches | Trim the search input before matching brand/generic names. | A generic-name query with outer whitespace still finds its medicine. |
| Quiz feedback stayed “Correct” after choosing another answer | Bind feedback to the answer that was checked and require a fresh check after a change. | Switching to an unchecked wrong answer hides stale feedback; checking displays the right feedback. |
| Published content was presented as live-chat readiness | Label catalog content “Published sources” and sidebar state “Published library”; state that chat also needs configured connections. | Existing missing-credential tests continue to disable chat. |

## Rerun and interaction checks

Existing UI tests continue to cover explicit Build XML, connection tests, review submission, staging, publication, quiz generation, answer generation, and re-explanation; none repeat on an ordinary rerun. Added checks verify separate histories for different document scopes, restoration when returning to the same scope, and safe selection reset when a selected source disappears.

Two integration checks use the actual `ExplorerService` with PDF/XML generated under pytest's temporary directory:

- Browse an unpublished collection, inspect extracted text, download its PDF, and render original page 1. A transport guard rejects accidental provider calls. Browsing leaves no accepted reviews or active release.
- Create one temporary review and immutable snapshot, supply offline retrieval evidence, and simulate a provider outage at the HTTP boundary. The actual answer/teaching pipeline renders its reviewed quotation, preserves the exact text, labels the fallback accurately on rerun, and opens the pinned original page. Dummy credentials exist only in memory within this test; no live provider or publication is used.

## Verification

- `python -m pytest tests/test_app_flows.py -q`: **32 passed**.
- `python -m pytest -q`: **183 passed, 21 subtests passed** (combined tree at handoff).
- Five dependency deprecation warnings concern PyMuPDF SWIG types; no application errors were reported in the focused run.

Limitations: AppTest verifies component output and state, not final browser layout. The root worker owns Chrome visual QA, live-provider smoke checks, demo navigation, and final combined-suite verification.
