# Future-feature roadmap

This is a proposed delivery order grounded in the current implementation. These features are not implemented by the regression-hardening release.

## First: extend trustworthy coverage

| Priority | Feature | User benefit | Completion criteria |
|---|---|---|---|
| 1 | Reviewer workbench for complete medicine lessons | More medicines can answer questions about approved uses, limitations, warnings and mechanism. | Explicit review assignments; source/PDF comparison; separate extraction-fidelity and clinical approval; visible review history; publication only for eligible content. |
| 2 | Clinician-reviewed evaluation dashboard | Makes retrieval and answer quality measurable before expanding coverage. | Representative questions per medicine/section and difficult refusal cases; expected passages; retrieval coverage and citation accuracy; unsupported-claim and material-qualifier checks; failures block promotion. |
| 3 | Label version and update management | Learners can see which label version supports an answer. | Official source URLs, retrieval dates and revisions; exact old/new diffs; changed passages require fresh review; explicit handling of supersession and presentation differences. |
| 4 | Coverage map for each medicine | Explains which questions the library can currently support. | A medicine-by-section grid showing absent, extracted, reviewed and published states; prompt suggestions limited to available evidence. |

## Next: improve ingestion and learning

| Priority | Feature | User benefit | Completion criteria |
|---|---|---|---|
| 5 | OCR and layout-aware table review | Makes scanned pages and difficult tables usable without losing units or row/column relationships. | Confidence and layout flags; page overlays; table structure preserved; uncertain content kept out of automatic publication until reviewed. |
| 6 | Saved learning paths and stronger quizzes | Gives learners a useful return experience. | Persistent progress and bookmarks; source-backed quizzes beyond the current extractive check; varied answer ordering, hints and explanations; optional plain-language/technical tracks. |
| 7 | Better search and chunk experiment evaluation | Helps find relevant passages and choose chunk settings using evidence. | Keyword plus semantic retrieval; section filters; evaluated reranking; side-by-side passage coverage, citation correctness, latency and cost for identical questions. |
| 8 | Accessible presentation and export | Makes lessons easier to read and share. | Keyboard and screen-reader audit; responsive browser checks; glossary definitions linked to sources; exportable lesson notes with label revision and citations. |

## Before shared hosting

| Priority | Feature | User benefit | Completion criteria |
|---|---|---|---|
| Required for sharing | Authentication and roles | Separates learners, reviewers and publishers. | Server-enforced permissions, isolated user state, audit records, authenticated deployment and secret management. |
| Required for sharing | Durable jobs, backup and recovery | Keeps uploads and reviews reliable across restarts and multiple users. | Persistent shared storage; managed background jobs; concurrency control; tested backup/restore; explicit retention and namespace cleanup. |
| Required for sharing | Operational dashboard and spending controls | Makes failures and usage visible. | Sanitized error logs; health checks; request latency, token usage and cost; bounded retries; cancellation; quotas and alerts; no raw credentials or unnecessary chat content in logs. |

The recommended next milestone is broader reviewed content plus the evaluation dashboard. These address the current limitation that live learning covers four mechanism passages across three medicines. Hosting should follow the security, recovery and evaluation work rather than serve as a substitute for it.
