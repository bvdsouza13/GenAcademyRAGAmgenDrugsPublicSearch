> Historical pilot evidence. See [the current bulk-library release report](../docs/implementation/bulk-refactor-release-report.md) for the refactored application.

# Live pilot and handoff — November 11, 2026

The local Streamlit app is running at `http://127.0.0.1:8501`. Both keys authenticate. OpenAI returned a completed Responses answer using the configured `gpt-6.1-sol` model; the Pinecone control plane described the existing `amgenproduct` index as ready and compatible. No new index was created.

| Stage | Actual result |
|---|---|
| Local extraction |37 PDFs /36 products /1439 physical pages;4634 source/archive/candidate blocks |
| Validation |Compatible structural XSD, unique/resolving references, hashes and exact original page text passed |
| Source-fidelity review |Four complete mechanism-of-action §12.1 passages, compared with rendered original pages by Codex |
| Published evidence |Aimovig p7; both Repatha sources p10; Tezspire p5 |
| Baseline configuration |600/80 conservative token bounds;6 chunks;906 reported Pinecone embedding tokens; load+publish4.597s |
| Alternate configuration |900/80 bounds;5 chunks;1240 reported embedding tokens |
| Publication reliability |All records fetched and compared; sentinel searches per document; alternate publication and rollback to baseline succeeded |
| Final offline tests |145 passed plus21 subtests; five upstream PyMuPDF SWIG deprecation warnings |
| Independent review |One PDF-image-cache identity issue fixed with7 regressions; scoped re-review accepted |
| Runtime |Streamlit health HTTP200; catalog, live chat and original PDF citation page visually checked in Chrome |

The alternate configuration remains as a retained verified test namespace. The original six-chunk pilot is active. Both presets are saved locally. No old namespace or source was deleted.

## Live explanation observations

The final smoke question was “What target does this medicine bind to, according to section12.1?” It was asked separately in each of the four source-document scopes.

| Source | Retrieved passages | Result | Total retrieval+answer seconds |
|---|---:|---|---:|
|Aimovig|1|Supported answer, one resolving citation|6.648|
|Repatha, contains-rubber filename|1|Supported answer, one resolving citation|5.223|
|Repatha, latex-free filename|1|Supported answer, one resolving citation|5.647|
|Tezspire|3|Supported answer, one resolving citation|5.445|

These eight OpenAI calls (generation plus entailment check for each answer) reported **7660 total tokens**. Full responses, usage and provenance are in `output/live-smoke.json`. These numbers do not include every earlier connectivity/pilot/browser request and are not a billing total.

An earlier broader “How does this medicine work?” run yielded supported Repatha and Tezspire explanations, including Tezspire’s unresolved-mechanism qualifier. An Aimovig paraphrase failed entailment and was withheld. The app now provides a clearly labeled exact-source fallback with citations when a paraphrase fails; fake-provider tests verify that the rejected wording is never exposed. The initial outcomes remain in `evals/pilot-live.json`, rather than being rewritten as successes.

Two identical Tezspire questions were compared across the600/80 and900/80 builds, holding XML/review snapshot, embedding profile, product and evidence budget constant. Observed retrieval latency ranged0.194–0.233s. `evals/configuration-experiment.json` records source coverage and passages. This small experiment does not establish superior accuracy of either chunk configuration.

## What remains limited

Source-fidelity review is not clinician approval and does not verify that supplied labels are the current official versions. Only four mechanism passages are accepted. All remaining4630 archive/candidate blocks stay needs-review; archived pages intentionally overlap derived passages and are never indexed as duplicate evidence. Essentials/safety lessons will report insufficient coverage until corresponding sources are reviewed and published.

The50 evaluation fixtures cover each PDF and13 adversarial/scope/qualifier cases. Their provenance checks pass; they are not50 completed clinician-reviewed answer evaluations. No OCR was run; unresolved tables, figures, reading-order artifacts and oversized indivisible text remain explicit exclusions. Exact hosted-tokenizer parity is not asserted; the independent conservative byte guard protects the immutable END truncation setting.

The app is local-only. Session progress/chat is not shared across learners. Public deployment, authentication/authorization, a full accessibility audit and narrow/mobile browser verification are outside this handoff. Runtime/source snapshots remain in the supplied workspace; preserve `data/` for citation and rollback continuity.
