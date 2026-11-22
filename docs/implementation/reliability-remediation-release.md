# Reliability remediation release — 22 November 2026

The user approved all eight remediation areas. The existing Streamlit, consolidated XML, Pinecone and OpenAI architecture remains in place. Administration still builds the whole library; learners search all content and select a source when starting a lesson. This report records implemented fixes and their practical limits.

## What changed

| Area | Original gap | Implemented behavior |
| --- | --- | --- |
| 1. Search relevance and evaluation | Conversational medicine questions matched boilerplate; unrelated neighbors appeared useful; scoring hid noisy results. | Query interpretation recognizes names, meaningful qualifiers and ambiguity. Relevant passages rank first; typos require an explicit choice. A frozen 51-case learner suite measures visible precision, graded relevance, clarification and no-results behavior without hidden answer filters. |
| 2. Provider readiness and bounded failures | Model access could be mistaken for working generation; retries and late responses were poorly characterized. | Explicit Admin readiness separates source reading, semantic search, model access and verified generation. Learning has a 60-second cooperative deadline. Bounded retries honor valid Retry-After values; authentication failures are not retried. Late or unverified output becomes source reading. |
| 3. Pinecone verification and repair | A previously successful build could hide subsequently missing or altered remote records. | Verify compares every expected record and checks all document scopes. Repair restores identical pinned records, checkpoints progress and verifies again. Provider outages are distinguished from missing data. Run identity and original source pins remain immutable. |
| 4. Local recovery | Corrupt XML, replaced PDF bytes, malformed history or a broken active pointer could block the UI. | Recovery remains reachable, restores validated retained versions and regenerates working XML from registered PDFs. Reuploading original PDF bytes repairs local corruption. Damaged history is isolated. Demo remains available without live configuration. |
| 5. Evidence selection and outage fallback | Overview evidence was crowded out; continuation fragments were unsafe; teaching lacked equivalent local fallback. | Complete continuation groups are selected together, with relevant section allocation and preserved qualifiers. Local retrieval retains the same document/device scope and source validation. Generated claims still require exact quotes and independent entailment checks. |
| 6. Follow-ups and quizzes | Generated follow-ups could introduce treatment instructions; personal requests bypassed routing; quizzes had predictable positions and inconsistent restrictions. | Vetted follow-ups and deterministic educational routing run before provider calls. Quizzes use the shared evidence policy, shuffle once and preserve options, answers and grading across reruns. |
| 7. Extraction and page coverage | One nearby table/figure could restrict clean narrative; text coverage was incomplete or misleading. | Native geometric regions separate clean text where supported. Every source page is accounted for. Genuine table, figure or multicolumn uncertainty remains visible and source-only. Parser/layout-policy changes create a new verified candidate. |
| 8. Operations, retention and capacity | Usage/storage boundaries and retained-version safety were unclear. | Inventory shows local storage and recorded provider usage with unknown costs labeled. Repair accounting is separate from ingestion. Cleanup stays disabled because durable historical publication and conversation references cannot yet prove any version unreferenced. One/five-reader capacity measurements and operational limits are documented. |

All 23 original failing diagnostic instances are now normal regression tests. The eleven implementation tasks are traced in the [approved plan](../superpowers/plans/2026-11-22-reliability-remediation.md).

## Source and live verification

The new consolidated XML uses `text-layer-layout-v3` and `native-geometric-boundaries-v1`. Its SHA-256 is `f6b6786246c8bcd09233ead3e4f2d675886f7bf4df23b8d68d2904df435e41cc`. The candidate run is `47b75fa785673734b5c00c994c6b289fc211e85694271d11bfc6c51f487c0742`.

