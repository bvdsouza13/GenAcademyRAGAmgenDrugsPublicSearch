# Technical implementation notes

These notes describe the bulk-library/global-discovery contracts and supersede the original pre-implementation notes. Existing code is the implementation authority; the [approved design](superpowers/specs/2026-11-11-bulk-library-global-search-design.md) supplies acceptance criteria and the [release report](implementation/bulk-refactor-release-report.md) records actual verification.

## Service boundaries

| Module | Responsibility |
|---|---|
| `source_import.py` | Transactional PDF imports, supported title identity, duplicate/replacement checks, expected source registry |
| `extraction.py`, `xml_store.py` | Single consolidated XML, XSD and source/provenance validation, exact page archives |
| `eligibility.py` | Versioned manual/bulk eligibility, exact-span source verification and unique interval coverage |
| `chunking.py` | Deterministic source-scoped chunks, exact spans, safe continuation splitting and conservative input limits |
| `indexing.py` | Record/profile/run integrity, batching, retry checkpoints, verification, activation and rollback |
| `search.py` | Immutable per-run lexical artifact, whole-library semantic search, verified rank fusion and grouped discovery |
| `library.py` | Complete-library preparation, candidate builds, registry/version lifecycle and chunk-setting selection |
| `evaluation.py` | Source-pinned suites, compatible comparisons and retrieval/span/citation measurements |
| `retrieval.py`, `teaching.py` | Source-scoped evidence, adjacent context, checked cited explanations and source-reading quizzes |
| `service.py`, `app.py`, `ui/` | Shared orchestration, explicit UI submissions and run-pinned conversation state |

Construction/import does not make provider requests. Keep mutable job state in persisted checkpoints; UI reruns and controls do not implicitly submit work. Local locks prevent conflicting build/publication operations. The first runtime remains one local Python/Streamlit process, with no hosted authorization claim.

## Source registry and XML

The source registry is authoritative expected inventory, initialized from the supplied XML and verified files. Deleting a file cannot silently remove its expected document. New files need readable title identity; replacements preserve registered identities and change hashes explicitly. Renamed identical bytes do not manufacture a second medicine. Preserve registry snapshots and old PDF/XML snapshots.

`build_corpus()` creates `XML/AmgenProducts.xml` locally and validates its candidate before replacement. XML preserves products, documents, section blocks and exact physical-page text separately from derived facts. `XML/prescribing-information.xsd` and `XML/xml-tag-guide.md` describe the local structure, not FDA SPL. Label revision, initial approval, acquisition and extraction dates are distinct; unknown values remain unknown.

A document's actual hash, ownership, 1-based page bounds and exact archived character spans must agree. Repatha's two PDFs remain distinct; filename phrases alone do not prove universal device applicability or supersession. General-learner paraphrases never overwrite exact source text.

## Eligibility and coverage

`manual_review_v1` is the default for legacy manifests without a marker. Its individual hash-bound acceptance/revocation behavior remains intact. `bulk_source_verified_v1` explicitly pins schema/policy and source verification; `human_review_status='not_assessed'` stays separate. All consumers use the same policy contract rather than scattered unconditional `review_state == accepted` checks.

Bulk assessment validates PDF/XML/text hashes and source ownership, prefers section spans and fills every uncovered nonempty page interval from its archive. Coverage is a union over `(document hash, physical page, character interval)`, not overlapping chunk totals. Missing registered sources or readable-text gaps block complete builds. Report blank/image-only pages separately; this implementation does not OCR them.

Retain table/figure/layout warnings for discovery and surface their source limitations. Flattened text cannot support inferred row/column relationships in generated explanations. Oversized units split with exact offsets, parent/continuation identities and adjacent-context retrieval; if necessary context exceeds the teaching budget, return an explicit limitation instead of silent truncation.

## Chunk and provider contract

Initial controls are target 600/overlap 80, target range 300–1,200, overlap range 0–200 and strictly below target. They use conservative UTF-8 byte budgets plus reserved units, not exact hosted-tokenizer counts. Every final embedded string includes the product/section prefix in its **bytes + 8 ≤ 2,048** hard guard.

