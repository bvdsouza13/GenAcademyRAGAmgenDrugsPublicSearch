# Amgen Medicine Explorer Implementation Plan

> Implementation handoff: the local app and limited live pilot are now running. This document retains the original planning checklist, including broader clinical-release criteria. See [README](../../../README.md), [implementation ledger](../../implementation/progress.md) and [pilot report](../../../evals/pilot-report.md) for verified delivery status and explicit limitations.

> **For agentic workers:** Use `superpowers:subagent-driven-development` or `superpowers:executing-plans` to implement the future application task by task. Checkboxes below describe planned work; the presence of the initial XML artifact does not mean the complete application exists.

**Goal:** Build an Amgen-branded Streamlit learning app that creates one XML collection from local prescribing-information PDFs, loads reviewed passages into Pinecone, and answers learning questions with citations.

**Architecture:** Local Python extraction produces the canonical XML before indexing begins. A review/chunking layer converts eligible XML content into Pinecone search records. Streamlit calls the same backend services as the command-line tools, and the chat layer uses only retrieved, cited evidence from the active corpus.

**Tech stack:** Python, Streamlit, PyMuPDF for initial PDF text extraction, XML parsing/validation, Pinecone's supported Python client/API, a configurable language-model client, and pytest for meaningful pipeline/retrieval checks. Pin compatible versions in a lockfile when the app is implemented.

**Spec:** [Proposed design](../../amgen-medicine-explorer-design.md). [Technical reference notes](../../technical-plan-notes.md) contain current service documentation and constraints. Date: November 11, 2026.

**Setup now available:** `config/app.toml`, `amgen_explorer/config.py`, `scripts/check_config.py` and `scripts/setup_pinecone.py` provide shared configuration, offline validation and explicit empty-index setup. The user selected the OpenAI API for explanations. Read the [configuration guide](../../configuration-and-pinecone-setup.md) and [architecture diagrams](../../architecture.md); reuse the supplied loader and Pinecone schema contract when implementing the application. These utilities do not implement ingestion or the chat UI.

## Global constraints

- Audience: general learners, plain language first, optional technical detail.
- Source directory: `Documents/`; canonical consolidated file: `XML/AmgenProducts.xml`.
- Preserve `urn:local:pi-corpus:1`; the custom XML is not FDA SPL.
- Initial inventory: 37 PDFs, 36 base products, 1,439 physical PDF pages; derive displayed counts at runtime.
- The template's referenced XSD and tag guide are absent. Do not claim XSD validation until an explicit compatible schema exists.
- Retain both Repatha documents. A filename is not evidence of exclusive device applicability or supersession.
- Clinical facts remain unknown or unreviewed until supported. A successful parse is not clinical review.
- XML creation is local and separate from cloud indexing; rebuilding cannot silently upload data.
- Do not put secrets in source code, XML, search metadata, browser markup, logs, or shared caches.
- No public deployment, personal prescribing, or patient data collection in the initial scope.

## Review focus

1. Multi-column highlights, tables, diagrams and footnotes can yield readable but incorrect text order; block unresolved fragments from factual answer generation.
2. The two Repatha files overlap in presentation coverage; a question about latex must resolve the relevant passage/device, not just the filename.
3. A partial upload, UI rerun or process interruption must not duplicate records or activate an incomplete corpus.
4. A label revision, document hash, schema version or embedding configuration change must invalidate affected cached/indexed data.
5. A superficially similar retrieved passage can fail to support a clinical claim; test citation support and abstention, not just non-empty search results.

## Planned file boundaries

| File or directory | Responsibility |
|---|---|
| `scripts/build_amgen_xml.py` | Initial reproducible local extraction entry point |
| `amgen_explorer/models.py` | Shared typed contracts for documents, chunks, citations and reports |
| `amgen_explorer/extraction.py` | Reusable extraction and consolidated XML assembly |
| `amgen_explorer/xml_store.py` | Safe XML loading, validation, IDs and source lookup |
| `amgen_explorer/review.py` | Review decisions and eligible content selection |
| `amgen_explorer/chunking.py` | Section-aware passages with exact source spans |
| `amgen_explorer/indexing.py` | Pinecone adapter, batch loading and manifests |
| `amgen_explorer/retrieval.py` | Product resolution, scoped search and evidence assembly |
| `amgen_explorer/teaching.py` | Cited answers, lessons and quizzes |
| `app.py`, `ui/explore.py`, `ui/learn.py`, `ui/sources.py` | Streamlit navigation and three user workflows |
| `.streamlit/config.toml` | Brand theme; never credentials |
| `data/review.sqlite`, `data/ingestion.sqlite` | Local review and ingestion state |
| `tests/`, `evals/` | Failure-mode tests and reviewed learning-question set |

The package files above are planned. Start by extracting reusable logic from the initial script rather than maintaining a second PDF extractor.

