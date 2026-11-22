# Condition-based treatment search

The user approved steps 1–3: interpret the condition and treatment intent, require supporting use evidence, and return only qualifying results. The observed query “What can treat migraine?” returned AIMOVIG followed by 19 passages matching only “treat,” including study captions. Bare condition matches can also be adverse-event mentions, so removing one stopword is insufficient.

Keep the existing local keyword plus Pinecone semantic retrieval. Recognized treatment/prevention/use-for questions activate a conservative evidence gate using the original passage, source section and product identity. Separate question intent from condition terms; favor indications over supporting clinical/patient-use evidence. Reject unrelated generic verbs, incidental conditions, adverse-event mentions, other medicines' uses and negative/unsupported use statements. Keep population and preventive/acute qualifiers in the unchanged cited source text. Explicit acute-use queries must not advertise prevention-only evidence.

Ordinary content search remains available, including bare condition searches, named medicines, storage and device variants. Missing treatment evidence means the loaded library did not establish a match; it does not establish that no treatment exists. Search returns fewer results when evidence is scarce, preserving document/device groups and citations. Unknown paraphrases may yield no results under the conservative rule; no clinical completeness claim is made.

The selected approach changes runtime query policy only. Re-chunking would not correct the demonstrated relevance rule. A learned reranker was discussed but is outside the approved steps. No provider, dependency, index, chunk-size or XML migration is needed; retained artifact bytes and source pins stay intact.

Verification covers both lexical engines, normal semantic retrieval and outages, unsupported conditions, multiword conditions, positive versus adverse/incidental/negated evidence, prevention versus acute use, explicit scopes, UI result groups, and existing search regressions. Independently inspected real source fixtures supplement synthetic fault cases. The existing learner holdout remains frozen.

## Confirmed full context and release scope

The user explicitly confirmed Search, chat and quiz context. Reuse a shared positive-use relation and atomic-source-group policy before cloud/local context packing and at the final teaching boundary. Re-explanation must revalidate saved evidence against the current question. Ineligible treatment evidence cannot become a source-only fallback or quiz. Ordinary mechanism, safety, dosing and storage evidence retains its own semantics; the standard quiz currently retrieves mechanism context. A generic-name relation uses the pinned product catalog, not a guessed alias.

The user subsequently requested the visible notice “This is Test App for Educational Purposes” beside the Amgen logo, detailed regression testing, refreshed current guides and all three regenerated architecture/data-flow/deployment diagrams, a consolidated fixes summary, and a feature-branch commit followed by integration into GitHub main and local launch. Historical dated reports remain as historical evidence; the new release report records fresh outcomes.
