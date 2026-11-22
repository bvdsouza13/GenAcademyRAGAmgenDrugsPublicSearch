# Failure assessment — 22 November 2026

The application has strong source-pinning and failed-build protections, but everyday search relevance, explanation availability, and self-service recovery need improvement. Chunk-size tuning alone will not resolve the principal problems.

This is an assessment of implementation `d63fb65` with the actual local configuration and published library. No application behavior, configuration, credentials, source files, active version, or Pinecone records were changed. Added artifacts are diagnostic tests, a read-only audit script, and this report. Faults involving deletion, corruption, outages, and partial writes were simulated in temporary storage with fake providers.

## Current configuration and live observations

| Item | Observed state |
|---|---|
| Library | 37 documents, 36 medicines; active manifest expects 9,110 records |
| Active run | `fac1a4e52d6904672ccf1882b520b83beaef77bf581aa729b5d7461e5bb110a6` |
| Chunk settings | 600 target / 80 overlap; conservative UTF-8 byte budgets, not exact model tokens |
| Teaching retrieval | `top_k=10`, `evidence_token_budget=4000`; continuation expansion can yield more than ten passages |
| Home search | Defaults to 20 displayed hits and 60 semantic candidates, separately from teaching `top_k` |
| OpenAI | `gpt-6.1-sol`, low reasoning, 4,096 output tokens, 60-second request timeout |
| Pinecone | Index `amgenproduct`; configured schema, host, API and embedding profile pass the live check |
| Current stored-record verification | **All 9,110 expected records fetched and matched**, with search visibility in all 37 document scopes; completed in 45.6 seconds without writes |
| OpenAI authentication | Model check returned **HTTP 401 twice**. The key was present, loaded from `.streamlit/secrets.toml`, with no environment override |
| Live teaching smoke | ACTIMMUNE and Repatha returned cited source excerpts with `provider_problem=true`; Tezspire returned a layout-limited source excerpt. No generated explanation succeeded in this check |
| Local server | Health endpoint returned `ok`; this does not establish provider readiness |

The 401 proves that the credential was rejected for those requests; it does not establish whether the key expired, was revoked, or belongs to the wrong account. Update the local secret and rerun connectivity plus an actual generation-and-verification test. Do not paste the key into chat or commit it.

## Test evidence

| Run | Result |
|---|---|
| Existing full regression suite, shuffled and network blocked | **349 passed + 21 subtests**, zero network attempts |
| New diagnostic cases | **48 passed, 23 strict expected failures** |
| Expanded full suite, shuffled and network blocked | **397 passed + 21 subtests, 23 expected failures**, zero network attempts |
| New diagnostics with expected-failure handling disabled | **48 passed, 23 failed at the intended defect locations** |
| Independent review/re-execution of recovery, teaching and operational diagnostics | 32 passed, 17 intended failures; no fixture/setup failures masking the findings |
| Real global search | 12 targeted queries, plus four smoke queries; no semantic outage observed |
| Simulated outage using the real pinned library | The same 12 targeted queries using local search only |
| Real document-scoped retrieval | One identical mechanism question against all 37 documents |
| Full remote integrity check | All 9,110 expected records matched; all 37 document scopes searchable |

Five existing PyMuPDF/SWIG deprecation warnings remain. Expected failures represent outstanding acceptance gaps, **not passing functionality**. Several are parametrizations of the same issue; 23 is a count of failing test instances, not 23 distinct root causes.

Tests: [search](../../tests/test_failure_search.py), [recovery](../../tests/test_failure_recovery.py), [teaching](../../tests/test_failure_teaching.py), [operations](../../tests/test_failure_operations.py). New reusable audit: [assess_failure_modes.py](../../scripts/assess_failure_modes.py).

## Priority 1: restore explanations and correct search relevance

### Authentication and readiness

OpenAI is currently unavailable, even though the app runs and search works. The source-only fallback behaves honestly and retains citations. However, `scripts/live_library_check.py --chat` still exits successfully when all attempted explanations fall back to source quotations. A simulated provider failure reproduced this misleading readiness signal.