## Task 1 — Make XML assembly reproducible and reviewable

**Files:** `scripts/build_amgen_xml.py`, `amgen_explorer/{models,extraction,xml_store}.py`, `tests/test_xml_pipeline.py`, `XML/prescribing-information.xsd`, `XML/xml-tag-guide.md`.

**Interfaces:** `build_corpus(source_dir: Path, output_path: Path) -> BuildReport`; `load_corpus(path: Path) -> Corpus`. `BuildReport` includes input/document/product/page counts, failed files/pages, warnings, schema-check status and output hash. `Corpus` retains document records, source evidence and extraction status.

- [ ] Audit the initial extraction script and report. Preserve the exact page text and per-document SHA-256 already generated.
- [ ] Define and document a local schema compatible with the supplied template and any explicitly documented extensions. Validate the template and generated output against it; never replace absent facts with placeholder values to satisfy the schema.
- [ ] Move extraction into the reusable service while keeping the CLI operational. Write to a temporary file, validate, then atomically replace the consolidated file; preserve a content-addressed prior snapshot for rollback.
- [ ] Extract full-PI headings, section numbers, label metadata and evidence-backed fields. Record layout, OCR, table and figure limitations explicitly. Use OCR only for pages without usable text, with page-specific status.
- [ ] Test corrupt PDFs, a blank/scanned page, XML special characters, duplicate source files, unknown metadata and the two distinct Repatha inputs. Assert that source text and page attribution survive round-trip and that no unsupported clinical field is marked reviewed.
- [ ] Run `pytest tests/test_xml_pipeline.py -q`; inspect the extraction report and representative rendered PDFs. Deliver the XML, report, schema/tag guide and reproducible command.

**Acceptance:** All files/pages are accounted for, references resolve, original source hashes match, and schema success is distinguishable from clinical-review status.

## Task 2 — Review passages and prepare searchable chunks

**Files:** `amgen_explorer/{models,review,chunking}.py`, `tests/test_review_and_chunking.py`, `data/review.sqlite`.

**Interfaces:** `record_review(document_sha256: str, block_ids: list[str], decision: ReviewDecision) -> None`; `prepare_chunks(corpus: Corpus, reviews: ReviewStore, config: ChunkConfig) -> ChunkPlan`. `ChunkPlan` includes eligible `Chunk` objects, excluded block IDs/reasons and a deterministic corpus fingerprint.

`Chunk` fields: stable ID, text, product ID, document ID/hash, source variant hint, verified variant IDs if known, section ID/title/kind, block IDs, physical page range, review state, verified label revision if known, content hash and parser/chunking version. Missing values remain missing rather than invented strings or dates.

`ChunkConfig` fields: `strategy="section_aware"`, `target_tokens=600` (allowed 300–1,200), `overlap_tokens=80` (allowed 0–200 and below target), tokenizer/version, prefix template/version, chunker version and required scope/provenance policy version. Compute a stable configuration hash from canonical serialization. The model cap includes the contextual prefix and remains a separate hard constraint, measured with the embedding model's tokenizer.

- [ ] Define review decisions as accepted / rejected / needs-review, with reviewer, timestamp, PDF hash, passage hash, evidence coordinates, pipeline version and block/fact scope. A changed PDF or extraction invalidates affected approvals. Bulk approvals must show their scope explicitly. An accepted raw passage may be eligible while unrelated normalized fields remain unknown.
- [ ] Split accepted content at section boundaries, using configurable `ChunkConfig` defaults of 600 tokens and 80 tokens overlap. Preserve sentence/qualifier context, exact source spans and full coverage rather than deriving page citations from chunk index or silently truncating text. Enforce parameter ranges and the actual model-token ceiling including prefixes.
- [ ] Keep tables with headers, units and footnotes; exclude unresolved table fragments. Separate highlights, full PI, medication guide and instructions for use. De-duplicate retrieval evidence without deleting the original source text.
- [ ] Generate deterministic IDs from document/content hashes, section/block spans and chunking version. Metadata preparation must obey the target Pinecone field types and size limits.
- [ ] Include `chunk_config_hash` in the chunk metadata, manifest and staged-corpus fingerprint. Save named configurations and local previews; unchanged source-passage approvals can be reused, while all newly assembled chunks must pass completeness/scope/provenance checks.
- [ ] Test two-column artifacts, a table footnote, an unreviewed boxed warning, cross-page sections and variant ambiguity. Assert unresolved content is excluded, all accepted chunks have valid provenance and no chunk joins separate products/documents.
- [ ] Add parameterized cases for zero overlap, overlap at/above target, out-of-range settings, a table row too large for the model, an oversized sentence with a qualifier, config-hash changes and identical-config determinism. Assert all source text is accounted for and no truncation is hidden.
- [ ] Run `pytest tests/test_review_and_chunking.py -q` and inspect the chunk preview for three representative medicines.

