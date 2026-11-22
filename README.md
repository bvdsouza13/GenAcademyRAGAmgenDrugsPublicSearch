# Amgen Medicine Explorer

A local Streamlit application for searching and learning from Amgen prescribing-information PDFs. An administrator builds the whole library once; learners search document text across medicines, open exact PDF citations, and start a conversation scoped to one source.

## Run locally

```bash
.venv-corpus/bin/python -m streamlit run app.py
```

Open **http://127.0.0.1:8501**. For a fresh Python 3.12 environment:

```bash
python3.12 -m venv .venv-corpus
.venv-corpus/bin/python -m pip install -r requirements.txt
.venv-corpus/bin/python -m streamlit run app.py
```

`requirements.txt` locks dependencies; `requirements.in` lists direct dependencies. The repository includes the supplied PDFs, canonical XML and a prepared offline demo. Runtime manifests, databases, immutable source snapshots and credentials stay local and are ignored by Git. A fresh clone needs an explicit library build before live library search and learning are available.

## Search & Learn

Submit a word or question under **Search all medicine information**. Try `ACTIMMUNE`, `latex` or `storage temperature`. Search covers body text, headings, brand names and generic names across the selected library version. Results group by medicine and document, keep the two Repatha sources separate, and show exact excerpts, physical PDF pages, section and available revision.

**View source** opens the retained PDF. **Ask about this source** starts teaching within that medicine/document and pins its library version. Changing the active library cannot silently change an existing conversation or its citations. Global discovery may show multiple medicines; teaching uses the selected source. If semantic search is unavailable, an explicit notice identifies verified local text results as degraded search.

Search runs on submission. Changing a filter, explanation style or navigation item does not repeat a provider request. The medicine catalog is an optional browse view. Session progress and the prepared **Demo tour** remain secondary navigation.

## Admin: build the entire library

1. Inspect the registered Documents inventory and optionally upload multiple PDFs. Upload stores PDFs locally; it does not send full files to a provider.
2. Select **Build / update entire library**. The app validates the complete registry, builds/reuses one `XML/AmgenProducts.xml`, verifies exact source spans, creates chunks, uploads text/metadata to a new Pinecone namespace and builds the matching local lexical artifact.
3. Watch **Reading documents → Preparing text → Uploading → Checking search → Ready**. A completed initial build becomes active; failures retain the previous library and can be retried.

Individual passage acceptance is not required for new bulk builds. `bulk_source_verified_v1` establishes extraction provenance, source ownership and readable-text coverage; it does not establish clinician approval. Historical manual-review runs retain `manual_review_v1` and their revocation checks. The review database is preserved rather than bulk-marked accepted.

The supplied inventory has **37 PDFs and 36 medicine identities**. These are input counts, separate from searchable counts shown for an actual verified run. Missing registered files, corrupt PDFs, source mismatches and incomplete coverage block a complete release. Both Repatha documents remain distinct. Discovery retains text carrying table/figure limitations and links its original page; teaching cannot infer unverified row/column relationships. Blank/image-only pages are reported separately; OCR is outside this version.

## Verify, repair and recover

In **Admin → Library**, **Records at last build** is historical. Select **Verify stored library** to fetch and compare every expected record and check every document scope. A difference exposes **Repair missing or changed records**, which restores the original IDs and exact content from intact pinned snapshots and then rechecks. An outage is reported as unavailable; it is never treated as proof that records are missing. Verification does not enumerate extra remote records.

Open **Connection and answer readiness → Check search and generated answers** to test model access, semantic search and an actual cited answer. Each result shows its check time. A valid key or model listing alone does not prove that generation works. Calls are explicit, and rerenders do not repeat them.

**Details → Open library recovery** lists validated retained versions and can regenerate damaged working XML from the complete registered PDFs. Startup also keeps Recovery reachable when the active pointer fails. Original registered bytes can be restored using **Replace matching filenames** on import. Parser upgrades occur on an explicit Build as a new candidate; old pinned conversations remain intact.

```bash
.venv-corpus/bin/python scripts/manage_corpus.py verify-library
.venv-corpus/bin/python scripts/manage_corpus.py repair-library
.venv-corpus/bin/python scripts/manage_corpus.py readiness
.venv-corpus/bin/python scripts/manage_corpus.py recoverable-versions
.venv-corpus/bin/python scripts/manage_corpus.py recover-xml
```

Search recognizes conversational names, presents typo/ambiguous-name suggestions for explicit selection, and can return no matching passages. Teaching falls back to verified local evidence during a semantic outage. Complete continuation groups are kept together; missing qualifiers or unresolved layout prevent generation and scored quizzes. Follow-up buttons use vetted educational prompts, and quiz choices shuffle once then keep their grading state.

## Admin: chunk experiments

Start with **Chunk size 600 / Overlap 80**. Units are conservative UTF-8 byte budgets plus a reserve, not exact model tokens; the values are starting points to test.

- **Test settings** builds an isolated full-library candidate and compares saved questions with the current full-library baseline. This action can consume provider usage.
- **Use this configuration** selects a verified candidate atomically.
- **Reset to defaults** changes draft controls to 600/80 only. **Restore current settings** discards draft edits. Neither action uploads, deletes data or changes live search.
- **Revert to previous version** restores the retained verified library. Legacy pilot recovery remains separately labeled.

