# Condition relevance and educational release — 22 November 2026

This release follows the eight-area reliability remediation. It addresses the reported query “What can treat migraine?”, applies the same source-use relevance rules to search and learning context, and adds **This is Test App for Educational Purposes** beside the Amgen logo. The app remains a local educational source explorer.

## Gaps and fixes in this release

| Gap | Implemented change |
| --- | --- |
| Generic “treat” matches filled results after the correct migraine result | Separate treatment/prevention intent from condition words. Require a positive use relation about the named medicine; “intent-to-treat” cannot establish a use. |
| A condition could occur as an adverse event, comorbidity, negation or another medicine’s indication | Match the condition to the medicine’s asserted use, retain qualifiers and exclude unsupported relations. Indications rank ahead of anchored supporting patient/study evidence. |
| A fixed result quota encouraged irrelevant neighbors | Return only eligible evidence, with a maximum rather than a minimum result count. The UI explains the loaded-library scope and preserves preventive/acute and population wording. |
| Normal chat retrieval and later section expansion could bypass discovery filtering | Filter the complete scoped context through the shared policy before packing, for both semantic and local outage paths. Unrelated subsections cannot re-enter. |
| Valid primary indication text could be crowded by flagged lower-tier summaries | For treatment teaching, use complete primary indication groups when available. Keep their own layout flags and qualifiers; general approved-use prompts retain normal section routing. |
| Saved responses or direct quiz calls could bypass a newer relevance rule | Recheck the actual question at the final teaching, re-explanation and quiz boundary. Mismatched treatment evidence cannot become a generated answer, source-only fallback or quiz. |
| A valid indication could be split into a parent sentence and heading, or into continuations | Carry complete source groups together within the same pinned identity. Missing partners or insufficient budgets prevent partial proof. Original text, pages and layout flags remain unchanged. Fallback quotations and generated-answer verification/citations retain linked qualifiers; fragment-dependent quizzes decline rather than present a partial answer. |
| Therapeutic goals could be confused with the population receiving them | Keep disease treatment distinct from preventing its complications, increasing bone mass during cancer therapy or reducing infection during chemotherapy. Exact-source adversarial regressions cover those distinctions. |
| Malformed retained continuation metadata could reach group sorting | Validate continuation indices before sorting and return a safe evidence limitation instead of a type error. |
| Verification could lack the antecedent for “both disorders” in a cited fragment | Give the verifier the same validated, bounded source context already used for generation, solely to resolve references and check qualifiers. Quoted support remains mandatory. The ACTIMMUNE live failure exposed this gap and passed after the fix. |
| Educational status was not explicit beside the brand | Display the requested notice in the shared sidebar, including the prepared demo. |
| Documentation lagged the new context flow | Refresh README, current product/technical/setup/demo/evaluation/roadmap guides and regenerate all three SVG/PNG architecture diagrams. |

The earlier [eight-area remediation report](reliability-remediation-release.md) remains the detailed record of previous fixes: conversational search and evaluation; actual generated-answer readiness and bounded retries; exact Pinecone verification/repair; local recovery; complete context and local fallback; vetted follow-ups and stable quizzes; native layout/page coverage; and retention/usage/capacity visibility. Those protections remain in place. Cleanup remains disabled pending durable historical-reference tracking.

## Source and deployment contract

Runtime ranking is `intent-relevance-v3`; immutable lexical artifacts remain `global-rrf-v1`. Existing configuration, keys, embedding model, chunk settings, XML and Pinecone records need no migration or rebuild. The checked full-library run contains 10,641 records across 37 PDFs and 36 medicines, covering 1,439 source pages.

- Run: `47b75fa785673734b5c00c994c6b289fc211e85694271d11bfc6c51f487c0742`.
- XML SHA-256: `f6b6786246c8bcd09233ead3e4f2d675886f7bf4df23b8d68d2904df435e41cc`.

## Verification

The final verification record covers the following checks. Offline tests use fake providers and temporary storage; live checks use the existing pinned library and explicit read-only queries.