**Acceptance:** A reviewed pilot subset can be indexed without pretending the entire 1,439-page corpus is clinically reviewed. Catalog availability and chat availability are separate states.

## Task 3 — Add explicit, resumable Pinecone ingestion

**Files:** `amgen_explorer/{models,indexing}.py`, `tests/test_indexing.py`, `data/ingestion.sqlite`, `.env.example` or `.streamlit/secrets.toml.example`.

**Interfaces:** `preview_index(plan: ChunkPlan, config: IndexConfig) -> IngestionPreview`; `run_ingestion(preview: IngestionPreview, on_progress: Callable) -> IngestionReport`; `activate_corpus(run_id: str) -> ActiveCorpus`. `IndexConfig` pins API family/version, index host, namespace strategy, embedding model/dimension/metric and metadata schema version. `IngestionReport` records attempted/succeeded/failed IDs and verification state.

- [ ] For a new index, use the Documents API (`2026-07` or later) and a tested Pinecone Python SDK release at least `10.1.0`, after checking target-account capabilities. An existing legacy vector index requires its own compatible adapter. Never mix request shapes.
- [ ] Configure integrated `llama-text-embed-v2`, 1,024 dimensions, cosine and `truncate=NONE` for the initial new index. Enforce the model's 2,048-token input limit including the context prefix. Use the same profile for query embedding; external embeddings remain an explicit alternate adapter. Evaluate this baseline on the labels rather than assuming domain performance.
- [ ] Validate metadata before upload. Store compact flat fields and text as supported by the chosen API; keep complete nested XML and original PDFs in the canonical store.
- [ ] Build a staging namespace per corpus/configuration fingerprint. Persist the upload manifest and checkpoints, retry transient failures with bounded exponential backoff, and use deterministic upserts for idempotency. Acquire one job lock per target so UI reruns do not start competing imports.
- [ ] Preview record count, eligible/excluded sources, estimated tokens and destination before the Load action. Begin at 64 chunks per integrated-embedding batch; enforce the maximum 96 records and 2 MB payload as well as model token limits. Enforce flat metadata at no more than 40 KB per record. Respect backpressure and rate limits.
- [ ] Wait for searchable consistency with a bounded verification loop, check expected records and sentinel queries, then atomically update the application-owned `data/active-corpus.json` pointer selected by the initial configuration. A Pinecone alias adapter can be added later. Retain the prior active namespace for rollback; cleanup is a separate explicit maintenance action.
- [ ] Allow a saved chunking configuration to build a test namespace without activation. Compare two configurations using pinned identical XML/review snapshots, held-out questions, embedding profile, retrieval method, generation settings and evidence-token budget. Evaluate evidence by source spans rather than chunk IDs, which change with chunk boundaries. Preserve complete table context and measure duplicate coverage from overlap. Show citations/qualifiers, latency and actual usage; require explicit Publish configuration after verification, and invalidate previews/test comparisons when inputs change.
- [ ] Test with a fake adapter: interrupted batches, retryable errors, duplicate clicks, stale review state, incompatible model dimensions and missing secrets. Assert failure cannot change the active corpus and resumed runs cannot create duplicate IDs.
- [ ] Run `pytest tests/test_indexing.py -q`. Once credentials exist, run an integration check against a clearly named development index using a small reviewed corpus.

**Acceptance:** A complete verified import becomes searchable; an incomplete import remains staged and reports recoverable failures. No credentials or paid resources are required for offline tests.

## Task 4 — Implement product-scoped search and cited teaching

**Files:** `amgen_explorer/{models,retrieval,teaching}.py`, `tests/test_retrieval.py`, `tests/test_teaching.py`, `evals/questions.jsonl`.

**Interfaces:** `retrieve(question: str, scope: QueryScope, active: ActiveCorpus) -> EvidenceBundle`; `teach(question: str, evidence: EvidenceBundle, mode: ExplanationMode) -> TeachingResponse`. `QueryScope` contains selected product, any verified variant and document/version constraints. `TeachingResponse` contains answer blocks, source citations, uncertainty/abstention state and suggested follow-ups.

