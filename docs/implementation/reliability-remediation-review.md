# Independent remediation review — 22 November 2026

**Final code-review verdict: approved. No remaining Critical or Important findings.** Release testing and operational evidence are recorded in the [release report](reliability-remediation-release.md).

Independent package reviews covered search/retention, remote/local recovery, teaching/operations and extraction. A separate whole-branch review inspected the approved plan, implementation reports, current modules, UI/service/configuration boundaries, operational scripts, tests and documentation. Review probes used temporary storage and fake providers, never destructive tests against the live library.

## Findings corrected before release

| Finding | Correction and regression coverage |
| --- | --- |
| Malformed nested coverage data could raise an unexpected exception. | Validate its shape before reading fields; malformed variants now fail through the recovery contract. |
| Search evaluation could reuse judgments after PDF changes or confuse teaching limits with visible results. | Reject stale PDF judgments; evaluate actual visible result limits and record runtime ranking policy. |
| Recognized aliases could silently overconstrain discovery. | Keep content discovery global unless the user supplies explicit filters; preserve full-phrase matching and source variants. |
| Layout-policy-only changes could skip extraction migration. | Explicit Build compares both parser and layout policy and creates a separate candidate. |
| Personal-intent routing missed a patient phrasing; incomplete provider responses lost usage. | Expand finite routing cases and retain sanitized reported usage even when generated output is refused or incomplete. |
| An access-only readiness report could display a generated-answer success banner. | Both service and UI require explicit, verified generation; unchecked and stale results stay distinct. |
| The smoke test could accept generated output for a deliberately restricted source. | Require verified ACTIMMUNE generation and Tezspire source fallback; reject provider failures and unexpected generation. |
| Repair usage and retry uncertainty were lost after the in-memory run was discarded. | Persist per-operation accounting before/after requests, including interrupted repairs and repeated-build repair, separately from immutable manifests. |

The final focused fix suite passed 112 tests. The subsequent Home status optimization passed 76 focused tests, including four new regressions. Home omits only unused retained-history inspection; active record, XML, PDF and profile validation remains. Admin and Recovery retain full history checks. Browser verification established that the medicine suggestion callback works; native automation required keyboard activation after focusing a button, so no speculative widget rewrite was made.

The review also checked that all 37 legacy provenance-fixture changes preserved questions, exact quotes and PDF hashes, changing only XML hash/block references. The learner suite stayed frozen after holdout measurement.

## Accepted limits

Cleanup remains disabled because durable historical publication and conversation-reference evidence is incomplete. Cooperative deadlines reject late output but do not promise operating-system-level transport cancellation. OCR, clinical certification/current-label review and hosted authorization remain separate capabilities. Approval does not imply clinical accuracy or production hosting readiness.
