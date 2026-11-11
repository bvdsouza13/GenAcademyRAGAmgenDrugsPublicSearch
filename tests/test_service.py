"""Orchestration checks use local fixtures; they never call either provider."""
from dataclasses import replace
import hashlib
from pathlib import Path
from unittest.mock import Mock

import pytest

from amgen_explorer.config import AppConfig, load_config
from amgen_explorer.models import Corpus, Document, Product
from amgen_explorer.service import ExplorerService


@pytest.fixture
def local_service(tmp_path):
    original = load_config(secrets_path=tmp_path / "absent.toml")
    cfg = AppConfig(original.settings, tmp_path)
    directory = cfg.path("source_dir")
    directory.mkdir()
    pdf = directory / "test.pdf"
    pdf.write_bytes(b"PDF fixture")
    document = Document("doc-1", "product-1", "test.pdf", hashlib.sha256(pdf.read_bytes()).hexdigest(), 1)
    corpus = Corpus(tmp_path / "XML/test.xml", "xml1", [Product("product-1", "TEST")], [document], [])
    service = ExplorerService(cfg)
    service.corpus = Mock(return_value=corpus)
    return service, corpus, pdf


def test_original_source_download_verifies_hash(local_service):
    service, corpus, pdf = local_service
    assert service.source_pdf("doc-1") == b"PDF fixture"
    pdf.write_bytes(b"changed source")
    with pytest.raises(ValueError, match="changed"):
        service.source_pdf("doc-1")


def test_source_download_rejects_unknown_document(local_service):
    service, _, _ = local_service
    with pytest.raises(ValueError, match="not in"):
        service.source_pdf("../../secrets")


def test_source_download_rejects_symlink_outside_source_dir(local_service, tmp_path):
    service, corpus, pdf = local_service
    outside = tmp_path / "outside.pdf"
    outside.write_bytes(b"PDF fixture")
    pdf.unlink()
    pdf.symlink_to(outside)
    with pytest.raises(ValueError, match="unavailable"):
        service.source_pdf("doc-1")


def test_inventory_has_only_local_pdf_files(local_service):
    service, _, pdf = local_service
    (pdf.parent / "ignore.txt").write_text("not PDF")
    rows = service.inventory()
    assert [row["filename"] for row in rows] == ["test.pdf"]
    assert rows[0]["bytes"] == len(b"PDF fixture")


def test_inventory_includes_uppercase_pdf_extensions(local_service):
    service, _, pdf = local_service
    (pdf.parent / "UPPER.PDF").write_bytes(b"another PDF")
    (pdf.parent / "mixed.PdF").write_bytes(b"mixed PDF")
    assert {row["filename"] for row in service.inventory()} == {"test.pdf", "UPPER.PDF", "mixed.PdF"}


def test_preset_names_cannot_escape_data_directory(local_service):
    service, _, _ = local_service
    controls = Mock()
    controls.as_dict.return_value = {"target_tokens": 600, "overlap_tokens": 80}
    controls.fingerprint.return_value = "abc"
    with pytest.raises(ValueError):
        service.save_preset("../../elsewhere", controls)
    service.save_preset("Small passages", controls)
    assert service.presets()["Small passages"]["config_hash"] == "abc"


def test_corrupt_presets_reports_safe_error(local_service):
    service, _, _ = local_service
    folder = service.config.root / "data"
    folder.mkdir()
    (folder / "chunk-presets.json").write_text("invalid")
    with pytest.raises(ValueError, match="cannot be read"):
        service.presets()


def test_existing_end_truncation_profile_is_supported_with_local_guard(local_service):
    service, _, _ = local_service
    service.config.settings["pinecone"]["truncate"] = "END"
    assert service.config.validate() == []
    service.config.settings["pinecone"]["truncate"] = "START"
    assert any("truncate" in error for error in service.config.validate())


def test_pinned_pdf_stays_available_when_working_source_changes(local_service):
    service, corpus, pdf = local_service
    xml_hash = "a" * 64
    folder = service.config.path("corpus_dir") / xml_hash
    folder.mkdir(parents=True)
    original = pdf.read_bytes()
    snapshot = folder / (corpus.documents[0].sha256 + ".pdf")
    service._immutable_bytes(snapshot, original)
    service._pinned_corpus = Mock(return_value=corpus)
    pdf.write_bytes(b"new source version")
    assert service.source_pdf("doc-1", xml_hash=xml_hash) == original
    snapshot.write_bytes(b"corrupted snapshot")
    with pytest.raises(ValueError, match="changed"):
        service.source_pdf("doc-1", xml_hash=xml_hash)


