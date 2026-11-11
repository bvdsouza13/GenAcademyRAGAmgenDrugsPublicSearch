# Pinecone bootstrap reference

This describes the project's existing `scripts/setup_pinecone.py` implementation. Bulk library building, lexical search and activation are separate application services; bootstrap readiness means a compatible index exists, not that the library is searchable. Earlier bootstrap verification is historical. Current release evidence belongs in the [bulk-refactor release report](implementation/bulk-refactor-release-report.md).

## Commands

Run from the repository root using the project Python 3.12 environment. The REST adapter needs no Pinecone SDK.

```bash
.venv-corpus/bin/python scripts/setup_pinecone.py
.venv-corpus/bin/python scripts/setup_pinecone.py --dry-run
.venv-corpus/bin/python scripts/setup_pinecone.py --check
.venv-corpus/bin/python scripts/setup_pinecone.py --create --timeout 120
```

Default and dry-run modes print the sanitized planned request without network access. Check describes an existing index. Create requires a key, creates only after a 404, then polls readiness. It reuses compatible existing indexes and rejects incompatible ones without modifying them. A failed creation POST is not retried automatically; after a timeout, check whether creation succeeded.

`--config PATH` and `--secrets PATH` choose TOML files. `--request-timeout SECONDS` limits requests; `--timeout SECONDS` bounds readiness polling; `--poll-interval SECONDS` defaults to two. The loader uses nonblank exported credentials before ignored local secrets. It does not load `.env`. Bootstrap does not require an OpenAI key or edit app.toml; copy the described bare hostname into `pinecone.index_host` yourself.

## Implemented REST profile

The control plane uses `POST /indexes` and `GET /indexes/{escaped-name}` with `Api-Key` and `X-Pinecone-Api-Version: 2026-07`, blocks redirects and sanitizes errors. Request fields use top-level `deployment`, `read_capacity`, `deletion_protection` and `schema`.

| Contract | Implementation |
|---|---|
| Deployment | Managed index; configured cloud/region; OnDemand read capacity |
| Text field | Configured `chunk_text`, type string, stored text and full-text-search support |
| Integrated embedding | `llama-text-embed-v2`, 1,024 dimensions, cosine |
| Read/write parameters | Both truncation settings checked against configuration |
| Existing configured index | `amgenproduct`; immutable schema uses `END` |
| New index recommendation | Unique name and `NONE`; no automatic migration of existing schema |
| Safety of input size | Final passage/query UTF-8 bytes plus eight reserved units must not exceed 2,048 |

`index_host` accepts a bare Pinecone hostname, not an arbitrary credential-bearing URL. Model, field, dimension, metric, deployment, readiness and returned host must match the supported profile. No delete/configure operation is exposed.

## Relationship to library versions

An explicit Admin whole-library build embeds documents in a run-specific namespace. Search embeds queries with the same profile. The matching local SQLite artifact supplies lexical retrieval; this does not require another Pinecone index or embedding provider. Verification checks exact cloud records and per-document visibility alongside local artifact readiness. Atomic activation selects the semantic namespace and lexical artifact together. Retries and draft-control changes do not delete the active namespace.

```bash
.venv-corpus/bin/python -m pytest tests/test_pinecone_setup.py tests/test_connectivity.py -q
```

Offline tests use synthetic credentials and controlled transports. They exercise payloads, network-free defaults, explicit creation, compatibility, polling, redirect handling and redaction. Passing those tests is separate from authenticated account access or a successful full-library cloud build. See [configuration/setup](configuration-and-pinecone-setup.md).