Pinecone uses the existing Documents API `2026-07` REST adapter, field `chunk_text`, integrated `llama-text-embed-v2`, dimension 1,024 and cosine. Existing END truncation is retained; a new index may use NONE. There is no automatic schema/index migration and no new embedding provider.

Metadata is flat with supported scalars/string lists, at most 40 KB. Batches obey configured byte/count limits, up to 96 integrated-embedding documents and 2 MB; the project defaults to 64 records. Every upsert submits a complete record and deterministic IDs permit safe retries. Errors and logs must not expose keys or remote response bodies.

## Immutable search and activation

A run ID binds plan fingerprint, exact records and embedding profile. Immutable chunk records, source snapshots and manifests persist locally. Verification fetches every expected record and tests visibility for every document. A complete full-library run additionally requires its matching local lexical artifact.

`search.py` builds a run/artifact-format-pinned SQLite database with exact record payloads, body text, section headings and pinned XML brand/generic aliases. FTS5 is used when available; a deterministic token fallback remains available. Artifact path, file hash, run/record/catalog/policy/ranking pins and authoritative rows are checked before search. Search uses validated bytes without trusting stale mutable caches.

Semantic search spans the whole concrete namespace with XML and optional product/document filters. Cloud hits must equal immutable local records. Runtime query interpretation and relevance gates handle conversational names, topical terms, typo choices and no-results behavior. Whole alias references in actual source text remain discoverable across products. Overlapping passages deduplicate; diversity applies among relevant results. A semantic outage yields an explicit degraded local-text result. A changed local artifact fails closed before provider use.

`data/active-corpus.json` atomically points to the semantic namespace and matching lexical artifact. Builds use separate namespaces. Failed/interrupted candidates leave the active library available; retained runs support rollback and old citation resolution. No automatic namespace deletion occurs.

## Discovery, teaching and experiments

`SearchResults` is global discovery; `EvidenceBundle` is one selected medicine/document/run. Result selection carries that run into retrieval, chat, quiz, re-explanation, citations and session history. Activation cannot silently redirect follow-up evidence. Legacy revocations are checked against the retained source and current review history.

OpenAI Responses receives the question and bounded scope-matched excerpts, uses `store=false`, and returns cited explanations checked for invented/wrong-scope IDs and unsupported claims. Preserve numbers, units, negations and qualifiers. Personal treatment choices and cross-medicine comparative recommendations are outside the teaching scope. Source text is evidence, not executable instructions.

Test settings builds a complete candidate and evaluates compatible versions with identical sources, policy, suite, embedding/search profile, retrieval settings and equal evidence budget. Visible discovery uses the Home result limit, independently of teaching top_k and evidence bytes. Metrics include precision@5/@10, graded relevance, judgment coverage and executed no-answer/suggestion behaviors, plus expected-document recall/rank, exact spans, citations, latency and reported usage. Changed PDF hashes invalidate frozen discovery judgments until a separately versioned relabeling; unchanged parser-only page spans retain judgments. Defaults/current resets change draft controls only. They neither delete data nor trigger API calls. A clinician-reviewed evaluation program remains separate from these retrieval observations.

## Configuration and future hosting

`config/app.toml` adds optional search/reliability settings with backward-compatible defaults. Credentials come from nonblank exported environment values or ignored `.streamlit/secrets.toml`; no `.env` loader exists. The local browser does not receive keys. Shared hosting requires server-enforced identity/roles, durable shared artifacts, isolated learner state, operational recovery and appropriate spending controls. See [setup](configuration-and-pinecone-setup.md) and [future work](future-features.md).

Shared evidence eligibility, atomic continuation packing, scoped local fallback, bounded provider work and explicit recovery contracts are described in the [current architecture](architecture.md). Mechanism/indication lessons keep the complete requested section context and omit unrelated ranked Highlights/IFU supplements; restrictions within the requested section remain binding.
