# Future-feature roadmap

Bulk source verification, whole-library content discovery and controlled chunk experiments are part of the current refactor rather than future proposals. Their actual verification scope belongs in the [release report](implementation/bulk-refactor-release-report.md). This roadmap replaces the earlier plan centered on manually accepting every passage.

## Evidence and source quality

| Next work | Benefit and acceptance boundary |
|---|---|
| Clinician-reviewed evaluation | Independent representative cases for safety, variants, qualifiers, abstention and explanation support; retrieval scores alone do not establish medical accuracy. |
| Label update provenance | Verified acquisition URLs/dates, revisions, exact changes and explicit supersession/applicability decisions; preserve old citation snapshots. |
| OCR and layout-aware tables | Add readable coverage for scanned pages and trustworthy table structure; retain confidence, units and footnotes, and avoid inferred relationships. |
| Optional clinical review workflow | Record independent professional judgments separately from automatic extraction verification and historical source-fidelity review. |
| Richer coverage inspection | Medicine/section coverage and layout limitations with useful source-backed query suggestions. |

## Learning and discovery

| Next work | Benefit and acceptance boundary |
|---|---|
| Persistent learning paths | Bookmarks, accounts and progress across sessions/devices, with version-pinned evidence and privacy controls. |
| Stronger assessments | More varied source-backed questions, hints and explanations beyond the current extractive reading quiz. |
| Evaluated search improvements | Study reranking and section filters against held-out expected evidence; retain whole-library coverage and deterministic variant isolation. |
| Accessibility and export | Keyboard/screen-reader review, responsive layouts and exportable notes retaining source revision/citations. |

## Before shared hosting

| Required work | Acceptance boundary |
|---|---|
| Authentication and roles | Server-enforced learner/operator permissions; Admin navigation alone is insufficient. |
| Durable jobs and recovery | Shared artifact storage, tested backup/restore, concurrency/cancellation and deliberate retention/cleanup. |
| Operations and spending | Sanitized diagnostics, actual provider usage, quotas, alerts and bounded retries without credential or unnecessary chat logging. |

Public hosting, inferred clinical fact normalization, new embedding providers and cross-medicine treatment recommendations are outside this refactor. Keep scientific/clinical evaluation distinct from software correctness and extraction provenance.
