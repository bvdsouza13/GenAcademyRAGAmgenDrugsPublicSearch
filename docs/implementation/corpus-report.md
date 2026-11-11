# Corpus implementation report — 2026-11-11

Tasks 1–2 have runnable local extraction, loading, review and chunking implementations. Root owns model/facade/cloud/UI integration; this worker made no cloud calls, recorded no clinical/source approvals, and edited no UI, provider service or configuration files.

## Delivered files and APIs

- `amgen_explorer/extraction.py`: reusable original PyMuPDF extractor, `build_corpus(source_dir, output_path)`, attached `CorpusBuildError.report`, atomic canonical replacement and content-addressed prior snapshots.
- `scripts/build_amgen_xml.py`: thin CLI using that same extractor, plus read-only `--validate-only`.
- `amgen_explorer/xml_store.py`: safe XML parsing (rejects DTD/entities), mandatory structural XSD validation, IDs/references, source document/page checks, exact fragment hashes/slices and the supplied `Corpus` contracts.
- `XML/prescribing-information.xsd` and `XML/xml-tag-guide.md`: compatible template/generated structural schema, deliberately separate from clinical or FDA SPL validation; documented provenance and limitations.
- `amgen_explorer/review.py`: lazy `ReviewStore(path)` with append-only hash-scoped decisions; one read-only snapshot for consistent statuses/fingerprint, summary and zero writes on an untouched preview.
- `amgen_explorer/chunking.py`: validated immutable `ChunkConfig`, canonical configuration fingerprint, deterministic section/sentence chunks, model guard, exact source-span metadata, explicit exclusions and optional hash-pinned local tokenizer artifact.
- `tests/test_xml_pipeline.py` and `tests/test_review_and_chunking.py`: 23 meaningful corpus cases, including parameterized invalid settings.

Root compatibly extended `BuildReport` with input counts, failed files/pages, schema status and snapshot path. No incompatible shared model changes were made. The new `ReviewStore.snapshot(corpus)` helper augments the supplied interface to avoid thousands of SQLite connections and bind preview decisions to one read snapshot.

## Actual local extraction verification

The actual canonical collection was rebuilt from all supplied PDFs using:

```sh
.venv-corpus/bin/python scripts/build_amgen_xml.py
```

Result: **36 products, 37 documents, 1,439 physical pages, 4,634 source/candidate blocks; 37 inputs, no failed files/pages.** Structural schema validation and exact page-text roundtrip/source-hash verification passed. Both Repatha documents remain separate. The current XML SHA-256 is:

`94dfcc3aea57dfab6f2cf6df57d01d8655bcca0d0ac60784c0099e74b01df572`

The preceding 2,980-block first extracted artifact was preserved at `XML/snapshots/28b9ba7a5e3e44d0b183fca51da602578384d19f785ba4977bb628b634660c45.xml`; the initial supplied artifact was also preserved under its own hash on the first rebuild. New candidate subsections separate 12.1 mechanism-of-action content from pharmacokinetic tables, and separate highlights/patient appendices. All original page archive text is retained unaltered. New IDs express those boundaries, intentionally invalidating approvals for superseded coarse slices.

Both the illustrative template and generated output pass the compatible local structural XSD. The loader also requires actual document hashes/page archives, so it correctly rejects an illustrative template as an extracted corpus. The schema permits optional generic clinical/list/table/figure nodes from the template; it is not a complete clinical semantic schema. Its scope is explicit in the guide and report.

## Actual three-product preview

After root visually inspected the four passages against source PDFs and explicitly recorded source-fidelity approvals (not clinical signoff), this worker read the resulting database and prepared the default local preview without creating or changing reviews:

| Product | Document scope | Physical page | Approved raw passages | Chunks |
|---|---|---:|---:|---:|
| Aimovig | supplied PI | 7 | 1 | 1 |
| Repatha | contains-dry-natural-rubber filename hint | 10 | 1 | 1 |
| Repatha | not-made-with-natural-rubber-latex filename hint | 10 | 1 | 1 |
| Tezspire | supplied PI | 5 | 1 | 3 |

The complete corpus has **4 accepted raw passages and 4,630 needs-review blocks** at this snapshot, yielding 6 chunks and 4,630 exclusions. Preview took approximately 0.10 seconds locally. Byte upper bounds including prefixes/reserve are 231, 489, 491, 521, 397 and 346, all below 2,048. The final Tezspire chunk retains its complete sentence including the qualifier that the mechanism in asthma/CRSwNP has not been definitively established. Repatha filename hints are not asserted device applicability. No clinical fields became reviewed as a result of raw-passage acceptance.

`output/corpus/chunk-preview.json` retains full chunk text, settings, exact source spans and hashes. Preview fingerprint at inspection:

`d9be4686b847cf3ed65ae9c65b6e88034ef569ecf86f281e66304c193a3dd5f3`

Cloud indexing/searchability are reported by root/services; this report does not infer them from local chunk preparation.

## Tests and self-review

Commands run and read:

```sh
.venv-corpus/bin/python -m pytest tests/test_xml_pipeline.py tests/test_review_and_chunking.py -q
.venv-corpus/bin/python -m pytest -q
```

