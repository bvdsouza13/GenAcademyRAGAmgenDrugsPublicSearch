# Evaluation and pilot evidence

`questions.jsonl` contains 50 cases: one source-linked mechanism question for each of 37 supplied PDFs, plus 13 scope, safety, missing-evidence, qualifier and injection cases. `tests/test_evaluations.py` checks source coverage, hashes, quotations and required case categories. Backend tests exercise abstention, citation resolution, isolation and unsafe source instructions using fake providers.

These are source-linked regression fixtures, **not 50 clinician-reviewed semantic answer evaluations**. Broad release still needs domain review and live expected-evidence scoring across the collection. Do not equate fixture coverage with retrieval recall or medical accuracy.

`pilot-live.json` records real cloud activity, provider usage and observed responses. Four section 12.1 passages from Aimovig, Tezspire and both Repatha PDFs were compared with rendered PDF pages by Codex for source fidelity. This supports a small educational demonstration, not clinical sign-off or an assertion that the supplied labels are current. All other passages remain unreviewed until a curator accepts them explicitly.

Repeat live checks with `python scripts/check_connections.py` and `python scripts/live_smoke.py`; the latter sends a small set of educational questions to Pinecone/OpenAI and may incur API usage. Offline tests require neither keys nor paid calls.