Comparisons pin sources, inventory, policy, question suite, embedding profile, search version, retrieval settings and evidence budget. Results use the 51-case learner-search suite with unfiltered source questions and executed behavior checks. They report visible-result precision, graded relevance, judgment coverage, no-answer/suggestion correctness, expected-document recall/rank, source-span coverage, citation/scope checks, observed latency and available provider-reported usage. Incompatible runs cannot be presented as a controlled chunk comparison. These retrieval measurements do not establish clinical accuracy.

## Configure providers

Put quoted credentials in the ignored `.streamlit/secrets.toml`:

```toml
OPENAI_API_KEY = "your-openai-key"
PINECONE_API_KEY = "your-pinecone-key"
```

Nonblank exported environment credentials override that file. **There is no `.env` loader.** Keep nonsecret paths, index host/name and models in [config/app.toml](config/app.toml). Optional `[search]` and `[reliability]` tables configure search limits, deadlines and retries; existing configuration files retain compatibility defaults.

```bash
.venv-corpus/bin/python scripts/check_config.py --require-secrets --require-chat
.venv-corpus/bin/python scripts/check_connections.py
.venv-corpus/bin/python scripts/setup_pinecone.py --check
```

The adapter targets the existing Pinecone Documents API `2026-07`, `chunk_text`, integrated `llama-text-embed-v2`, 1,024 dimensions and cosine. The existing configured index uses `truncate=END`; every transmitted passage/query must first satisfy **UTF-8 bytes + 8 ≤ 2,048**, preventing oversized input from relying on truncation. A different index requires explicit setup; startup never creates one. OpenAI teaching uses the configured Responses model with `store=false`. See [configuration/setup](docs/configuration-and-pinecone-setup.md).

## Verify and operate

```bash
.venv-corpus/bin/python -m pytest
.venv-corpus/bin/python scripts/test_offline.py --shuffle-seed 271828
.venv-corpus/bin/python scripts/build_amgen_xml.py --validate-only
.venv-corpus/bin/python scripts/manage_corpus.py --help
```

Offline tests use fake providers and temporary storage. `test_offline.py` additionally blocks socket connections and can randomize order. `scripts/live_library_check.py --chat` explicitly exercises live global searches and three source-scoped teaching questions. Live connection/search/generation checks require explicit commands and can incur usage. The management CLI provides explicit full-library actions:

```bash
.venv-corpus/bin/python scripts/manage_corpus.py preview-library --target 600 --overlap 80
.venv-corpus/bin/python scripts/manage_corpus.py build-library --target 600 --overlap 80
.venv-corpus/bin/python scripts/manage_corpus.py search --query "storage temperature"
.venv-corpus/bin/python scripts/manage_corpus.py test-settings --target 900 --overlap 80 --suite learner-search
.venv-corpus/bin/python scripts/manage_corpus.py use-configuration --run-id VERIFIED_RUN_ID
.venv-corpus/bin/python scripts/manage_corpus.py revert-library
.venv-corpus/bin/python scripts/manage_corpus.py status
```

`preview-library` is local; `build-library` writes to Pinecone and activates after verification. Add `--candidate-only` to build without activation. `test-settings` builds/evaluates a candidate, and `search` calls semantic retrieval with local lexical fallback; both may consume provider usage. Search accepts optional `--run-id`, `--product-id` and `--document-id`. Legacy `preview/load/publish/rollback` remain for pilot recovery; a selected-product legacy load is not a full-library update.

Retain `Documents/`, `XML/` and `data/` together. `data/source-registry.json` is the authoritative inventory; versioned registry snapshots retain its history. `data/manifests/` holds immutable records, run manifests and lexical artifacts; `data/corpora/` retains XML/PDF citation snapshots. `data/active-corpus.json` atomically points to the matching semantic namespace and lexical artifact. No namespace deletion happens automatically.

## Evidence and release history

The earlier six-chunk/four-mechanism-passage pilot and its live smoke results are historical. They do not describe the searchable coverage of a new bulk run. Source-fidelity review is separate from clinical review, and supplied documents are not asserted to be the latest labels. This custom XML is not FDA SPL.

The [reliability remediation report](docs/implementation/reliability-remediation-release.md) records the latest changes and checks. The historical [bulk-refactor release report](docs/implementation/bulk-refactor-release-report.md) records its verified coverage, regression results, live searches, chunk comparison and operating limits. Earlier [release QA](docs/implementation/release-qa-report.md), [regression assessment](docs/implementation/additional-regression-assessment.md) and [pilot evidence](evals/pilot-report.md) describe their original scope and are superseded for current workflow/status claims. Their recorded measurements must not be read as a new full-library cloud evaluation.

- [Architecture and editable diagrams](docs/architecture.md)
- [Current product design](docs/amgen-medicine-explorer-design.md), [approved bulk/search design](docs/superpowers/specs/2026-11-11-bulk-library-global-search-design.md), [refactor implementation plan](docs/superpowers/plans/2026-11-11-bulk-library-global-search-refactor.md)
- [Technical contracts](docs/technical-plan-notes.md), [evaluation notes](evals/README.md), [prepared demo](docs/demo.md), [future work](docs/future-features.md)
- [XML guide](XML/xml-tag-guide.md) and [structural XSD](XML/prescribing-information.xsd)

The Admin view is a local operator workflow. Shared hosting, server-side authentication/authorization, persistent learner accounts and cross-device progress remain outside this version.
