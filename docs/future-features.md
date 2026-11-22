# Future-feature roadmap

Bulk source verification, whole-library content discovery and controlled chunk experiments are part of the current refactor rather than future proposals. Their actual verification scope belongs in the [release report](implementation/condition-search-release.md). This roadmap replaces the earlier plan centered on manually accepting every passage.

## Evidence and source quality

| Next work | Benefit and acceptance boundary |
|---|---|
| Clinician-reviewed evaluation | Independent representative cases for safety, variants, qualifiers, abstention and explanation support; retrieval scores alone do not establish medical accuracy. |
| Label update provenance | Verified acquisition URLs/dates, revisions, exact changes and explicit supersession/applicability decisions; preserve old citation snapshots. |
| OCR and layout-aware tables | Add readable coverage for scanned pages and trustworthy table structure; retain confidence, units and footnotes, and avoid inferred relationships. |
| Optional clinical review workflow | Record independent professional judgments separately from automatic extraction verification and historical source-fidelity review. |
| Richer section coverage inspection | Page/native-text coverage and layout exceptions now exist; extend to curated section completeness and source-backed query suggestions. |

## Learning and discovery

| Next work | Benefit and acceptance boundary |
|---|---|
| Persistent learning paths | Bookmarks, accounts and progress across sessions/devices, with version-pinned evidence and privacy controls. |
| Stronger assessments | More varied source-backed questions, hints and explanations beyond the current extractive reading quiz. |
| Evaluated search improvements | The current conservative treatment-use gate applies to discovery and learning context. Expand independently labeled synonyms, populations, qualifiers and sentence forms; study reranking and section filters against untouched holdouts. Retain source limits and variant isolation. |
| Accessibility and export | Keyboard/screen-reader review, responsive layouts and exportable notes retaining source revision/citations. |

## Before shared hosting

| Required work | Acceptance boundary |
|---|---|
| Authentication and roles | Server-enforced learner/operator permissions; Admin navigation alone is insufficient. |
| Durable jobs and recovery | Local exact repair and recovery now exist; add shared artifact storage, durable job cancellation, backups and a durable publication/conversation reference ledger before enabling cleanup. |
| Operations and spending | Readiness, bounded retries and recorded usage now exist; add quotas, alerts and provider billing reconciliation without credential or unnecessary chat logging. |

Public hosting, inferred clinical fact normalization, new embedding providers and cross-medicine treatment recommendations are outside this refactor. Keep scientific/clinical evaluation distinct from software correctness and extraction provenance.