- [ ] Resolve brand/generic names against the verified catalog. Ask for clarification when the generic covers multiple products or device/version scope matters. Do not search globally after a product filter yields no evidence.
- [ ] Resolve the active corpus once per answer and pin its concrete namespace and XML hash through search and citation resolution. Search with metadata filters, use exact-name/section matching where helpful, assemble related passages and optionally rerank. Treat candidate counts as evaluation-tuned configuration, not proof of reliability.
- [ ] Produce short plain-language answers by default and a technical expansion from the same evidence. Source references must resolve to document/hash/section/page and support their associated claims.
- [ ] For overview lessons, include safety context from appropriate verified sections. If relevant safety evidence is unavailable, explain the limitation; do not imply the drug has no warning. For factual questions without sufficient evidence, abstain.
- [ ] Add lesson progression and one-question-at-a-time quizzes with cited rationales. Keep model/provider selection configurable; cache shared corpus artifacts, not another user's conversation.
- [ ] Build at least 50 reviewed evaluation questions for broad-corpus release, including at least one per source PDF and extra cases covering approved uses, mechanism, warnings, source lookup, missing evidence, conflicting revisions, Repatha device scope and unrelated-product contamination. Include a malicious instruction embedded in retrieved text. In V1, a cross-product comparison request asks the learner to select one product and offers separate source views. The smaller pilot uses the corresponding subset of these cases.
- [ ] Run `pytest tests/test_retrieval.py tests/test_teaching.py -q` and the offline evaluation suite. Require all source-resolution, product-isolation and unsupported-answer cases to pass before enabling learner mode; assess semantic answer quality through reviewed expected evidence.

**Acceptance:** A plausible answer without supporting evidence is a failed result. Evidence links and abstention matter as much as retrieval recall.

## Task 5 — Implement the three Streamlit workflows

**Files:** `app.py`, `ui/{explore,learn,sources}.py`, `.streamlit/config.toml`, `tests/test_app_flows.py`.

**Interfaces:** UI imports the Task 1–4 service contracts. It never reconstructs XML, talks directly to a second embedding implementation, or invents separate review rules.

- [ ] Use the supplied logo and mockups, with one consistent sidebar. Set the primary theme color to `#0063C3`; implement the hero, readable product collection and responsive source panel using native controls and limited scoped styling.
- [ ] Implement Explore with derived product counts/search and honest states for products with no reviewed chat content.
- [ ] Implement Learn with product scope, plain/technical switch, Streamlit chat input/messages, streamed answers, source expanders, lesson prompts and session-local quiz progress.
- [ ] Implement Manage sources with folder inventory, **Build XML**, extraction report/preview, **Download XML**, source review, **Preview Pinecone load**, and **Load Pinecone**. The Build button invokes `build_corpus()` and writes `XML/AmgenProducts.xml`; the Load button invokes `run_ingestion()` from that XML's reviewed chunk plan.
- [ ] Add a collapsed **Advanced chunking settings** panel with the fixed initial strategy, target/overlap controls, source selector, restore/save configuration, and local **Preview chunks**. Show source text beside exact embedded chunks, highlighted overlap, section/pages, token counts and exclusions. Separate **Build test index**, **Compare retrieval**, and **Publish configuration** actions; preview/settings changes must never initiate a paid API call.
- [ ] Display separate Extracting, Needs review, Ready to index, Indexing, Verifying, Searchable and Failed states. Build/Load actions must not run merely because the UI rerenders.
- [ ] Keep management local-only initially. For later hosting, add server-side authorization before enabling curator actions and protected source access.
- [ ] Use Streamlit application tests for the missing-credential, empty-corpus, build-success, build-failure and pending-ingestion states. Manually check keyboard use, narrow-screen layout and PDF citation opening.
- [ ] Run `pytest tests/test_app_flows.py -q`, then launch `streamlit run app.py` and verify the visible end-to-end flows.

**Acceptance:** A user can see where the XML is built, inspect/download it, deliberately index reviewed content, and learn from cited answers. A mockup or fake success badge cannot substitute for these actions.

## Task 6 — Pilot and handoff

**Files:** `README.md`, `requirements.txt` or `pyproject.toml` plus lockfile, `evals/pilot-report.md`.

- [ ] Document local setup, the current CLI, Streamlit launch, secret names without values, review workflow, supported Pinecone API/model configuration, reindexing and rollback.
- [ ] Run a reviewed three-product pilot including both Repatha source records; expand the searchable corpus only as its passages pass review.
- [ ] Record extraction coverage, actual eligible chunk count, index verification, retrieval failures, citation accuracy, response latency and observed API usage. Do not invent targets or claim performance from mocks.
- [ ] Verify a source change causes re-review/reindexing; simulate a partial upload and confirm the previous corpus still answers; verify a failed citation prevents unsupported answer publication.
- [ ] Deliver a final status table separating extracted, reviewed, indexed and searchable content. Note any unreviewed tables/figures or model-provider limitations.

## Suggested delivery order

1. Finish and verify the consolidated XML and provenance report.
2. Add the review and chunk preview, then a small verified Pinecone import.
3. Deliver the branded Explore and Learn screens with cited answers.
4. Add guided lessons/quizzes, run the pilot, then expand coverage.

The mockups and first-pass XML are useful project artifacts now. The complete Streamlit UI, reviewed clinical corpus and live Pinecone connection are subsequent implementation work, not already completed features.