**Tweak:** distinguish source-reading availability, Pinecone retrieval, OpenAI authentication, and successful verified generation. Give the smoke script a required-generation acceptance mode, with intentionally layout-limited cases evaluated separately. Show the last successful check time in Admin, with a simple learner-facing “Source reading available; explanations unavailable” state. Preserve sanitized error details such as HTTP status without exposing provider bodies or credentials.

### Named questions and unrelated results

| Query | Live result | Simulated Pinecone outage |
|---|---|---|
| `Prolia` | 20 PROLIA passages | 20 PROLIA passages |
| `What is prolia` | 1 PROLIA passage, 19 from other medicines | Same product-count pattern |
| `What is ACTIMMUNE` | 1 ACTIMMUNE passage, 19 from other medicines | Same product-count pattern |
| `qzxvnmqzxvnm` | 20 drug passages | No results |
| `How do I bake sourdough bread?` | 20 drug passages | 20 drug passages |
| `ACTIMUNE` | 20 ACTIMMUNE passages | No results |

These are relevance failures, not evidence of wrong source identity or invented text. Results remain linked to real pinned documents.

Root causes in [search.py](../../amgen_explorer/search.py): `_lexical_ids` ORs every query token, including conversational words; the name boost only recognizes a whole-query alias; final document round-robin promotes different medicines before a second passage from the intended medicine. Semantic neighbors have no relevance/answerability gate.

**Tweaks, in order:**

1. Recognize brand names within a question and prioritize relevant passages. Preserve global content search; offer a visible scope chip instead of silently imposing an ambiguous generic-name filter.
2. Remove conversational filler from lexical matching while retaining meaningful terms, qualifiers and negation. Diversify only among sufficiently relevant documents.
3. Add a calibrated relevance check and a useful no-results response. Do not treat a fixed raw vector-score threshold as universally reliable without evaluation.
4. Add local typo suggestions so degraded search explains “Did you mean ACTIMMUNE?” rather than appearing to lose the medicine.

The explicit product filter already works in isolated tests and is a temporary workaround. Both Repatha document variants remain discoverable and separate.

## Priority 1: make stored-library status verifiable and repairable

Two destructive scenarios were simulated only against an in-memory provider:

1. Build and activate a library, delete its remote records, and repeat the unchanged Build action. It returns `verified` / Ready while the fake namespace remains empty.
2. Delete a verified candidate's remote records. Use configuration correctly refuses activation and preserves the old active library, but retrying that candidate cannot repair it.

`IndexService.ingest` returns an already-verified manifest without fetching remote records. An unchanged active build skips activation verification. Completed batch checkpoints also assume previously acknowledged records still exist.

**Tweak:** add one Admin **Verify / repair library** action for the entire collection. Compare actual stored records with the immutable local set; upload missing/mismatched records when repair is requested; recheck document search visibility; update the verification timestamp only after success. Keep the previous library active during repair. Label the existing count “Records verified at last build” until refreshed.

This finding does **not** mean the real namespace was deleted. It is a reproduced recovery defect. A separate live read-only check fetched and matched **all 9,110 expected records** and confirmed all **37 document scopes** searchable in 45.6 seconds. The stored library is intact today. This verifies expected records; it does not enumerate unexpected extra records. The audit script supports `--verify-remote` to repeat this check without repairing or changing anything.

## Priority 1: improve evidence selection and teaching safeguards

### Source-only answers are common under this configuration

For the exact question **“How does this medicine work? Explain its mechanism of action.”**, live retrieval across all 37 documents produced:

| Gate outcome before OpenAI generation | Documents |
|---|---:|
| Eligible to attempt generation | 22 |
| Layout/extraction restriction forces source fallback | 11 |
| Incomplete continuation context forces source fallback | 4 |

