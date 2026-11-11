> Historical pilot report. Current bulk-library behavior and release evidence are in [the bulk refactor release report](bulk-refactor-release-report.md). Original observations below are retained for traceability.

# Implementation contracts

Root: the repository directory.
All agents share files. Python `.venv-corpus/bin/python` is 3.12. Do not print/read secrets into tool output. No git repo. No nested workers. Write tests using pytest; existing unittest tests remain. Root manages requirements/install and app facade. Shared dataclasses are in `amgen_explorer/models.py`; extend only compatibly and notify root.

## Corpus worker owns
`extraction.py`, `xml_store.py`, `review.py`, `chunking.py`, `scripts/build_amgen_xml.py`, XML schema/guide and its tests.
Provide `load_corpus(path)->Corpus`; `build_corpus(source_dir, output_path)->BuildReport` reuses extractor with atomic snapshot; `ReviewStore(path)` with `record(block, decision, reviewer, note="")`, `status(block)->str`, `fingerprint(corpus)->str`, `summary(corpus)->dict`. Decisions accepted/rejected/needs-review, hash scoped.
`ChunkConfig(target_tokens=600, overlap_tokens=80, prefix_template=...)` accepts defaults; `.as_dict()` and `.fingerprint()`; `prepare_chunks(corpus,reviews,config)->ChunkPlan`. No cloud calls. Named config save/load helpers optional. Exact-token check available through tokenizer function; never mislabel approximation as exact. Unknown facts remain unknown.

## Services worker owns
`connectivity.py`, `indexing.py`, `retrieval.py`, `teaching.py`, feature tests and CLI connectivity/live test script. Reuse config and setup helpers. Root will communicate actual API capabilities. Own provider SDK/REST exact shapes and mocks.
`check_connections(config)->dict` sanitized result, keys never printed.
`IndexService(config)` methods `preview(plan)->dict`, `ingest(plan,on_progress=None)->dict`, `activate(run_id,current_plan=None)->dict`, `active()->dict|None`, `runs()->list[dict]`, `rollback(run_id)->dict`. Atomic manifests; stage/verify/explicit activate; deterministic IDs; persistent retry; no writes on init. Current-plan check before publication.
`retrieve(question,product_id,active,config,document_id=None)->EvidenceBundle` always selected product, namespace and XML hash pinned; source citation metadata from chunks. Can accept client optional for tests.
`teach(question,evidence,config,mode="Plain language",history=None)->TeachingResponse`, `make_quiz(evidence,config)->dict`, `OpenAIClient` configurable transport. Do not hallucinate when no evidence. Claims require valid citations; JSON structured answer/citations preferred. Guard scope/personal dosing; same evidence for detail switch. Source text untrusted. Tests use fake providers.

## UI worker owns
`app.py`, `ui/*`, `tests/test_app_flows.py`. Use mockups and existing real logo. Root provides `amgen_explorer/service.py` facade `ExplorerService(config=None)` with `.config`, `.corpus()->Corpus|None`, `.inventory()->list[dict]`, `.reviews` property ReviewStore, `.index` property IndexService.
Methods `.build()->BuildReport`, `.connection_status()->dict`, `.chunk_config(target_tokens=600,overlap_tokens=80)->ChunkConfig`, `.preview(chunk_config,product_id=None,document_id=None)->ChunkPlan`, `.review(block_id,decision,reviewer,note="")`, `.load(plan,on_progress=None)->dict`, `.publish(run_id,plan)->dict`, `.active()->dict|None`, `.answer(question,product_id,mode="Plain language",document_id=None,history=None)->TeachingResponse`, `.quiz(product_id,document_id=None)->dict`, `.save_preset(name,chunk_config)`, `.presets()->dict`, `.compare(run_a,run_b,questions,product_id)->dict`, `.rollback(run_id)->dict`.
UI can access corpus dataclasses. `.index.runs()` lists manifests. `.load` stages and verifies only; publish separate explicit action. Active product IDs from active manifest `product_ids`. If no reviewed content show honest state, not fabricated answer. Render citation source filename/pages and local PDF download with safe path handling. Source review explicit, show passage and PDF and its status. Controls no paid calls on rerun. Connections only button triggered. Persist chat/progress in session_state only.
Root will provide `.source_pdf(document_id)->bytes` and `.source_page(document_id,page)->bytes` helpers and `.answer` robust citation metadata. Quiz format: `{question, choices: list[str], correct_index:int, rationale, citations:list}` or `{error}`.