| Check | Observed result |
| --- | --- |
| Shuffled full offline regression, seed `20261123` | **773 tests and 21 subtests passed**, zero failures, zero network attempts; five existing PyMuPDF/SWIG deprecation warnings. Elapsed 79.08 seconds. |
| Frozen condition-use fixture | 12 cases / 24 query formulations passed locally and live; 10 cited PDF documents resolved, zero citation failures, no live degradation. Product sets and leading indication proof are checked independently of the matcher. |
| Unchanged learner suite | All 51 local result rows were identical to the pre-change baseline: hit IDs/order, outcomes, relevance measurements and behavior results. Same run and suite hash, zero provider calls. This is local discovery preservation, not a new live holdout precision measurement. |
| Live ordinary workflow smoke | Four searches passed: ACTIMMUNE, latex, storage temperature and interferon content. All three teaching contracts passed: verified ACTIMMUNE generation, scoped Repatha evidence and preserved Tezspire layout fallback. |
| Live condition teaching | AIMOVIG produced a verified explanation and technical re-explanation using the same evidence; OTEZLA migraine context abstained with zero model requests; PAVBLU returned its complete parent/heading source pair with its limitation and zero model requests. The standard AIMOVIG mechanism quiz passed. |
| Sources | XML schema passed; all 37 PDF hashes and all 1,439 page-text round trips verified. |
| Native browser/UI | Preview displayed the notice beside the branding. “What can treat migraine?” displayed one medicine, one source document and four passages, led by the AIMOVIG indication including preventive use and adults. Main/demo UI regressions also check the notice. |
| Documentation | Three SVG/PNG diagram pairs regenerated and visually inspected. Current guide links checked without missing local targets. Historical reports retain their original measurements. |
| Independent review | Exact-source and adversarial probes found and verified fixes for population/goal confusion, other-medicine attribution, prior therapy, qualifier leakage, malformed continuations and incomplete output/verification context. No unresolved release-blocking findings remained. |

The first full run found a generic approved-use routing regression; the original test was kept and the router corrected. Live AIMOVIG initially fell back because of a lower-tier flagged Highlights supplement; primary indication selection fixed that without dropping primary-source restrictions. ACTIMMUNE initially failed support verification because a cross-passage reference lacked its antecedent at verification time. Diagnostic capture established the gap; supplying already-validated context fixed it, and the final strict live smoke check passed. These failures are part of the test record, not erased by the final passes.

Ignored local reports are under `output/condition-search/`: `release-regression.log`, `local-release.json`, `live-final.json`, `holdout-candidate.json`, `live-context.json`, `live-smoke-resolved.json`, `xml-validation.log` and the intermediate diagnostic logs. The frozen condition fixture SHA-256 is `87d8e34717d5cf69e32096f551d48a6eadc37606418802697a6c53002a2eb66b`. The 51-case suite hash is `d4ef0f5397b6783ecfa8a338b40f33ee6528a9eb55556a846e09407d092fe545`.

## Delivery

Feature branch: `condition-search-relevance`, based on main `579af1d`. Code, tests, current guides and regenerated diagrams are committed together on this branch before integration into main. Credentials, runtime data and diagnostic reports remain ignored. The original XML, active pointer and retained manifest/artifact hashes are checked against the 23-file pre-change snapshot; no ingestion, upsert or activation is part of this release.

Confidence is high for the exercised local workflows and failure contracts. Arbitrary clinical phrasing and model output still require the source checks and conservative fallback described below.

## Practical limits

The condition matcher is a finite conservative text policy, not a comprehensive clinical ontology. Unseen synonyms, complex sentence structures and population constraints can produce omissions. Bare condition queries intentionally remain general content search. The added source-audited suite checks exact medicine sets and leading supporting indication evidence; it does not certify every lower-ranked passage, all possible treatments, medical correctness or current labeling. Unknown or negative-use questions can abstain.

Mechanism, safety, dosing and storage questions retain their topic-specific context. The current standard quiz asks about mechanism; applying the shared boundary does not turn it into a treatment-recommendation quiz. Table/figure uncertainty still prevents unsupported interpretation, even when a discovery result is relevant. Personal treatment selection remains outside scope.

## Reproduce and operate

```bash
.venv-corpus/bin/python scripts/test_offline.py --shuffle-seed 20261123
.venv-corpus/bin/python scripts/check_condition_search.py --output output/condition-search/local.json
.venv-corpus/bin/python scripts/check_condition_search.py --live --output output/condition-search/live.json
.venv-corpus/bin/python scripts/live_library_check.py --chat --output output/condition-search/live-smoke.json
.venv-corpus/bin/python docs/diagrams/render_diagrams.py
.venv-corpus/bin/python -m streamlit run app.py
```

The offline suite blocks network access. The condition checker defaults to local search; `--live` and the live smoke script explicitly consume provider queries. None of these verification commands builds or uploads a library. See [architecture](../architecture.md), [evaluation](../../evals/README.md), [setup](../configuration-and-pinecone-setup.md) and [demo](../demo.md).
