# Retention inventory and local capacity

The app can inventory retained versions and their local disk use. Cleanup is disabled because no version can currently be proven unreferenced. Nothing in this implementation deletes local files, remote documents, or namespaces; resetting experiment settings does not authorize deletion.

## Retention contract

`amgen_explorer.retention.plan_cleanup(config, selected_run_ids=())` reads local files only. `CleanupPlan` exposes `runs`, `snapshots`, `files`, `local_bytes`, `last_provider_usage`, `warnings`, and a content fingerprint. The default selection is empty. A selection expresses which runs an operator wants assessed; it does not establish that they are safe to delete. Run IDs must be 64 hexadecimal characters.

Each run reports its retained status, record count, recorded provider usage, local manifest/records/search-artifact bytes, shared snapshot bytes, and protected reasons. Known active, published, rollback and migration-reference-held runs are protected. Every run also has `reference_history_unproven`: current conversations are held in memory and historical publication events are not durably recorded on every manifest. A verified candidate without `published_at` could have been published earlier. Neither its age nor its current status proves the absence of those references. Corrupt manifests, missing selections and symlinks are retained or skipped with explicit reasons.

`apply_cleanup(plan)` validates the selection again and re-inventories known references and file contents. Its report identifies changes since preview and retained selections. It always returns an empty `deleted_run_ids`; repeated calls do not mutate state or call a provider. A newer rollback reference therefore remains protected even if it appeared after preview. No approval flag can bypass the missing reference proof.

`local_bytes` counts each regular file in the configured manifest and immutable corpus directories once. It excludes original source PDFs, working XML, databases, logs, reports, and remote storage. Per-run `shared_snapshot_bytes` is an attribution and must not be summed across runs; the snapshots list gives unique shared totals. Unexpected regular files in those two directories are included in the total, while symlinks are not followed. The plan retains a credential-free configuration internally for revalidation; callers should render the public attributes rather than serialize `_config`.

The latest run by creation time with saved usage supplies `last_provider_usage`, explicitly scoped to initial and resumed ingestion. These are accumulated provider-reported embedding tokens from ingestion, not a bill or complete retry accounting. The stored `usage_may_include_unreported_retries` flag remains visible. Remote storage and dollar cost are `None` (unknown); no price or storage estimate is invented. Prepared experiment record counts, token/byte guards and batching remain available from the existing ingestion preview. Healthy retained experiments are reused and reverified through the existing build/recovery path.

Repair operations write separate sanitized ledgers under `data/health/operations/` before and after each upload attempt. The immutable run manifest and its ingestion usage remain unchanged. Both explicit Repair and a repeated Build of a verified run use this accounting. Each ledger preserves reported embedding tokens, operation completion/interruption, an outstanding-request marker, and uncertainty from missing usage or unsuccessful requests. Interrupted repairs retain their known partial usage. Verification reports expose the associated repair ledger; the retained-run table aggregates known tokens across recorded repairs and exposes incomplete accounting. These totals cover recorded repair operations from this version; earlier repairs may be unreported. Search and verification request usage, remote storage and billing remain outside these embedding-token totals.

## Remote deletion capability

The [official Pinecone Documents API 2026-07 delete reference](https://docs.pinecone.io/reference/api/2026-07/data-plane/delete_documents) documents `POST /namespaces/{namespace}/documents/delete`. Its accepted response is HTTP 202; acceptance is asynchronous and is not proof that deletion has completed. The captured reference is in the ignored `output/remediation/pinecone-delete-docs.json`.

No deletion adapter was added. The blocking issue is the absence of durable reference evidence, independently of the documented deletion endpoint. No remote listing completeness, namespace deletion behavior, or deletion-completion capability is assumed. Local provenance and shared snapshots remain intact.

## Measured current corpus

Run the read-only benchmark with:

```sh
.venv-corpus/bin/python scripts/measure_local_capacity.py --iterations 3 --output output/remediation/local-capacity.json
```

The report was generated on 2026-11-22 at 19:45 UTC on macOS 26.2, arm64, Python 3.12.15, 10 logical CPUs. It used active run `fac1a4e52d6904672ccf1882b520b83beaef77bf581aa729b5d7461e5bb110a6`: 9,110 records, 37 documents and 1,439 source pages. The full test suite had completed before this measurement. No provider calls, uploads, activations or source/state writes were made. Only the ignored report was written.

Each session ran three queries and rendered the first pinned Actimmune PDF page after each query. One session produced three samples per phase; five concurrent threads produced fifteen. Search calls `search_local` with pinned corpus/record/artifact validation. Rendering uses `source_page`, which checks the pinned XML and PDF hashes. No integrity checks were bypassed and no validation cache was introduced.

| Concurrent sessions | Phase | Search median / p95 (ms) | PDF page median / p95 (ms) | Whole batch (ms) |
| --- | --- | ---: | ---: | ---: |
| 1 | Cold batch | 595 / 926 | 26 / 55 | 2,205 |
| 1 | Warm batch | 623 / 670 | 25 / 25 | 1,958 |
| 5 | Cold batch | 3,921 / 6,521 | 32 / 80 | 13,165 |
| 5 | Warm batch | 3,757 / 4,276 | 43 / 287 | 11,482 |

The process high-water RSS rose from 183,894,016 bytes after startup/corpus preparation to 3,575,742,464 bytes (3.33 GiB) over the complete benchmark. This is a process-wide peak including imports, shared objects and allocator/cache retention, not per-session memory or a measured leak. Five readers completed but had substantial search contention compared with one reader. This small local measurement does not establish a public hosting capacity or an operational concurrency guarantee.

“Cold” means the XML parser cache was cleared at the beginning of the batch; later iterations in that batch can be warm. OS filesystem caches were uncontrolled. The warm batch immediately followed the cold batch in the same process. Three samples per session and one PDF page cannot characterize every query, PDF or long-lived workload. PDF rendering timings exclude browser/Streamlit layout and network delivery. All timings include the existing integrity validation overhead.

The accompanying `output/remediation/retention-inventory.json` recorded seven retained runs and one shared snapshot, with 364,080,632 unique local bytes (about 347.2 MiB) in the stated inventory scope. The latest saved usage was 2,497,606 embedding tokens and carried the retry-accounting uncertainty flag. These are observations of the retained state at measurement time, not remote cost claims.

## Verification and remaining scope

Tests exercise zero-mutation preview and apply, explicit selection, active/publication/rollback protection, shared snapshots, concurrent reference changes, unavailable/corrupt manifests, malformed rollback metadata, symlink refusal, provider independence and repeated apply. An isolated real library also exercises one/five local sessions and pinned PDF rendering without state mutation.

Cleanup remains unavailable until durable publication and live-reference evidence can prove a selection safe and remote completion can be established before removing provenance. Full OCR, public hosting and clinical currency certification remain separate capabilities.

## Learner status validation

On the final 10,641-record candidate, one sequential comparison measured full history status at 12.595 seconds and learner status at 4.481 seconds. Home now omits the scan of five retained historical versions. Active manifest, record/artifact and pinned XML/PDF validation remain in both paths; Admin/Recovery still validate retained versions. This is a single status-call comparison, not a browser or capacity benchmark. The local report is `output/remediation/learner-status-comparison.json`.
