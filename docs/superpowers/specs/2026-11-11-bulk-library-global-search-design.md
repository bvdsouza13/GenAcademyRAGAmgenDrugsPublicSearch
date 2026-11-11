# Bulk library administration and global content search

Status: **Approved and implemented on 2026-11-11. Release verification is recorded in [the implementation report](../../implementation/bulk-refactor-release-report.md).**

## Intent

For this version, an administrator loads the complete document collection once. Individual passage review is removed from the normal workflow. Learners search the text of the entire searchable library and follow citations into learning conversations. The administrator's routine experimentation consists of changing chunk settings, testing the result, choosing a configuration, and resetting or reverting it.

Keep Streamlit, Amgen branding, the consolidated `XML/AmgenProducts.xml`, Pinecone's existing Documents API index, and OpenAI explanations. The supplied collection has 37 PDFs and 36 medicine identities; the two Repatha documents remain separate source scopes.

## Approaches considered

1. **Recommended: full-library builds with versioned test configurations.** One admin action extracts/validates/chunks/uploads/verifies the whole collection. A successful initial import becomes the active library. Subsequent chunk experiments build separate namespaces and become active only when the administrator selects them. This reuses the existing retry, snapshot, verification and rollback mechanisms.
2. **In-place index resets.** Easier-looking controls, but a failed rebuild can interrupt search and makes fair comparison or rollback difficult. Do not use this approach.
3. **Per-medicine preparation wizard.** Improves today's flow but still requires repeated preparation for individual medicines. It does not meet the requested bulk experience.

The user approved approach 1 for this implementation.

## Experience

Primary navigation becomes **Search & Learn** and **Admin**. Session learning progress and the demo remain secondary links. The Admin view is a local workflow, not a claim of implemented server-side authorization; shared-host authentication is outside this refactor.

### Search & Learn

- Lead with **Search all medicine information** and a Search button. Search runs on explicit submission, not on every keystroke or Streamlit rerun.
- Example queries: `ACTIMMUNE`, `latex`, `storage temperature`, and other words or questions found within the documents. No medicine selection is required.
- Search covers body text, section headings, brand names and generic names across the active full library. Exact names receive a ranking boost; they do not limit search to catalog metadata.
- Results show medicine, source document/variant, section, exact excerpt, physical PDF page and available revision. Group by medicine and document; deduplicate overlapping passages.
- Each result offers **View source** and **Ask about this source**. The latter carries the query, medicine/document identities and the result's `run_id` into the learning conversation. Chat, quizzes, re-explanation and session-history keys use that pinned run and its policy. An intervening activation must not silently change their evidence version.
- Search is global discovery. Teaching remains clearly scoped to the chosen source; it does not blend different medicines or source variants into an unlabeled answer.
- Show actual searchable document/medicine counts separately from source files merely present on disk. Search results belong to one pinned library version.
- Keep the medicine catalog as an optional browse view beneath search.

Label older conversations/results with their library version and offer a fresh search/conversation using the latest library. Old citations and conversations remain resolvable from retained snapshots and manifests.

### Admin: Library

One screen contains multiple-PDF upload, the existing Documents-folder inventory, build status and a primary **Build / update entire library** action. No per-medicine selection or passage-approval screen is required.

Persist an authoritative source registry, initialized from the supplied XML's 37-document inventory and verified source files. Compare builds against this registry, not merely the files remaining in the folder. Missing registered sources block a complete build; newly validated imports extend its versioned inventory. Explicit file replacement records the new hash while preserving document identity and prior snapshots. Renamed/duplicate bytes must not create a second medicine accidentally. Preserve known medicine IDs; derive new identity from a supported source title, and report unresolved title/filename identity as a precise batch import error rather than inventing a medicine. No individual passage approval is introduced by these file checks.

On that action:

1. Validate the complete source inventory and newly uploaded files.
2. Build or reuse the consolidated XML when its source identity is unchanged.
3. Verify source hashes, exact archived text, citation spans and coverage automatically.
4. Create chunks for every source using the current published settings, or defaults for the first build.
5. Load a new Pinecone namespace and construct the matching local text-search index.
6. Verify every record, every document's search visibility, and the expected inventory/coverage.
7. Atomically activate the completed library. A failed or interrupted build leaves the previous library available and offers **Retry**.

