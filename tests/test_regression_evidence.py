"""Provider and source-read failures must preserve the verified evidence boundary."""
from pathlib import Path

import pytest

from amgen_explorer.teaching import OpenAIClient, teach
from test_indexing import config
from test_service import built_service, local_service
from test_teaching import evidence


@pytest.mark.parametrize('output', [None, {}, 'not-a-list', [None], ['bad-item'],
    [{'type': 'message', 'content': None}],
    [{'type': 'message', 'content': 'not-a-list'}],
    [{'type': 'message', 'content': [None]}],
    [{'type': 'message', 'content': [{'type': 'output_text'}]}],
    [{'type': 'message', 'content': [{'type': 'output_text', 'text': 12}]}],
    [{'type': 'message', 'content': [{'type': 'refusal', 'refusal': 'No'}]}],
])
def test_malformed_provider_envelope_is_withheld_with_source_fallback(config, evidence, output):
    client = OpenAIClient(config, transport=lambda *a, **kw: {'status': 'completed', 'output': output})
    response = teach(evidence.question, evidence, config, client=client)
    assert response.abstained
    assert response.usage['source_fallback'] is True
    assert response.citations[0]['supporting_quote'] == evidence.passages[0]['text']


def test_download_returns_only_the_bytes_whose_hash_was_verified(local_service, monkeypatch):
    service, _, pdf = local_service
    original = pdf.read_bytes()
    original_read = Path.read_bytes
    reads = []
    def replace_after_read(path):
        payload = original_read(path)
        if path == pdf:
            reads.append(True)
            pdf.write_bytes(b'replaced-after-verification')
        return payload
    monkeypatch.setattr(Path, 'read_bytes', replace_after_read)
    assert service.source_pdf('doc-1') == original
    assert len(reads) == 1
    with pytest.raises(ValueError, match='changed'):
        service.source_pdf('doc-1')


def test_page_render_uses_the_verified_byte_snapshot(built_service, monkeypatch):
    service, block, pdf = built_service
    original_read = Path.read_bytes
    def replace_after_read(path):
        payload = original_read(path)
        if path == pdf:
            pdf.write_bytes(b'not-a-pdf-anymore')
        return payload
    monkeypatch.setattr(Path, 'read_bytes', replace_after_read)
    assert service.source_page(block.document_id, 1).startswith(b'\x89PNG')


def test_snapshot_copies_exact_verified_pdf_bytes(built_service, monkeypatch):
    service, block, pdf = built_service
    plan = service.preview(service.chunk_config())
    original = pdf.read_bytes()
    original_read = Path.read_bytes
    def replace_after_read(path):
        payload = original_read(path)
        if path == pdf:
            pdf.write_bytes(b'replaced-after-verification')
        return payload
    monkeypatch.setattr(Path, 'read_bytes', replace_after_read)
    service._snapshot(plan)
    folder = service.config.path('corpus_dir') / plan.xml_hash
    assert (folder / (block.document_sha256 + '.pdf')).read_bytes() == original


def test_changed_xml_cannot_be_snapshotted_under_previous_hash(built_service):
    service, _, _ = built_service
    plan = service.preview(service.chunk_config())
    corpus = service.corpus()
    service.corpus = lambda: corpus
    corpus.xml_path.write_bytes(corpus.xml_path.read_bytes() + b'\n')
    with pytest.raises(ValueError, match='XML.*changed'):
        service._snapshot(plan)
    assert not (service.config.path('corpus_dir') / plan.xml_hash / 'AmgenProducts.xml').exists()
