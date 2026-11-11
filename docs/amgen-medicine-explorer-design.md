# Amgen Medicine Explorer — current product design

This document supersedes the original per-passage administration proposal. The [bulk-library/global-search design](superpowers/specs/2026-11-11-bulk-library-global-search-design.md) is the detailed refactor contract. Release results belong in the [bulk-refactor release report](implementation/bulk-refactor-release-report.md), separately from this description of intended behavior.

## Purpose and source boundary

Let general learners find information within the supplied prescribing-information library and follow exact sources into plain-language or technical teaching. Keep Streamlit, Amgen branding, one consolidated XML, the existing Pinecone Documents API index and OpenAI cited explanations.

The supplied collection has 37 PDFs, 36 medicine identities and 1,439 physical pages. These input facts do not establish current searchable coverage, current clinical labeling or a complete external product catalog. Display actual verified searchable counts separately from files present on disk. This custom collection XML is not FDA SPL; normalized clinical facts remain unknown unless supported.

## Search & Learn

Lead with **Search all medicine information** and an explicit Search button. Search body text, headings, brand names and generic names; no medicine selection is required. Examples include `ACTIMMUNE`, `latex` and `storage temperature`. Exact names receive a bounded relevance boost rather than limiting matching to catalog metadata.

Group results by medicine and document. Show source/variant, section, exact excerpt, physical PDF page and available revision. Deduplicate overlapping passages within the same source. The two Repatha documents remain separate even when brand names or passages overlap. A filename does not establish device applicability or supersession.

**View source** resolves the result's retained PDF/XML snapshots. **Ask about this source** carries query, product, document and run into teaching. A conversation, quiz, re-explanation and its progress retain that run through later activations. Label older versions and offer a fresh search on the latest library.

Global search is discovery. Teaching retrieves and explains one selected source scope, with every material medicine claim supported by a citation. Plain language and technical detail use the same evidence. When the context cannot safely fit, an extraction layout is unreliable or evidence is insufficient, show the limitation and source excerpt. Do not infer table relationships or combine medicines into an unlabeled treatment answer. Personal treatment selection/dose changes remain outside the educational workflow.

Search and teaching happen on explicit submission, not each keystroke or Streamlit rerun. The optional medicine catalog, session learning view and prepared demo remain secondary entry points.

## Admin: Library

One local operator screen contains multi-PDF upload, the registered Documents inventory, build status and **Build / update entire library**. Import validates title identity, deduplicates renamed identical bytes, preserves known medicine/document IDs and records explicit replacements. Missing registered files remain expected and block completion.

A build validates the complete source inventory, builds/reuses `XML/AmgenProducts.xml`, verifies source hashes and exact archived spans, chunks every document, sends extracted text/flat metadata to a new Pinecone namespace, creates the matching local lexical artifact and verifies both before atomic activation. Full PDF/XML files stay local. Show **Reading documents → Preparing text → Uploading → Checking search → Ready**, actual counts and extraction limitations. Technical identifiers belong in Details.

An interrupted or failed build keeps the previous active library and supports retry. The active manifest selects the semantic namespace and lexical artifact together. Retained manifests and source snapshots keep old citations resolvable.

## Automated eligibility and coverage

New runs explicitly use `bulk_source_verified_v1`, a schema version and eligibility fingerprint. Source verification establishes extraction provenance; independent human/clinical review remains `not_assessed`. Do not bulk-write accepted decisions into historical review records. Legacy manifests without a policy marker use `manual_review_v1` with their accepted/revoked behavior.

Readable-text coverage counts unique `(PDF hash, page, character interval)` spans. Prefer sections, then fill uncovered archived-page intervals. Table/figure/layout warnings remain searchable with visible limitations. Oversized source units split deterministically with exact offsets, parent/continuation relationships and adjacent context. Nothing is silently truncated or omitted to satisfy an embedding limit. Blank/image-only pages are reported separately; OCR is out of scope.

## Admin: Chunk experiments

| Control | Behavior |
|---|---|
| Chunk size / Overlap | Draft conservative UTF-8 byte budgets; initial defaults 600/80, not exact token counts or claimed optima |
| Test settings | One explicit action creates a complete isolated candidate and evaluates it against the compatible current full-library baseline |
| Use this configuration | Atomically selects a verified candidate |
| Reset to defaults | Changes draft controls only to 600/80 |
| Restore current settings | Discards draft changes and copies published settings |
| Revert to previous version | Restores a retained verified full library; legacy pilot recovery is separate |

Each version contains every intended medicine. A selected medicine or example question cannot reduce the live library to that medicine. Source changes require a library update before controlled chunk comparison. Neither default/current resets nor navigation makes provider calls.

Evaluations pin sources, registry, policy, question-suite hash, embedding profile, search version, retrieval settings and equal evidence budget; only chunk configuration varies. Show expected-document Recall@k/reciprocal rank, expected-span coverage, searchable coverage/exclusions, citation/scope checks, measured latency and available reported usage. Separately label any generated-answer checks. These measurements do not establish medical accuracy.

## Local deployment boundary

Keep provider keys in ignored TOML/environment credentials on the local server; no `.env` loader is added. OpenAI uses `store=false`. Admin navigation is not hosted authorization. Authentication/roles, OCR, inferred table reconstruction, persistent learner accounts, public hosting and new embedding providers remain outside this refactor. See [architecture](architecture.md), [setup](configuration-and-pinecone-setup.md), [technical contracts](technical-plan-notes.md) and [roadmap](future-features.md).