Show progress in plain language: **Reading documents → Preparing text → Uploading → Checking search → Ready**. Display processed files, searchable products/documents/pages, chunks, extraction limitations and actual completion status. Technical hashes and namespaces go in Details.

The UI must distinguish uploading PDFs to the application's local library from sending extracted chunks and metadata to Pinecone. Full PDFs and the single XML remain local, with immutable snapshots for citations.

### Admin: Chunk experiments

Keep three visible controls: **Chunk size**, **Overlap**, and **Reset to defaults**. Explain their actual units: the existing implementation uses conservative UTF-8 byte budgets plus a reserve, not exact model-token counts. Propose initial defaults of 600/80; do not claim these are optimal.

- Show a local preview of chunks, coverage and estimated embedding volume beside draft settings.
- **Test settings:** one explicit action builds an isolated full-library version and runs the same saved questions against the current and test versions. Show stage progress, then cited passages side by side, measured retrieval scores, latency and reported usage. The internal build/evaluate steps are not separate mandatory user actions.
- **Use this configuration:** after successful verification, switch the entire library atomically.
- **Reset to defaults:** change draft size/overlap to 600/80 only. It neither deletes Pinecone data nor changes live results. Testing and choosing that configuration applies it.
- **Restore current settings:** discard draft changes and copy the published settings.
- **Revert to previous version:** restore the previous verified full-library version. The old pilot remains a separately labeled recovery option, not a full-library default.

Every version contains all intended medicines. Configuring ACTIMMUNE or testing a question about it must never replace the global library with ACTIMMUNE alone. Keep staging terminology, test-index duplication and separate initial-publication controls out of the main experience.

Experiments require an active full-library baseline under the same policy. If source documents changed, update the library before comparing chunk settings. This avoids presenting changes in source coverage as improvements caused by chunk size.

## Automated eligibility replaces manual passage approval

Do not bulk-write `accepted` into the review database or present machine verification as human/clinical approval.

Introduce a versioned policy contract used consistently by chunking, indexing, search, teaching and re-explanation:

- Legacy manifests without a policy marker use `manual_review_v1`, preserving their existing accepted-review and revocation checks.
- New manifests explicitly use `bulk_source_verified_v1` and a schema/policy fingerprint.
- New metadata records source verification, extraction method, layout limitations, and independent human/clinical review status. Existing manual review records remain historical; missing individual reviews do not block new bulk runs.
- Automatic verification checks PDF identity, text hashes, exact page offsets, document/medicine ownership, complete inventory and embedding limits. It establishes extraction provenance, not clinical validity.

This change must reach every current `review_state == accepted` check together; simply hiding the review UI would leave most content unavailable.

## Full searchable coverage

A read-only audit of the supplied XML found 3,398,430 archived characters across 1,439 pages. Candidate section spans currently cover these characters exactly once. However, today's eligibility rules exclude 433 section blocks containing 799,990 characters because of unresolved table/figure flags. Removing manual review alone will not meet the requested full-content search.

- Define coverage using unique `(PDF hash, page, character interval)` spans, rather than chunk count or overlapping text totals.
- Prefer section passages; fill any uncovered page intervals from the archived text. Never suppress a whole page archive merely because some section exists in its document.
- Retain text with table/figure/layout warnings for discovery. Show the limitation and original page; explanations must not infer unverified row/column relationships. Use a cited source excerpt when the structure cannot support a reliable explanation.
- Split oversized source units deterministically at safe boundaries, with exact offsets, continuation/parent IDs and adjacent-context retrieval. Do not silently drop them or let the embedding service truncate them. If the full necessary context cannot fit during teaching, return an explicit limitation with the source.
- Report blank or image-only pages separately. This version targets all readable PDF text; OCR is not included. Corrupt/unreadable files or missing expected documents prevent an apparently complete release and retain the previous library.
- For the supplied collection, verification must account for all 37 PDFs and 36 products, including both Repatha documents, and all nonempty archived text. No manual passage decisions are needed.

