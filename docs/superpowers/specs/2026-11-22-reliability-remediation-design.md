# Reliability and learning-quality remediation design

**Status:** Approved by the user on 2026-11-22 ("Fix all the 8").

**Evidence:** [Failure assessment](../../implementation/failure-assessment-2026-11-22.md). The assessment produced 23 failing test instances across search, recovery, teaching and operational readiness, alongside 397 passing tests and 21 passing subtests.

**Pre-implementation correction:** The OpenAI credential issue has since been resolved. Authentication passed, and a real ACTIMMUNE explanation produced three citations and passed the application's entailment check in 9.23 seconds. Readiness detection still needs fixing; replacing the key did not fix the application defects. All 9,110 expected Pinecone records and all 37 document scopes passed the earlier live verification.

## Intent and recommended approach

Improve the existing local Streamlit learning application so general learners get relevant discovery, useful source-backed explanations and honest availability states, while an administrator manages the entire library without reviewing medicines individually.

The recommended approach is staged remediation of the current Python/Streamlit/XML/Pinecone/OpenAI stack. Existing source snapshots, exact citations and atomic publication provide a useful foundation. A replacement service architecture would add deployment and migration work without directly resolving the demonstrated defects. Configuration tuning alone cannot correct ranking, recovery or validation logic. The user approved this approach on 2026-11-22. Implementation and release evidence are recorded in the remediation release report.

Deliver independently testable work packages, with independent review of search, recovery and teaching boundaries. Keep query improvements separate from extraction migrations and storage repair.

## User experience

**Search & Learn:** Search all content by default. Recognize names inside questions, rank relevant passages first, suggest likely spelling corrections without silently changing the query, and show a useful no-results state for unrelated questions. Recognized names may be shown as optional scope chips. Ambiguous generic names and multiple-medicine discovery remain global; a lesson continues to use one selected source/device scope.

Learning displays one of three understandable states: verified explanation, source reading with a stated limitation, or unavailable evidence. During a Pinecone outage, verified local retrieval can support the same scoped learning flow. Personal treatment requests receive an educational redirect. Follow-up suggestions come from vetted templates. Quizzes share the explanation eligibility rules, vary answer position and remain stable across page reruns.

**Admin:** Retain the whole-library Build/update action and the existing chunk experiment/reset/revert workflow. Add one whole-library verification/recovery area: Verify library reads current state, and Repair becomes available for identified repairable issues. Last verification time, source-page coverage and provider readiness are visible. Detailed reports, retention controls and exceptional recovery options remain under Advanced/Details. No medicine-by-medicine review is introduced.

## Global constraints

- Implementation starts only after the user approves this proposal.
- Keep the existing local Streamlit, single consolidated XML, Pinecone Documents API and OpenAI Responses API architecture.
- Preserve whole-library administration and global content search; do not introduce individual medicine or passage approvals.
- Keep chunk defaults at 600/80 until controlled evaluation supports a change; chunk and evidence controls use conservative UTF-8 byte budgets, not exact model tokens.
- Preserve exact PDF/XML hashes, source spans, document/device distinctions, immutable artifacts and run-pinned citations.
- Never publish a generated medicine claim without its exact supporting quote and the existing independent entailment check.
- Keep unresolved layout, missing-context and unsupported-source restrictions; do not remove them to improve an answer-success percentage.
- Opening or rerendering a page must not initiate provider calls, uploads, repairs, reindexing or deletion.
- Use isolated candidates for source, parser, eligibility or chunk changes; preserve the prior active library until verification succeeds.
- Restore missing or mismatched remote records only from an intact pinned local record set, using identical IDs/content and the unchanged provider profile.
- Keep credentials and raw provider responses out of logs, artifacts, UI and Git.
- Retain published/active/rollback/reference-held versions; cleanup is explicit, previewed and never index-wide.
- Keep the server bound to 127.0.0.1; hosted authorization is a separate product change.

## Required outcomes

1. All 23 demonstrated failure instances become ordinary passing regression cases, with expected-failure markers removed only after genuine fixes.
2. Home-page scoring penalizes irrelevant results and tests unfiltered user queries. Expected answers are not secretly supplied as retrieval filters.
3. Existing and retained libraries remain readable after ranking changes without unnecessary re-embedding.
4. Historical verification is distinguished from a current provider check; connectivity and generated-answer readiness are separate.
5. Exact remote-record repair is resumable and verified, and an unavailable provider is never misreported as missing data.
6. Corrupted working PDFs/XML/history or an unreadable active pointer have actionable recovery paths. Invalid active or selected source data is never silently accepted.
7. Evidence selection preserves relevant facts, safety qualifiers and complete continuation groups. Local fallback retains all provenance and source-scope validation.
8. Quizzes and follow-ups cannot bypass the shared evidence and learning policies.
9. Clean narrative is not unnecessarily restricted merely because a separable table/figure occurs nearby; genuinely ambiguous layout stays restricted. Page coverage is explicit.
10. Retries, response deadlines, experiment usage, retained storage and diagnostic errors are bounded and understandable.
11. Documentation, demo, evaluation reports and operational scripts describe the implemented behavior accurately.

## Scope boundaries and honest completion

The 15/37 mechanism-query fallbacks are not 15 independently proven defects. Resolve avoidable retrieval/context/layout failures and publish before/after results for every scope. Keep appropriate abstention for genuinely unreadable or ambiguous evidence. Do not promise 37/37 generated answers.

This proposal fixes mixed-page coverage reporting and conservative layout boundaries. **Full OCR, clinical validation, automatic current-label certification and hosted multi-user authentication are not included.** They are additional capabilities, not implemented features to claim as repaired. Image-only content must be identified as unavailable to search, with original-PDF access and a clear OCR-needed status. Current printed revision metadata must not be labeled current or clinically reviewed.

Namespace deletion is not implemented in the present adapter. Retention work must verify the official API capability before adding remote cleanup. If safe deletion/reference validation cannot be established, retain the data and report that limitation; do not claim remote cleanup completed.

## Proposed configuration policy

Keep the existing embedding profile, OpenAI model and 600/80 chunk baseline. Compare evidence budgets 4,000 / 6,000 / 8,000 after selection changes. Surface separate home-result and teaching-retrieval controls in technical configuration, preserving current defaults of 20 home results, 60 semantic candidates and teaching top-k 10.

Add a 60-second overall learning-response budget, with individual cloud requests capped at the lesser of their configured timeout and the remaining budget. Late/unverified results must never be displayed as verified answers. Preserve four total upload attempts, adding bounded exponential backoff and jitter; honor a valid Retry-After only within the retry budget. Authentication/permission failures are not retried.

New optional settings receive validated compatibility defaults; existing config files must continue loading. Final values and calibration profiles are documented with the release evidence, and any default change must be justified by measured results.

## Release acceptance

Run offline unit/integration/AppTest suites, expected-failure removal checks, held-out search evaluation, provider-fault simulations, local corruption and repair tests, migration/rollback tests, and bounded live checks. Require source/citation resolution and scope isolation on all retained acceptance fixtures. Compare all 37 document scopes before/after, and verify every expected remote record for any candidate proposed for activation.

Do not delete real active data to simulate faults. Use temporary storage/fake providers for destructive cases and isolated namespaces for bounded live write tests. A final release report must distinguish generated answers, expected source fallbacks, unresolved content limitations, provider availability, measured usage and untested deployment risks.