Corpus tests: 21 passed. Whole-suite snapshot before the additional UTF-16 safety regression: **114 passed, 21 subtests passed**, in 1.84 seconds. Final whole-suite result is recorded below. The only warnings were PyMuPDF SWIG deprecation warnings. Tests initially demonstrated absent implementation, then verified roundtrip text/XML special characters, unknown identities, empty pages, corrupt inputs preserving previous XML, duplicate-content retention, XSD/schema envelope rejection, external entity rejection, subsection/appendix scope, review invalidation, sentence coverage across pages, config ranges/determinism, unresolved table/reading-order exclusion, unreviewed warning exclusion, atomic table footnotes, prefix cap, oversized sentence/table exclusion, optional tokenizer hash invalidation and document isolation.

Self-review also found that the initial ASCII byte check could miss a UTF-16 DTD. A reproducing test failed; the loader now inspects document metadata using entity/network resolution disabled before ElementTree parses it. No XML regeneration or review fingerprint change was needed.

Self-review found and fixed a missing mandatory XSD check in `load_corpus()`: the reproducing empty-envelope test was observed failing, the loader was corrected, and the corpus/whole suites passed afterward. Source-span/hash validation and hard guard were inspected directly. Whole sentences can exceed the soft target but never the byte cap; no over-cap sentence or table is truncated. A changed review snapshot changes the plan fingerprint; the service must compare the current complete plan before publication, as contracted.

## Rulings and remaining limitations

1. There is no confirmed public exact tokenizer artifact for the hosted Pinecone model. Per root's explicit decision, the default uses the conservative UTF-8-byte upper bound plus eight special-token reserve, and labels all counts non-exact. Target/overlap settings use these conservative units. This yields smaller chunks than an exact tokenizer would. Optional local tokenizer counts prove only that artifact's counts, not hosted-provider parity; the independent byte guard always applies. Pinecone's model architecture/limit are documented by [Pinecone](https://www.pinecone.io/learn/nvidia-for-pinecone-inference/) and [its Documents API model guidance](https://www.pinecone.io/blog/docs-api-integrated-embedding/). No heavy tokenizer/model download or cloud request is needed.
2. No OCR engine is available. Empty/low-text pages are retained, counted and explicitly flagged; no OCR result or completeness claim is fabricated. Initial extraction can still miss scanned-image text, tables, figures or visual reading-order facts. Source inspection remains required even without a detected warning.
3. Candidate Table/Figure headings are conservative unresolved exclusions. Heuristics cannot identify every table or layout problem. Properly corrected `verifiedTable` blocks preserve headers, units and footnotes as an indivisible unit. Reviewed raw prose does not approve unresolved table/figure content.
4. The XML canonical replacement is atomic and validated before replacement; the adjacent JSON report is separately atomic and hash-bound. Consumers must compare its artifact hash. Failed/corrupt PDF inputs prevent publication of a partial canonical corpus and provide an attached report. Page-specific extraction exceptions are currently reported at file granularity because a complete original page archive is required before publication.
5. Overlap preserves whole sentences within its budget, so requested overlap can be smaller or zero. Oversized indivisible units have exact exclusion spans. Cross-page joins introduce one documented newline while keeping exact original page offsets; source archives remain lossless.
6. The supplied repo has no git metadata; no worktree, commits, or branch integration was possible. Root explicitly assigned shared-file ownership and no nested workers. Implementation and its self-review therefore used the assigned filesystem directly. This self-review is weaker than independent review, and root is responsible for final integration review.

No remaining known correctness blocker in the assigned corpus layer. Broad clinical review, OCR/layout reconciliation, hosted-tokenizer parity, and broad-corpus availability remain explicit limitations, not completed work.

Final verification after the UTF-16 regression fix: **21 corpus tests passed**; **121 whole-suite tests and 21 subtests passed** in 1.68 seconds, with only the five existing PyMuPDF SWIG deprecation warnings. XML bytes, parser version, accepted block scopes and preview fingerprint were unchanged by the loader safety fix.


## Final source-file validation correction

Root's scoped review found that the refactored CLI's `--validate-only` had retained XML-internal validation but omitted the original current-PDF comparison. The bounded correction adds reusable, read-only `xml_store.validate_source_files(corpus, source_dir)` and invokes it from the CLI. It requires exact current PDF filename inventory, checks each SHA-256 against the canonical document, opens the exact hashed in-memory bytes, checks physical page counts and every `sort=False` page string against its archived source, then rechecks hashes/inventory before success. Unexpected PDF extraction errors are reported without PDF content or parser details. New, missing or changed inputs fail safely; no rebuild or review mutation occurs.

New regression tests were observed failing before implementation and then passing: added, missing and changed temporary PDFs; restored source; source archive text mismatch. They assert existing canonical XML bytes remain unchanged. Corpus result after this correction: **23 passed**. The actual command `.venv-corpus/bin/python scripts/build_amgen_xml.py --validate-only` passed with **37 current PDF hashes and 1,439 exact page-text roundtrips verified**, unchanged XML SHA-256 `94dfcc3aea57dfab6f2cf6df57d01d8655bcca0d0ac60784c0099e74b01df572`. The parser version, accepted review scopes and all current XML bytes are unchanged.

Post-correction whole-suite verification: **145 passed and 21 subtests passed** in 2.46 seconds; only the five existing PyMuPDF SWIG deprecation warnings remained.
