# Pinecone bootstrap reference

Verified against official documentation on November 11, 2026. This reference covers the runnable empty-index bootstrap. Document chunking, upload, retrieval, OpenAI calls and corpus publication are separate application work.

## Interface

Run from the repository root with Python 3.11 or later. The existing `.venv-corpus/bin/python` also works. No Pinecone SDK dependency is needed by this script.

```bash
.venv-corpus/bin/python scripts/setup_pinecone.py
.venv-corpus/bin/python scripts/setup_pinecone.py --dry-run
.venv-corpus/bin/python scripts/setup_pinecone.py --check
.venv-corpus/bin/python scripts/setup_pinecone.py --create --timeout 120
```

The first two commands render the sanitized planned request without contacting any service. `--check` requires a Pinecone key and describes the existing index. `--create` requires a key, creates only after an HTTP 404, then polls until ready. A compatible existing index is reused; an incompatible one is rejected without modification. A failed POST is never automatically retried. After a timeout, run `--check` because creation may already have succeeded.

`--config PATH` and `--secrets PATH` select alternative TOML files. `--request-timeout SECONDS` limits the initial HTTP requests; `--timeout SECONDS` bounds subsequent readiness polling and its requests; `--poll-interval SECONDS` defaults to two. Every mode is independent of the OpenAI key. Configuration loading follows the shared loader's environment-over-file credential precedence.

On success, the script prints a hostname obtained from an actual describe response. Save that value as `pinecone.index_host` in `config/app.toml`; the script never edits configuration. Readiness here means that the empty index is provisioned and compatible. It does not mean a corpus has been uploaded, reviewed or activated.

## REST contract

The bootstrap sends `POST https://api.pinecone.io/indexes` and `GET https://api.pinecone.io/indexes/{escaped-index-name}`, with `Api-Key` and `X-Pinecone-Api-Version: 2026-07`. It blocks redirects and suppresses response bodies in errors. The current API uses top-level `deployment` and `schema`, and reports initialization through `status.ready`. See [create-index REST](https://docs.pinecone.io/reference/api/2026-07/control-plane/create_index) and [describe-index REST](https://docs.pinecone.io/reference/api/2026-07/control-plane/describe_index).

With the checked-in settings, the planned JSON body is:

```json
{
  "name": "amgen-medicine-explorer",
  "deployment": {
    "deployment_type": "managed",
    "cloud": "aws",
    "region": "us-east-1"
  },
  "read_capacity": {"mode": "OnDemand"},
  "deletion_protection": "enabled",
  "schema": {
    "fields": {
      "chunk_text": {
        "type": "string",
        "store_text": true,
        "full_text_search": {},
        "embed": {
          "model": "llama-text-embed-v2",
          "dimension": 1024,
          "metric": "cosine",
          "write_parameters": {"truncate": "NONE"},
          "read_parameters": {"truncate": "NONE"}
        }
      }
    }
  }
}
```

Pinecone embeds `chunk_text` during later document writes and embeds query text during later semantic searches. `store_text` retains the text and `full_text_search` enables BM25. The dense model settings and both parameter dictionaries belong inside `embed`. Describe returns their resolved values; the bootstrap checks both truncation settings, model, dimension, metric, storage/search support, deployment and host. See [integrated embedding](https://docs.pinecone.io/guides/search/integrated-embedding) and [FieldEmbedConfig](https://sdk.pinecone.io/python/reference/models.html#pinecone.models.indexes.schema.FieldEmbedConfig).

The chosen model accepts 1,024 dimensions and up to 2,048 input tokens. `truncate: NONE` rejects oversized inputs instead of discarding text; the future chunker must count the product/section prefix in that limit. See [model parameters and limits](https://docs.pinecone.io/models/llama-text-embed-v2).

New indexes have deletion protection enabled. The script contains no delete/configure operation and does not change deletion protection on an existing index. The future uploader must use a concrete staging namespace, validate its contents, and publish it through the local active-corpus manifest described in `config/app.toml`.

## Offline validation

```bash
.venv-corpus/bin/python -m unittest discover -s tests -p 'test_pinecone_setup.py' -v
```

Tests use synthetic credentials and mocked responses. They cover exact request shape, network-free default behavior, safe HTTP failures, explicit creation, incompatibility checks, readiness polling, redirect rejection and secret redaction. They are not a live Pinecone integration test; no remote index was provisioned as part of producing these files.
