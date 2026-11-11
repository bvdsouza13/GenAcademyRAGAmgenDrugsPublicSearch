# Amgen Medicine Explorer

A local Streamlit application for learning about Amgen medicines from the supplied prescribing-information PDFs. It builds one XML collection, reviews and chunks source passages, loads Pinecone, and uses OpenAI to explain retrieved evidence with PDF citations.

## Run it

The existing environment is ready:

```bash
.venv-corpus/bin/python -m streamlit run app.py
```

Open **http://127.0.0.1:8501**. The server listens only on the local machine. On a new machine, use Python **3.12**:

```bash
python3.12 -m venv .venv-corpus
.venv-corpus/bin/python -m pip install -r requirements.txt
.venv-corpus/bin/python -m streamlit run app.py
```

`requirements.txt` pins direct and transitive dependencies; `requirements.in` contains the direct dependencies. The current environment was installed with `uv pip --python .venv-corpus/bin/python` because it did not include pip.

## Try the three-minute demo

Open **[the guided demo](http://127.0.0.1:8501/?demo=1)** or select **Demo tour** in the sidebar. It follows an included Repatha passage through **PDF → XML → chunk → cited lesson → quiz**. Use Next, Back, Restart tour and Exit demo. The prepared example works without API keys or a published index and verifies its included sources before showing content. It makes no network calls and opens no databases. See the [demo walkthrough](docs/demo.md).

A fresh clone includes the source PDFs, canonical XML, application, tests and demo. Credentials, review databases, ingestion checkpoints, source snapshots and published manifests stay local and are **not included in Git**. The catalog and demo work immediately after dependency installation; live learning requires configured credentials plus a reviewed and published library. The pilot results below describe the original development machine, not a preconfigured cloud connection for every clone.

## Configuration and connectivity

Keys belong in the ignored `.streamlit/secrets.toml`:

```toml
OPENAI_API_KEY = "your-openai-key"
PINECONE_API_KEY = "your-pinecone-key"
```

Keep the real values local. TOML string values require quotes. Nonblank exported environment variables override these two credentials. **There is no `.env` loader.** Nonsecret index names, hosts and model settings belong in [config/app.toml](config/app.toml), not in the secrets file.

```bash
.venv-corpus/bin/python scripts/check_config.py --require-secrets --require-chat
.venv-corpus/bin/python scripts/check_connections.py
.venv-corpus/bin/python scripts/setup_pinecone.py --check
```

Development connectivity was verified on 2026-11-11 with both keys. OpenAI accepted a Responses request using `gpt-6.1-sol`. The configured Pinecone **amgenproduct** Documents API index was ready in AWS `us-east-1`; its verified hostname is saved in configuration. It uses `llama-text-embed-v2`, 1,024 dimensions and cosine. Its immutable schema uses `truncate=END`; the app rejects every document/query above its conservative **UTF-8 bytes + 8 ≤ 2,048** bound before transmission, preventing truncation of accepted input. New indexes can instead use `NONE`. For a different account, update the nonsecret index/model configuration and run the checks above. No index is created automatically.

See [configuration and Pinecone setup](docs/configuration-and-pinecone-setup.md).

## What you can do

- **Explore medicines:** search brand/generic names across 36 medicines and see which have published learning content.
- **Learn with chat:** select a medicine and source document, ask educational questions, inspect exact quotations and PDF pages, choose plain language or technical detail, and explicitly re-explain an answer using the same pinned evidence.
- **Guided learning:** explore essentials, mechanism and safety; take an extractive source-reading quiz and track session-local progress.
- **Manage sources:** inspect the 37-file inventory, build and download the consolidated XML, review individual passages beside the original PDF, and accept/reject/return them for review.
- **Chunk controls:** adjust target and sentence overlap, save named presets, preview exact embedded text, provenance, overlap and exclusions locally. Counts are clearly labeled conservative token bounds, not exact hosted-tokenizer counts.
- **Pinecone workflow:** preview a load, upload to a separate staging namespace, verify every record plus per-document searches, then explicitly publish. Test another configuration, compare retrieval on identical questions, and roll back to a retained verified build.

The main local flow is:

```text
Documents/*.pdf
  → Manage sources / Build XML
  → XML/AmgenProducts.xml
  → hash-bound passage review
  → section/sentence chunk preview
  → Load Pinecone into a staging namespace
  → verify fetch + search
  → Publish configuration
  → scoped retrieval → OpenAI explanation + evidence check → PDF citations
```

**The single XML is created by `amgen_explorer/extraction.py:build_corpus()`**, called by the Build XML button and `scripts/build_amgen_xml.py`. Building XML never uploads anything. Pinecone receives only reviewed, eligible chunks and flat metadata; complete PDFs/XML stay local.

## Current data and pilot

| Stage | Verified status |
|---|---|
| Extracted | 37 PDFs, 36 product identities, 1,439 physical pages |
| XML | Structural XSD, source hashes, exact page text and fragment spans validated |
| Reviewed demonstration | Four complete §12.1 passages: Aimovig, Tezspire, both Repatha documents |
| Pinecone | Six chunks loaded, fetched, searched and published |
| Live teaching | Four source-specific smoke checks completed; detailed responses/usage in `output/live-smoke.json` |

The four passages received **Codex source-fidelity review against rendered PDF pages**, not clinician sign-off. All other passages remain unreviewed. The broader catalog is available, but learning answers are limited to published evidence. Start with **How it works** for the three pilot medicines; for Repatha choose one source document. Essentials and safety will explain missing coverage until those passages are reviewed and published.

This custom XML is not FDA SPL. Normalized clinical fields remain unknown/unreviewed. Source filenames do not establish device applicability or supersession, particularly for the two Repatha files. Low-text/scanned pages are flagged; OCR is not implemented. Unresolved tables/figures remain excluded. Source text may be reviewed for faithful extraction without asserting current clinical validity.

## Test each feature

```bash
.venv-corpus/bin/python scripts/test_features.py all
.venv-corpus/bin/python scripts/test_features.py xml
.venv-corpus/bin/python scripts/test_features.py chunking
.venv-corpus/bin/python scripts/test_features.py indexing
.venv-corpus/bin/python scripts/test_features.py search
.venv-corpus/bin/python scripts/test_features.py teaching
.venv-corpus/bin/python scripts/test_features.py ui
.venv-corpus/bin/python scripts/test_features.py integration
.venv-corpus/bin/python scripts/test_features.py evaluation
.venv-corpus/bin/python scripts/test_features.py demo
```

Offline tests use fake providers and temporary storage; they need no API keys and make no paid calls. They cover corrupt PDF/build preservation, source-hash review invalidation, chunk coverage and limits, interrupted/idempotent loads, locks, stale publication, rollback, manifest tampering, scope isolation, unsupported claims, source instructions, snapshot downloads and Streamlit actions/reruns.

GitHub Actions runs the complete offline suite and checks the canonical XML against all included PDFs on each push and pull request. The [QA report](docs/implementation/release-qa-report.md) records the release checks and their limits.

Explicit live tests:

```bash
.venv-corpus/bin/python scripts/live_smoke.py
.venv-corpus/bin/python scripts/live_smoke.py --generate
```

The first checks published retrieval; `--generate` also calls OpenAI and checks citation resolution. These do not upload or publish. Reports preserve observed latency/usage and abstentions. Fifty evaluation fixtures cover all 37 PDFs and edge cases; **they are not a completed clinician-reviewed semantic evaluation**. See [evaluation notes](evals/README.md).

## Rebuild, load and publish from the CLI

```bash
.venv-corpus/bin/python scripts/build_amgen_xml.py --validate-only
.venv-corpus/bin/python scripts/build_amgen_xml.py
.venv-corpus/bin/python scripts/manage_corpus.py preview --target 600 --overlap 80
.venv-corpus/bin/python scripts/manage_corpus.py load --target 600 --overlap 80
.venv-corpus/bin/python scripts/manage_corpus.py runs
.venv-corpus/bin/python scripts/manage_corpus.py publish --run-id RUN_ID --target 600 --overlap 80
.venv-corpus/bin/python scripts/manage_corpus.py rollback --run-id PREVIOUS_RUN_ID
```

`load` stages and verifies; it does not publish. Publish requires exactly the same current source/review/configuration fingerprint. A changed PDF/extraction invalidates its old approvals. Old published answers retain their XML/PDF snapshots. Review decisions are append-only in `data/review.sqlite`; batch checkpoints are in `data/ingestion.sqlite`; manifests/records are in `data/manifests`; `data/active-corpus.json` is the atomic active pointer. No namespace cleanup/deletion occurs automatically. Retain `data/` with the local application.

## Design and architecture

- [Architecture, data flow and deployment diagrams](docs/architecture.md) — editable SVG and PNG.
- [Original design](docs/amgen-medicine-explorer-design.md), [implementation plan](docs/superpowers/plans/2026-11-11-amgen-medicine-explorer.md), [implementation reports](docs/implementation/progress.md).
- [Explore mockup](docs/mockups/01-explore-medicines.png), [learning mockup](docs/mockups/02-guided-learning-chat.png), [source-management mockup](docs/mockups/03-manage-sources.png).
- [XML tag guide](XML/xml-tag-guide.md), [local structural XSD](XML/prescribing-information.xsd), [pilot report](evals/pilot-report.md).

Local use is implemented. Shared/public hosting needs server-side authentication and authorization, durable storage and a deployment review; it has not been performed. Chat and progress remain in the current Streamlit session. OpenAI requests use `store=false`.
