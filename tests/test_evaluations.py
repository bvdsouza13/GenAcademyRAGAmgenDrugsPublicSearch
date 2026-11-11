"""Validate evaluation provenance separately from unclaimed semantic accuracy."""
import json
from pathlib import Path
from amgen_explorer.xml_store import load_corpus

ROOT = Path(__file__).resolve().parents[1]


def test_evaluation_cases_cover_every_pdf_with_resolving_source_quotes():
    corpus = load_corpus(ROOT / "XML/AmgenProducts.xml")
    rows = [json.loads(line) for line in (ROOT / "evals/questions.jsonl").read_text().splitlines()]
    assert len(rows) >= 50
    assert len({r["id"] for r in rows}) == len(rows)
    blocks = {b.id: b for b in corpus.blocks}
    source_cases = [r for r in rows if r["kind"] == "source_lookup"]
    assert {r["document_id"] for r in source_cases} == {d.id for d in corpus.documents}
    for row in source_cases:
        assert row["xml_hash"] == corpus.xml_hash, "Rebuild fixtures explicitly when the canonical source version changes"
        for bid in row["expected_block_ids"]:
            block = blocks[bid]
            assert block.document_id == row["document_id"]
            assert block.product_id == row["product_id"]
            assert block.document_sha256 == row["pdf_sha256"]
            assert row["expected_quote"] in block.text
        assert "pending" in row["review_status"]  # Fixture validity is not a claim of clinical review.


def test_evaluation_includes_scope_qualifier_and_adversarial_cases():
    rows = [json.loads(line) for line in (ROOT / "evals/questions.jsonl").read_text().splitlines()]
    kinds = {r["kind"] for r in rows}
    assert {"ambiguity", "comparison", "personal_dose", "revision", "unrelated", "source_injection", "table", "qualifier", "missing_safety"} <= kinds
