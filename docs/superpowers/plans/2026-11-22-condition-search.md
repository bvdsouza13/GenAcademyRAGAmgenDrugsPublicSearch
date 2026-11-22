# Condition Search Implementation Plan

> **For agentic workers:** Use test-driven development and independent review. The user approved implementation of steps 1–3; routine implementation and release decisions are delegated.

**Goal:** Return condition-supported treatment evidence without padding results with generic word matches.

**Architecture:** Add compatible intent fields and a focused evidence policy to existing hybrid retrieval. Preserve immutable artifacts, source text and explicit scopes; expose the search mode to the result UI.

**Tech Stack:** Existing Python, SQLite FTS/token fallback, Pinecone Documents API and Streamlit. No new dependencies.

**Spec:** [Condition-search design](../specs/2026-11-22-condition-search-design.md).

## Constraints and review focus

- No upserts, re-embedding, XML changes, reranking provider or new mandatory configuration.
- No hardcoded medicine answer; distinguish condition evidence from adverse-event mentions and another medicine's use.
- Keep preventive/acute and population qualifiers, negative statements and unknown-condition behavior.
- Preserve ordinary content search, variants, explicit filters, source pins and old artifacts.
- Return fewer qualifying results rather than fill a result quota; explain the limited library scope in empty states.

## Task 1 — Intent and evidence policy

Owner: implementation agent. Files: `query_intent.py`, `search.py`, optional `condition_evidence.py`, `tests/test_condition_search.py`.

- [x] Reproduce treatment/ITT false positives with failing real-search tests under both lexical engines and provider outcomes.
- [x] Add compatible intent parsing and positive source-relation eligibility; prioritize indications and bump runtime ranking version only.
- [x] Test unsupported/multiword conditions, negation, incidental mentions, acute/preventive distinctions, ordinary search and scope isolation.

## Task 2 — User feedback and independently sourced acceptance cases

Owner: root, with a read-only source audit. Files: `ui/search_results.py`, `tests/test_search_experience.py`, new condition evaluation fixture/runner if required.

- [x] Add failing UI tests for one source group with supporting passages and a condition-specific empty state.
- [x] Explain treatment-evidence mode without implying complete medical coverage; retain existing source actions.
- [x] Freeze condition/source expectations from local prescribing information and run before/after queries without changing the original learner holdout.

## Task 3 — Verify and release

Owner: root; independent reviewer checks the combined changes.

- [x] Run focused and shuffled offline regressions; review real-corpus results and original held-out search behavior.
- [x] Run bounded live read-only queries, verify zero corpus/index mutations and record limitations.
- [ ] Refresh documentation/test grouping, commit, integrate into the user's local app and GitHub main under existing authorization, and verify launch.

## Confirmed additions — all context and educational release

- [x] Apply one source-use policy before cloud/fallback retrieval packing and reject stale/mixed treatment bundles at chat/re-explanation/quiz boundaries.
- [x] Preserve complete linked indication fragments and continuation groups, unchanged source text, population limits and extraction flags.
- [x] Test ordinary mechanism/safety/storage/dose paths, direct quiz consumers and pinned generic-name catalog support.
- [x] Add the educational Test App notice beside the logo in main and demo navigation.
- [x] Regenerate solution, data-flow and deployment diagrams; refresh all current guides and write a consolidated fixes/release report.
- [ ] Push the reviewed feature branch first; merge into main, verify the local release and push main.