Thus **15/37 document scopes (40.5%)** fall back for this question even with a working OpenAI credential. This is one prompt per document, not an overall answer-success rate. Different questions retrieve different passages; the three-question smoke check therefore has different layout outcomes. “Eligible” does not mean a generated answer would be correct or pass verification.

The active records include 1,999 layout-limited chunks out of 9,110 (21.9%) and 102 continuation chunks. Every document has at least one layout-limited record. These flags are valid reasons for caution, not reasons to disable the safeguards.

An isolated overview-query test also showed canonical warning passages exhausting the 4,000-byte evidence budget before the sole relevant indications passage. A 7,000-byte test budget admitted that passage, confirming budget/order starvation; it does not establish an optimal global budget.

**Tweaks:** allocate evidence by question intent and section, reserve space for relevant facts and required safety qualifiers, and retrieve continuation groups together. Compare 4,000 / 6,000 / 8,000 byte budgets on representative questions. Improve table/reading-order extraction where needed; do not silently discard necessary flagged qualifiers just to make generation succeed.

### Inconsistent provider-outage behavior

Global search correctly falls back to verified local text for simulated 401, 403, 429, 500 and 503 errors. Chat/quiz evidence retrieval propagates a Pinecone failure despite retaining local source records. The UI handles the action failure, but no new cited lesson is produced.

**Tweak:** reuse verified local search for document-scoped chat and quizzes during an outage, label the result as degraded, and preserve all source, scope, layout and completeness checks.

### Follow-up and quiz safeguards

The answer's claims receive citation and entailment checks, but generated follow-up strings do not. A fake provider response containing an unverified treatment instruction survived into `response.followups`, which the UI displays. Three personal-treatment paraphrases also bypassed the deterministic phrase filter.

These tests establish **validation gaps with injected provider output and phrase-matching gaps**, not observed unsafe live-model answers. The live OpenAI credential failure prevented such model validation.

**Tweak:** use a vetted set of educational follow-ups or validate generated follow-ups for scope, evidence and treatment instructions. Improve intent routing beyond a small phrase list while retaining model-level safeguards.

Quizzes always place the correct option first and reuse the same extractive structure. They also accept layout-limited or incomplete continuation passages that the teaching path withholds. Randomize answer placement without embedding the answer in the rationale position, diversify question forms, and share the same evidence-eligibility checks across chat and quizzes.

## Priority 2: recover gracefully from local damage

| Simulated failure | Current behavior | Recommended recovery |
|---|---|---|
| Existing PDF corrupted, original bytes reuploaded | Classified as a duplicate; damaged file remains | Hash the existing destination; restore it when replacement is explicitly requested |
| Working consolidated XML malformed | Pinned search can continue, but Build fails while parsing working XML | Regenerate XML atomically from the validated registry and intact PDFs; retain the published snapshot |
| Unrelated historical run JSON malformed | Status raises; Home and Admin depend on that status | Isolate invalid historical entries and show a repair notice; keep strict validation for active/selected runs |
| Active pointer unreadable | Startup stops before Admin navigation | Provide a configuration/recovery shell and restore only a separately validated retained version |
| PDF mixes readable and image-only pages | Readable coverage can be complete while image-only pages are excluded | Display searchable-page coverage and OCR-needed exceptions prominently |

An entirely unreadable synthetic PDF was rejected safely. The mixed-page test is a feature limit: “complete” currently means complete extracted readable-character coverage, not that every visual element in every PDF is searchable.

## What the tests handled correctly

- Failed registry write rolls back changed sources and a partially added file.
- Concurrent library operations fail before provider writes.
- Source changes during an upload prevent activation and preserve the active pointer.
- Repeated 429/503 upload errors stop after four attempts; 401 stops after one.
- Partial upload acknowledgement fails safely; retry resumes without duplicate IDs.
- Missing registered PDFs block a new build while pinned source snapshots remain available.
- Wrong-scope or altered semantic hits are excluded; citations stay pinned to their source/version.
- OpenAI timeout, refusal, incomplete output, malformed JSON, and errors in either generation or entailment checking withhold the paraphrase and retain source quotations.
- Invalid citation IDs, mixed document evidence, and oversized/empty retrieval questions are rejected in the tested paths.
- Demo mode remains available without loading service configuration.

