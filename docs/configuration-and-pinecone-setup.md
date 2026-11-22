# Configuration and Pinecone setup

The application and CLI share `amgen_explorer.config.load_config()`. Paths resolve under the repository root. Python 3.12 and the locked `requirements.txt` define the project environment. The bulk-library refactor retains the existing TOML structure and provider index/model profile.

## Credentials

Copy `.streamlit/secrets.toml.example` to `.streamlit/secrets.toml` only if the real file does not exist. Enter quoted `OPENAI_API_KEY` and `PINECONE_API_KEY` values, keep the ignored file local, and use file mode 0600. Nonblank exported environment credentials override the corresponding TOML value. **No `.env` file is loaded.**

Nonsecrets belong in `config/app.toml`. A `PINECONE_INDEX_NAME` value in secrets is not a supported index-name override.

## Existing Pinecone profile

| Setting | Project value |
|---|---|
| API family/version | Documents / `2026-07` |
| Index name | `amgenproduct` |
| Deployment | AWS `us-east-1` |
| Integrated embedding | `llama-text-embed-v2` |
| Stored/searchable text field | `chunk_text` |
| Dimensions/metric | 1,024 / cosine |
| Existing truncation setting | `END` |
| Namespace strategy | `local_manifest`, prefix `pi` |

Use the bare verified hostname in `pinecone.index_host`; inspect the checked-in nonsecret config for its value. The app never creates an index on startup or changes an immutable schema. Its independent **UTF-8 bytes + 8 ≤ 2,048** guard applies to every final prefixed passage and query before transmission, including when the existing index uses END.

```bash
.venv-corpus/bin/python scripts/check_config.py --require-secrets --require-chat --require-host
.venv-corpus/bin/python scripts/check_connections.py
.venv-corpus/bin/python scripts/setup_pinecone.py --check
```

The first command is offline. Connection checks make read-only provider requests; they do not build or activate a library. Errors suppress credentials and remote bodies. OpenAI uses the configured Responses model with `store=false`. Earlier pilot connection/generation results are historical; see the [current release report](implementation/bulk-refactor-release-report.md) for the refactor's actual verification scope.

## Different index

Choose a unique index name, clear its host and select a supported cloud/region in app.toml. For a new index use `truncate="NONE"` and retain the supported model/dimension/metric profile.

```bash
.venv-corpus/bin/python scripts/setup_pinecone.py --dry-run
.venv-corpus/bin/python scripts/setup_pinecone.py --create
```

Default behavior is a network-free dry run. Creation occurs only after a genuine 404; a compatible existing index is reused and an incompatible one is rejected without modification. Save the returned bare host and run `--check`. See the [bootstrap reference](pinecone-setup-reference.md).

## Build a searchable library

Run the app and open **Admin → Library**. Inspect the registered inventory, optionally upload PDFs, then select **Build / update entire library**. This single explicit action reads every registered source, builds/reuses the consolidated XML, verifies exact text/spans and full coverage, chunks all sources, uploads a separate Pinecone namespace, constructs local search, checks readiness and activates the completed build.

Uploading PDFs stores their bytes locally. Pinecone receives extracted chunk text and compact metadata; full PDF/XML files stay local. New runs use automatic `bulk_source_verified_v1` eligibility. Individual passage decisions are not required or manufactured. Missing registered sources and incomplete readable-text coverage prevent a complete release. Historical manual-review manifests retain their original policy and revocation checks.

**Chunk experiments** change draft chunk size/overlap. Initial values are 600/80 conservative byte budgets, not exact tokenizer counts. **Test settings** builds a complete isolated candidate and compares compatible versions. **Use this configuration** selects it; **Revert to previous version** restores a retained library. Defaults/current-settings resets change controls only. Streamlit rerenders do not submit builds, searches or evaluations.

## Persistence and troubleshooting

Keep source files, XML and `data/` together. The registry defines expected inventory; manifests bind exact records, policy, source snapshots, namespace and lexical artifact. Retained snapshots resolve citations from older results and conversations. Keeping cloud records alone cannot restore local provenance.

| Symptom | Action |
|---|---|
| Missing credentials | Edit the ignored TOML file or export nonblank values; quote TOML strings. |
| HTTP 401/403 or incompatible model/schema | Check provider permissions and app.toml; the app does not recreate the index. |
| Missing registered PDF | Restore/import the intended file; removing it from the folder does not shrink expected coverage. |
| Failed or interrupted build | Retry the unchanged build; the previous active version stays available. |
| Local artifact integrity failure | Rebuild and verify the library; cloud results cannot bypass local integrity checks. |
| Semantic outage | Use visibly labeled local-text degraded results; restore provider access for semantic retrieval. |
| Ambiguous variants | Select a result's source document before teaching; keep Repatha variants distinct. |
| Source layout limitation | View the physical PDF page; do not infer table relationships from flattened text. |
| Older conversation | Continue using its pinned version, or explicitly start a fresh search on the latest library. |

Local Admin is not server-side authorization. Public/shared deployment requires authentication, roles and durable shared storage.

## Optional search and reliability settings

Older configuration files continue to load. These tables set the compatibility defaults:

```toml
[search]
result_limit = 20
semantic_candidates = 60

[reliability]
response_deadline_seconds = 60
max_attempts = 4
retry_budget_seconds = 60
backoff_base_seconds = 1
backoff_cap_seconds = 8
```

Search limits accept 1–100; the candidate pool is at least the requested result count. Response/retry budgets accept 1–300 seconds, attempts 1–6, and backoff satisfies 1 ≤ base ≤ cap ≤ 60 seconds. Teaching's existing `[retrieval] evidence_token_budget=4000` remains a conservative byte budget including prefixes and reserve. Keep 600/80 chunk defaults until measured comparisons justify changing them.

The learning deadline covers retrieval, generation and entailment through remaining request timeouts and cooperative late-result rejection. It cannot forcibly cancel all operating-system transport work. Retryable failures use bounded exponential jitter and Retry-After;401/403are not retried. Unknown usage after interrupted/retried calls is labeled unknown, not zero.

Admin's **Check search and generated answers** explicitly tests model access, semantic search and one cited answer. Last-check timestamps are historical. `scripts/check_connections.py` checks access only; `scripts/manage_corpus.py readiness` requests verified generation. A source-only fallback is not successful generation. Existing credentials do not need to be rewritten.

Admin's **Verify stored library** compares all expected records and every document scope. **Repair missing or changed records** restores exact original content from intact local pins. It cannot repair altered local provenance. Use **Details → Open library recovery** for trusted XML regeneration or retained-version restoration. Never treat a connection outage as evidence that the index is empty.

Retention inventory reports local storage and provider-reported usage. Remote storage/dollar charges remain unknown. The official Documents API supports asynchronous [deletion by explicit IDs](https://docs.pinecone.io/reference/api/2026-07/data-plane/delete_documents), but this app deliberately retains versions until durable publication/conversation references can prove cleanup safe; it has no deletion adapter. A 202 acceptance would not prove deletion complete.

## Treatment-query relevance update

The shared condition-use policy is code, not a new Pinecone setting. Existing secrets, index, namespace, XML, 600/80 controls and lexical artifacts remain usable. A ranking-only update needs no re-upload or re-embedding. `search.result_limit` is a maximum: fewer qualifying results is intentional. The local regression command is `scripts/check_condition_search.py`; add `--live` only for an explicit provider query check. See the [current release report](implementation/condition-search-release.md) for observed results and limitations.