## Search architecture

Add a global discovery contract, separate from the existing single-source `EvidenceBundle`:

1. Build a local lexical index from the exact records of each verified run, including source text, section headings and names from its pinned XML. Use built-in SQLite FTS5 if available; keep a deterministic local lexical fallback.
2. Run the existing Pinecone semantic search over the whole active namespace, with source-version filters and optional user-selected medicine/document filters.
3. Validate cloud hits against immutable local records, combine lexical and semantic ranks deterministically, apply a bounded exact-name boost, and group/deduplicate results.
4. Resolve citations to that version's PDF/XML snapshots.

No new Pinecone index or embedding model is proposed. Cache lexical artifacts by run identity and ranking version. The active manifest points to both the Pinecone namespace and the matching lexical artifact; neither may switch independently. On semantic-provider failure, retain local text search with an explicit degraded-mode notice. Display top matches honestly rather than implying an exhaustive clinical answer.

## Measuring whether chunking improves results

The existing Compare feature reports returned passages, unique source-block counts and one elapsed time; these are not relevance or accuracy scores. Its product-only scope also prevents useful comparisons between the two Repatha documents.

Create a versioned evaluation suite with both global discovery and explicit medicine/document-scoped cases. Reuse the 50 existing provenance fixtures, then add name-free content queries and expected documents/quotes/spans.

For a controlled chunk comparison, pin the PDF/XML versions, full inventory, eligibility policy, question-suite hash, embedding profile, ranking/search version, retrieval settings, evidence budget and generation settings when applicable. Only chunk configuration varies. Label incompatible comparisons as unavailable rather than presenting a winner.

Show:

- Expected-document Recall@k and reciprocal rank for global search.
- Expected quote/span coverage under an equal evidence budget; touching one block ID is insufficient.
- Searchable source coverage and exclusions, including expected sources that failed coverage.
- Citation resolution and cross-medicine/document contamination checks.
- Observed latency and provider-reported usage, with cold/warm conditions identified.
- Optional generated-answer checks, separately labeled; these do not establish clinical accuracy.

Run evaluations on explicit clicks. Do not auto-run paid comparisons on rerender or claim that a larger chunk is inherently better.

## Migration and boundaries

Preserve the existing XML, review history, immutable snapshots, saved manifests and pilot namespaces. Add new policy/schema fields compatibly; legacy runs remain readable and recoverable. Snapshot the existing configuration before enabling the new workflow. Initial full-library activation happens only after new-policy coverage, local lexical-index readiness and Pinecone verification pass.

Keep exact citations, source-integrity checks, controlled publication, retry/resume, the OpenAI citation/entailment checks and personal-treatment boundaries. Extend the test suite rather than weakening legacy assertions. Update the demo to show bulk setup, content search and a chunk comparison; prepared demo content remains clearly labeled and independent of provider calls.

Out of scope: clinician sign-off, OCR, inferred table reconstruction, cross-medicine treatment recommendations, new embedding providers, public hosting and production authentication.

## Approval acceptance criteria

1. A fresh empty review database can build and activate the complete supplied collection without accepting any individual passage.
2. All 37 documents/36 products and all readable archived text are accounted for; source gaps are visible and cannot silently disappear from completion counts.
3. ACTIMMUNE becomes searchable through the same bulk action as every other medicine.
4. A body-text query without a medicine name finds the expected source; exact brand/generic searches still work.
5. Search can show multiple medicines while source variants, citations and follow-up conversations remain distinct.
   Follow-up retrieval stays pinned to the selected result's run even if a different library becomes active before the click or subsequent question.
6. Resetting controls makes no provider calls and does not change live search; a failed rebuild leaves the active library intact.
7. A/B results use identical sources/questions/budgets and report measured retrieval quality rather than invented improvement scores.
8. A verified configuration can be selected and reverted without dropping other medicines or breaking prior citations.
9. The existing 250-test regression baseline is preserved or migrated into explicit legacy-mode tests; new tests cover the new bulk/search policies.

Implementation steps are in [the refactor plan](../plans/2026-11-11-bulk-library-global-search-refactor.md).