## Configuration tweaks to consider

| Setting / behavior | Recommendation |
|---|---|
| `OPENAI_API_KEY` | Resolve the current 401 first; run actual verified generation afterward |
| Chunk target/overlap `600/80` | Keep as baseline while fixing ranking. Compare `900/80` afterward; there is no evidence that larger chunks fix these failures |
| Evidence budget `4000` | Experiment with `6000` and `8000` alongside intent-aware selection; these values are conservative bytes, not model tokens |
| Retrieval `top_k=10` | Evaluate with the evidence budget and relevance precision; raising it alone does not fix home search or omitted context |
| Provider timeout `60` | Add an overall response deadline and separate retrieval/generation/verification status; two sequential OpenAI calls can each consume their timeout |
| Upload backoff | Honor provider retry guidance and use exponential backoff with jitter; current waits are only 0.25, 0.5 and 1 second |
| Retained chunk experiments | Show estimated usage and provide deliberate retention cleanup; each distinct full build creates another retained namespace/artifact |
| Local deployment | Keep loopback binding. `auth_enabled=true` is not an implemented hosted security switch; hosted roles and authorization require implementation |

The timeout, capacity, retention and hosted-deployment recommendations follow from code/configuration review. No sustained load, billing, multi-machine deployment or genuine prolonged provider outage was measured.

## Make evaluation reflect the real home page

The current suite has 42 retrieval questions, of which **37 supply a product/document filter** and only five are global. Thirteen behavioral fixtures are retained separately and not scored by the chunk-comparison runner.

A new metric-characterization test demonstrated that one relevant result followed by nine irrelevant results receives the same document recall, reciprocal rank, quote coverage and global contamination score as the relevant result alone. That explains how strong previous retrieval scores can coexist with a noisy home page.

Add unfiltered natural-language brand questions, typos, generic-name ambiguity, out-of-library questions, mixed topics, safety/overview queries and multi-turn follow-ups. Measure precision and graded relevance in addition to recall, no-answer behavior, generated-answer availability, qualifier retention and citation support. Compare chunk configurations only after these checks represent the learner experience.

## Reproduce

```sh
# Complete offline regression, including explicit known gaps.
.venv-corpus/bin/python scripts/test_offline.py --shuffle-seed 20261123

# Show the outstanding desired-behavior failures directly; intentionally nonzero.
.venv-corpus/bin/python -m pytest -q tests/test_failure_*.py --runxfail --tb=short

# Local inventory/coverage audit; no provider calls.
.venv-corpus/bin/python scripts/assess_failure_modes.py

# Explicit read-only live probes; these consume Pinecone API usage.
.venv-corpus/bin/python scripts/assess_failure_modes.py --live --verify-remote
.venv-corpus/bin/python scripts/check_connections.py
```

Raw evidence is under `output/failure-assessment/` (ignored runtime output): `full-offline-tests.log`, `confirmed-failures.log`, `connectivity.json`, `openai-diagnostic.json`, `live-smoke.json`, `search.json`, `library-audit.json`, `remote-verification.json`, and `preservation-check.json`. The default audit output is overwritten on a later invocation; pass `--output` to retain separate runs.

## Confidence and limits

Confidence is **high in the source-pinning and tested failed-build isolation**, **moderate in local prototype usability**, and **insufficient for unattended operation or broader deployment** until the P1 failures are resolved. These are engineering judgments, not measured probabilities. The earlier release assessment should not be read as covering the newly reproduced scenarios.

No clinical review, source-label currency validation, successful live OpenAI generation, comprehensive adversarial-model evaluation, sustained concurrency/load test, real disk exhaustion, OS power-loss test or remote deletion was performed. Existing safeguards must remain in place while improving usefulness. The audit compared 55 production configuration/source/manifest files before and after testing with no changes; the active library remained unchanged.