def test_pinned_snapshot_cannot_be_silently_overwritten(local_service):
    service, corpus, pdf = local_service
    with pytest.raises(ValueError, match="integrity"):
        service._immutable_bytes(pdf, b"overwrite")
    assert pdf.read_bytes() == b"PDF fixture"


@pytest.fixture
def built_service(tmp_path):
    """Real XML/review/index orchestration; only the external provider is fake."""
    import pymupdf
    from amgen_explorer.indexing import IndexService
    from test_indexing import FakeDocuments

    cfg = AppConfig(load_config(secrets_path=tmp_path / "absent.toml").settings, tmp_path)
    cfg.path("source_dir").mkdir()
    pdf = cfg.path("source_dir") / "sample.PDF"
    with pymupdf.open() as document:
        page = document.new_page()
        page.insert_text((50, 50), "FULL PRESCRIBING INFORMATION\n12 CLINICAL PHARMACOLOGY\n12.1 Mechanism of Action\nA synthetic source statement.")
        document.save(pdf)
    fake = FakeDocuments()

    class LocalService(ExplorerService):
        @property
        def index(self):
            return IndexService(self.config, fake, sleep=lambda _: None, verification_attempts=1)

    service = LocalService(cfg)
    service.build()
    block = next(b for b in service.corpus().blocks if b.section_kind == "fullPrescribingInformation" and "synthetic" in b.text)
    # This is an artificial test passage, never an actual medical-source review.
    service.review(block.id, "accepted", "Synthetic fixture")
    return service, block, pdf


def test_service_rejects_review_revocation_between_preview_and_load(built_service):
    service, block, _ = built_service
    plan = service.preview(service.chunk_config())
    assert plan.chunks
    service.review(block.id, "needs-review", "Synthetic fixture")
    with pytest.raises(ValueError, match="changed"):
        service.load(plan)
    assert service.active() is None
    assert service.index.runs() == []


def test_service_rejects_changed_pdf_before_review_or_loading(built_service):
    service, block, pdf = built_service
    plan = service.preview(service.chunk_config())
    pdf.write_bytes(b"changed source PDF")
    with pytest.raises(ValueError, match="changed"):
        service.review(block.id, "accepted", "Synthetic fixture")
    with pytest.raises(ValueError, match="changed"):
        service.load(plan)
    assert service.index.runs() == []


def test_published_service_sources_survive_working_copy_change_and_detect_tampering(built_service):
    service, block, pdf = built_service
    plan = service.preview(service.chunk_config())
    original = pdf.read_bytes()
    run = service.load(plan)
    service.publish(run["run_id"], plan)
    pdf.write_bytes(b"working source replaced")
    assert service.source_pdf(block.document_id, run["xml_hash"]) == original
    assert service.source_page(block.document_id, 1, run["xml_hash"]).startswith(b"\x89PNG")
    snapshot = service.config.path("corpus_dir") / run["xml_hash"] / "AmgenProducts.xml"
    snapshot.write_bytes(snapshot.read_bytes().replace(b"synthetic", b"tampered!"))
    with pytest.raises(ValueError, match="snapshot"):
        service.source_pdf(block.document_id, run["xml_hash"])


def test_revoked_review_blocks_published_retrieval_and_reexplanation(built_service, monkeypatch):
    import amgen_explorer.retrieval as retrieval
    from amgen_explorer.models import TeachingResponse

    service, block, _ = built_service
    index = service.index
    monkeypatch.setattr(retrieval, "DocumentsClient", lambda config: index.client)
    plan = service.preview(service.chunk_config())
    run = service.load(plan)
    service.publish(run["run_id"], plan)
    question = "Explain its mechanism"
    evidence = service._evidence(question, block.product_id, block.document_id)
    assert evidence.passages and evidence.xml_hash == run["xml_hash"]
    previous = TeachingResponse("Synthetic answer", evidence=evidence)
    service.review(block.id, "needs-review", "Synthetic fixture")
    with pytest.raises(ValueError, match="needs review"):
        service._evidence(question, block.product_id, block.document_id)
    with pytest.raises(ValueError, match="needs review"):
        service.reexplain(question, previous, "Technical detail", block.product_id, block.document_id)


def test_fresh_repository_browse_without_credentials_creates_no_runtime_state(tmp_path, monkeypatch):
    for name in ("PINECONE_API_KEY", "OPENAI_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    cfg = AppConfig(load_config(secrets_path=tmp_path / "absent.toml").settings, tmp_path)
    service = ExplorerService(cfg)
    assert service.corpus() is None
    assert service.inventory() == []
    assert service.active() is None
    assert service.index.runs() == []
    response = service.answer("Explain a mechanism", "product-missing")
    assert response.abstained and "no published" in response.answer
    assert list(tmp_path.iterdir()) == []