- 37 PDF documents, 36 medicines and 1,439 pages; native text was detected on all 1,439 pages. This does not establish completeness of figure/table semantics.
- 10,641 records with the application's unchanged 600/80 chunk configuration and metadata prefix. Every expected remote record matched, and every document scope was searchable before activation.
- Candidate activation, rollback to the previous run and reactivation passed. Retrieval against the previous run still resolved its original XML hash and source PDFs after activation.
- The frozen live learner evaluation completed without degraded search: all 14 behavioral cases passed and every returned citation resolved. Development precision@5 was 0.8487; holdout precision@5 was 0.7167. These are fixture-based relevance measurements, not clinical accuracy scores. The pre-ranking local baseline was 0.20 and 0.15 respectively; extraction changed for the final candidate, so that comparison includes both changes.
- All 37 source-scoped mechanism probes retained valid provenance: 29 were eligible for generation and eight correctly remained source-only because of relevant layout restrictions. Those eight scopes were Enbrel, Kyprolis, Lumakras, Parsabiv, Ravicti, Tavneos, Tepezza and Tezspire. Eligibility is not a promise that every stochastic generation attempt passes verification.
- Live ACTIMMUNE and Repatha examples produced verified explanations; Tezspire preserved its expected source fallback. The final strengthened live smoke check passed all four search checks and all three teaching contracts. Personal treatment examples redirected before provider use. A subsequent ACTIMMUNE readiness attempt fell back despite successful authentication and semantic search; the application reported readiness incomplete. Successful access alone never establishes answer readiness.

The original OpenAI credential incident was resolved before these code changes. Both configured credentials and the existing Pinecone index were accessible during release testing. No secrets were added to source control and no real active records were deleted for fault simulation.

## Regression and release evidence

The final working-tree regression passed **612 tests and 21 subtests**, with zero network attempts and no xfails, using `scripts/test_offline.py --shuffle-seed 20261123` (81.60 seconds). Five warnings originate in upstream PyMuPDF/SWIG bindings. The final review found and then approved fixes for readiness presentation, smoke-test fallback enforcement and repair accounting. Clean-checkout verification and local release integration follow this commit.

Independent package reviews covered search/retention, recovery, teaching/operations and extraction. The whole-branch review preserved immutable sources and verified that the 37 legacy provenance-fixture updates changed only XML hashes/block IDs, not questions, quotes or PDF hashes. The frozen learner suite was not relabeled after observing holdout results.

Local reports are retained under ignored `output/remediation/`: `candidate-run.json`, `live-candidate-discovery.json`, `live-candidate-probes.json`, `live-candidate-teaching.json`, `activation-rollback-check.json`, test logs and capacity reports. These contain machine-specific runtime evidence and are not required by a fresh checkout.

Reproduce the principal checks:

```sh
.venv-corpus/bin/python scripts/test_offline.py --shuffle-seed 20261123
.venv-corpus/bin/python scripts/manage_corpus.py verify-library
.venv-corpus/bin/python scripts/manage_corpus.py readiness
.venv-corpus/bin/python scripts/live_library_check.py --chat
```

Live commands consume provider requests. Use `--help` for command options; no provider checks run simply by opening or rerendering a page.

## Confidence and remaining boundaries

Confidence is high for the tested local workflows and failure recovery contracts. It is lower for arbitrary questions, new PDF layouts and sustained concurrent use. Exact-source checks establish provenance; they do not certify medical accuracy, current labeling or the judgment labels in the search evaluation.

The [capacity report](retention-capacity.md) measured roughly 623 ms median warm local search with one reader and 3,757 ms with five concurrent readers, with a 3.33 GiB process peak. That benchmark used the previous 9,110-record corpus, shared threads and one rendered PDF page; it does not include browser rendering or establish hosting capacity. On the final candidate, one sequential comparison measured full history status at 12.595 seconds and learner status at 4.481 seconds. Home now defers retained-history inspection to Admin/Recovery; active library and source checks still run. These status timings are not full browser latency and indicate room for further performance work.

Remaining capabilities are full OCR, clinician-reviewed evaluation/current-label certification, durable publication/conversation reference tracking before cleanup, and authenticated shared hosting. No data was cleaned up. The app remains bound to `127.0.0.1`. See [future features](../future-features.md) for the next development priorities.
