# Configuration and Pinecone setup

The running application and CLI use the same `amgen_explorer.config.load_config()` loader. Paths resolve relative to the project root, even when launched from another directory. Python 3.12 and `requirements.txt` are the tested environment.

## 1. Credentials

Copy `.streamlit/secrets.toml.example` to `.streamlit/secrets.toml` only if the real file does not exist. Enter quoted values for `OPENAI_API_KEY` and `PINECONE_API_KEY`. Do not overwrite the saved file. It is excluded from Git and should have file mode 0600. A nonblank environment variable overrides the corresponding TOML credential. A `.env` file is not loaded.

Index name/host and other nonsecrets are read from `config/app.toml`. `PINECONE_INDEX_NAME` in secrets is not a supported override; the actual name from the user's saved setup has already been placed in `config/app.toml`.

## 2. Existing index — already configured

```toml
[pinecone]
api_family = "documents"
api_version = "2026-07"
index_name = "amgenproduct"
index_host = "amgenproduct-7tgd2ef.svc.aped-4627-b74a.pinecone.io"
cloud = "aws"
region = "us-east-1"
embedding_model = "llama-text-embed-v2"
text_field = "chunk_text"
dimension = 1024
metric = "cosine"
truncate = "END"
max_input_tokens = 2048
batch_size = 64
max_batch_bytes = 2000000
namespace_strategy = "local_manifest"
namespace_prefix = "pi"
```

The existing index was described through the authenticated API, not inferred from its name. It has the correct `chunk_text` string field with integrated embeddings, stored text and full-text search. Its schema is immutable and uses END truncation. The local independent UTF-8 byte upper-bound guard prevents oversized uploads and queries. Extra index fields such as `title` are harmless. The app never changes that index schema or creates an index on startup. [Pinecone schema configuration](https://docs.pinecone.io/reference/api/2026-07/control-plane/configure_index)

## 3. Verify both services

```bash
.venv-corpus/bin/python scripts/check_config.py --require-secrets --require-chat --require-host
.venv-corpus/bin/python scripts/check_connections.py
.venv-corpus/bin/python scripts/setup_pinecone.py --check
```

The first command is offline. The second checks both credentials/model/index. The third validates the detailed index schema. Errors are sanitized; no keys or remote error bodies are printed. OpenAI uses the Responses API with the configured `gpt-6.1-sol` model and `store=false`. Actual inference was tested successfully. [Responses API](https://developers.openai.com/api/reference/resources/responses/methods/create)

## 4. Create a different index only when needed

Choose a unique `index_name` in app.toml, clear `index_host`, and select supported cloud/region. For a new index, set `truncate = "NONE"`. Retain the supported model/dimension/metric profile.

```bash
.venv-corpus/bin/python scripts/setup_pinecone.py --dry-run
.venv-corpus/bin/python scripts/setup_pinecone.py --create
```

The default is a dry run. `--create` creates only after a genuine 404 and never deletes/replaces an existing index. Copy the returned bare host into app.toml and run `--check`. Do not use the existing name with an incompatible schema and expect the app to migrate it. Creating an index may affect provider billing.

## 5. Load the XML through the app

Run `streamlit run app.py` using the project environment. In Manage sources: Build XML, review selected source passages, Preview chunks, Preview Pinecone load, Load Pinecone, then Publish configuration after verification. An empty/unreviewed plan cannot load. Each configuration produces a separate deterministic staging namespace; retries resume checkpoints. Moving a slider or rerunning Streamlit does not send provider requests.

Advanced chunk sizes use a conservative token upper bound, not the exact hosted tokenizer. Target 600/overlap80 are initial budgets; whole sentences may exceed the soft target but never the hard model guard. Overlap uses complete sentences, so its actual amount may be lower. Compare configurations on the same source/review snapshot before publishing.

## 6. Persistence and troubleshooting

Keep `Documents/`, `XML/`, and `data/` together. Publication snapshots include the XML and source PDFs required for stable citation pages. Losing local manifests/reviews/snapshots cannot be repaired by merely retaining cloud vectors.

- Missing credentials: edit the correct secrets file and quote TOML strings.
- HTTP401/403: check provider key permissions/project access; no index recreation is attempted.
- Model/schema mismatch: describe the existing index and correct app.toml; do not point keys at arbitrary hosts.
- Empty chat: choose a published medicine and a single source version; review missing passages.
- Stale preview: preview again after a source/review/chunk setting changes, then stage that build.
- Partial upload/verification delay: retry the unchanged plan; the previous active namespace remains selected.
- Rejected paraphrase: read the exact cited source fallback or ask a narrower question.

The application listens on `127.0.0.1:8501`. Public/shared deployment is not configured and requires server-side authorization for curator actions and source access.
