> Historical pilot report. Current bulk-library behavior and release evidence are in [the bulk refactor release report](bulk-refactor-release-report.md). Original observations below are retained for traceability.

# Connectivity, ingestion, retrieval and teaching implementation

Implemented `amgen_explorer/connectivity.py`, `indexing.py`, `retrieval.py`, `teaching.py`, `scripts/check_connections.py`, and four provider-free feature test files.

## Provider contract

Pinecone uses the existing Documents API index, pinned to `2026-07`, through Python standard-library HTTPS. No Pinecone SDK dependency is required. There is no legacy Records/Vectors fallback and no automatic index creation. Every load and publication validates the actual configured index/schema with the existing setup helper before document writes or active-pointer changes.

Verified primary documentation on 2026-11-11:

- [Upsert documents](https://docs.pinecone.io/reference/api/2026-07/data-plane/upsert_documents): POST `/namespaces/{namespace}/documents/upsert`, JSON `documents` containing `_id`, text field and flat metadata; confirm `upserted_count`.
- [Fetch documents](https://docs.pinecone.io/reference/api/2026-07/data-plane/fetch_documents): POST same prefix `/fetch`, JSON `ids` and `include_fields`; returns `documents` ID map.
- [Search documents](https://docs.pinecone.io/reference/api/2026-07/data-plane/search_documents): POST same prefix `/search`, `top_k`, `score_by`, `filter` and `include_fields`; returns `matches`.
- [Integrated embedding](https://docs.pinecone.io/guides/search/integrated-embedding): scoring clause `type=embed`, `fields=[chunk_text]`, `query=...`.

The root worker separately verified the actual user's index and OpenAI model. This worker made no cloud mutations or paid model calls. Existing index truncation is `END`; local guards reject all document/query inputs whose UTF-8 byte count plus eight exceeds 2,048. This is explicitly a conservative token upper bound, not an exact tokenizer count.

OpenAI uses `/v1/responses`, `store=false`, configurable model/reasoning/output budget, user `input_text`, and strict JSON schema in `text.format`. Incomplete responses never publish partial clinical answers. A teaching answer uses two requests: generation and a separate evidence-entailment check. The read-only connection CLI checks index compatibility and model availability without generation.

## State and publication

Constructors and preview/runs/active reads do not create files or call providers. Run IDs hash the complete pinned plan, exact records and index profile. Namespaces use those deterministic IDs. Each run retains immutable candidate records and an atomic JSON status manifest. SQLite persists batch attempts/completed checkpoints. A kernel process lock protects the database target; its owner PID/start is also recorded in SQLite. Crash releases the kernel lock, and the next explicit load resumes persisted completed batches. Retries are bounded and deterministic upserts avoid duplicate IDs; embedding retries may incur provider charges. Actual reported embedding-token counts are recorded, with a flag when retry usage may be unreported.

All records must be explicitly accepted and have product/document/hash/section/page provenance. Metadata is flat, finite and <=40 KB. Batches respect 96 records and configured JSON byte limits. Verification fetches every record and compares every expected field/text, then performs a filtered search sentinel for every document scope. Only complete verified runs are publishable. Load never changes the active pointer. Publish requires a fresh reviewed plan matching the run and repeats verification; active-pointer replacement is atomic. Rollback similarly verifies the retained run and current index profile. No cleanup/deletion is performed.

Run manifest states: `indexing`, `verifying`, `failed`, `verified`. Fields include `run_id`, `namespace`, `xml_hash`, `config_hash`, `review_hash`, `record_count`, `succeeded`, `failed_ids`, `product_ids`, `document_ids`, `profile`, `index_host`, `embedding_model`, `records_path`, timestamps and usage. A published active manifest retains `status=verified` and adds `published_at` and `previous_run_id`.

## Evidence and teaching

Search always filters by selected product, pinned XML hash and concrete document scope. Multiple document/device scopes require selection. Search hits must exactly match their immutable local records, including text and provenance. There is no global fallback. Complete evidence passages are added within a conservative byte-based token budget without hidden truncation. Safety and overview prompts supplement semantic hits from canonical reviewed safety sections; absence is explicit.

Teaching validates source scope, exact support quotations, citation IDs, numeric preservation and absence of model-supplied citation markers, then requests an independent entailment verdict. An invalid citation, unsupported verdict, incomplete provider response or request failure withholds the generated explanation. The abstention can still display one complete exact reviewed source quotation with its real citation, explicitly labeled as source reading rather than a verified explanation. Provider failures remain explicit; usage flags identify `explanation_verified=false`, `source_fallback=true`, and provider problems. Safety/out-of-scope abstentions do not display this fallback. Personal dosing/treatment, comparison/interchangeability, fabricated citations and pricing requests receive deterministic scope/safety abstention. Safety questions require actual reviewed safety evidence. Citation metadata includes source PDF filename/hash, pages, section, revision or `revision not identified`, exact passage and support quote. Plain/technical modes consume the same evidence contract. Quizzes are extractive source-reading exercises with exact cited rationales and no model calls.

## Validation and remaining limits

Command: `.venv-corpus/bin/python -m pytest tests/test_connectivity.py tests/test_indexing.py tests/test_retrieval.py tests/test_teaching.py -q`

Result: **49 passed**, provider-free. Coverage includes retry/interruption/resume, duplicate clicks, no initial filesystem writes, staged-only loads, atomic publication/rollback, stale reviews/profile rejection, eventual visibility failure, input/metadata limits, exact REST shapes, source/product isolation, variant ambiguity, source tampering, canonical warnings, complete-passage evidence budgeting, invalid citations/quotes/numbers, personal advice, model failure/incompletion, source-instruction isolation and sanitized connection failures.

Limits: entailment remains a model-based check, not a clinical review or proof. Full semantic answer quality and safety-critical recall require the separately reviewed evaluation set and real reviewed pilot. The byte guard is deliberately conservative and may create more/smaller chunks than a locally available exact tokenizer. Quiz distractors are general unsupported inferences; this is a source-reading check rather than a broad clinical assessment. PDF review authorization, source-file hash checking and revoked-review enforcement are performed by the root service facade. A hosted/multi-machine deployment needs durable shared storage and a distributed job lock; this implementation is local single-host.

## Live-pilot follow-up hardening

The root worker reported an actual six-chunk reviewed pilot successfully fetched, searched and published; Repatha and Tezspire explanations passed generation/entailment, while an Aimovig paraphrase was rejected. The source-reading fallback now gives a useful exact quotation in that rejected-explanation state while preserving `abstained=true` and withholding every unsupported generated word. Regression tests cover verifier rejection, unsupported paraphrase removal and explicit provider outages.

Immutable record integrity now recomputes the original deterministic run ID from the full records, plan fingerprint and profile before retrieval, publication or idempotent reuse. It also checks configured index/embedding profile, derived namespace, canonical records path, unique IDs, exact product/document sets, accepted review state and matching XML/review/chunk configuration pins. Modified content with an unchanged record count is rejected before search/publication. The existing live six-record active manifest passes these checks without migration (local read-only verification).
