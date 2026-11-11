from pathlib import Path
import hashlib
import xml.etree.ElementTree as ET
import pytest
import pymupdf
from datetime import datetime, timezone
from amgen_explorer.extraction import build_corpus, CorpusBuildError
from amgen_explorer.xml_store import load_corpus, validate_schema


def pdf(path, text):
    doc = pymupdf.open()
    for page_text in text:
        page = doc.new_page()
        page.insert_text((50, 50), page_text)
    doc.save(path)


def test_build_roundtrip_schema_snapshot_unknown_identity(tmp_path):
    sources = tmp_path / 'Documents'; sources.mkdir()
    pdf(sources / 'repatha_prescribing_information.pdf', ['REPATHA (evolocumab)\nInitial U.S. Approval: 2015\nFULL PRESCRIBING INFORMATION\n1 INDICATIONS AND USAGE\nA & B < C.', 'continued.'])
    pdf(sources / 'repatha_alt.pdf', ['No reliable identity title', ''])
    output = tmp_path / 'XML' / 'AmgenProducts.xml'
    report = build_corpus(sources, output)
    corpus = load_corpus(output)
    assert report.schema_valid and report.document_count == 2 and report.product_count == 1
    assert report.page_count == 4
    assert len({d.id for d in corpus.documents}) == 2
    for doc in corpus.documents:
        assert doc.sha256 == hashlib.sha256((sources / doc.filename).read_bytes()).hexdigest()
    pages = [b for b in corpus.blocks if b.section_kind == 'sourcePageArchive']
    for block in pages:
        document = next(d for d in corpus.documents if d.id == block.document_id)
        with pymupdf.open(sources / document.filename) as source:
            assert block.text == source[block.page_start - 1].get_text('text', sort=False)
    before = output.read_bytes()
    build_corpus(sources, output)
    assert (output.parent / 'snapshots' / (hashlib.sha256(before).hexdigest() + '.xml')).read_bytes() == before
    assert validate_schema(output)
    assert validate_schema(Path('XML/prescribing-information-template.xml'))
    assert any('OCR' in w for w in corpus.warnings)
    tree = ET.parse(output)
    assert all(n.get('presence') == 'unknown' for n in tree.findall('.//{urn:local:pi-corpus:1}structuredLabel//*[@presence]'))


def test_corrupt_pdf_preserves_last_valid_artifact(tmp_path):
    sources = tmp_path / 'Documents'; sources.mkdir()
    pdf(sources / 'unknown.pdf', ['Unknown metadata'])
    output = tmp_path / 'corpus.xml'; build_corpus(sources, output)
    before = output.read_bytes()
    (sources / 'bad.pdf').write_bytes(b'bad')
    with pytest.raises(CorpusBuildError) as error:
        build_corpus(sources, output)
    assert error.value.report.failed_files
    assert output.read_bytes() == before


def test_unchanged_rebuild_preserves_source_identity_across_clock_changes(tmp_path, monkeypatch):
    import amgen_explorer.extraction as extraction

    class BuildClock:
        value = datetime(2026, 1, 1, tzinfo=timezone.utc)

        @classmethod
        def now(cls, tz):
            return cls.value

    monkeypatch.setattr(extraction, "datetime", BuildClock)
    sources = tmp_path / 'Documents'; sources.mkdir()
    pdf(sources / 'one.PDF', ['Exact unchanged source text.'])
    output = tmp_path / 'corpus.xml'
    first = build_corpus(sources, output)
    payload = output.read_bytes()
    BuildClock.value = datetime(2026, 2, 1, tzinfo=timezone.utc)
    second = build_corpus(sources, output)
    assert second.xml_hash == first.xml_hash
    assert output.read_bytes() == payload
    # A real source change must still invalidate the canonical identity.
    (sources / 'one.PDF').unlink()
    pdf(sources / 'one.PDF', ['Different source text.'])
    third = build_corpus(sources, output)
    assert third.xml_hash != first.xml_hash


def test_missing_source_directory_returns_build_report_without_replacing_xml(tmp_path):
    output = tmp_path / 'corpus.xml'
    output.write_bytes(b'previous corpus')
    with pytest.raises(CorpusBuildError) as error:
        build_corpus(tmp_path / 'missing', output)
    assert error.value.report.input_count == 0
    assert output.read_bytes() == b'previous corpus'


def test_duplicate_content_retained_and_tampering_rejected(tmp_path):
    sources = tmp_path / 'Documents'; sources.mkdir()
    pdf(sources / 'one.pdf', ['Hello < & >'])
    (sources / 'two.pdf').write_bytes((sources / 'one.pdf').read_bytes())
    output = tmp_path / 'corpus.xml'; report = build_corpus(sources, output)
    assert report.document_count == 2
    assert any('Duplicate source content' in w for w in report.warnings)
    output.write_text(output.read_text().replace('Hello', 'Jello'))
    with pytest.raises(ValueError, match='hash'):
        load_corpus(output)


def test_external_entity_rejected(tmp_path):
    path = tmp_path / 'unsafe.xml'
    path.write_text('<!DOCTYPE a [<!ENTITY x SYSTEM "file:///etc/passwd">]><a>&x;</a>')
    with pytest.raises(ValueError): load_corpus(path)


def test_subsection_scope_and_appendices_retained(tmp_path):
    sources=tmp_path/'Documents'; sources.mkdir()
    pdf(sources/'sample.pdf',['HIGHLIGHTS OF PRESCRIBING INFORMATION\nBrief highlight.\nFULL PRESCRIBING INFORMATION\n12 CLINICAL PHARMACOLOGY\n12.1 Mechanism of Action\nA mechanism statement.\n12.3 Pharmacokinetics\nTable 1: Unit mg\nA 1\nMEDICATION GUIDE\nPatient statement.\nINSTRUCTIONS FOR USE\nDevice statement.'])
    output=tmp_path/'corpus.xml'; build_corpus(sources,output); c=load_corpus(output)
    assert any(b.section_id.endswith('section-12-1') and 'mechanism statement' in b.text for b in c.blocks)
    assert {'highlights','medicationGuide','instructionsForUse'} <= {b.section_kind for b in c.blocks}
    table=next(b for b in c.blocks if b.section_id.endswith('section-12-3'))
    assert 'unresolved_table' in table.warnings


def test_missing_required_envelope_rejected(tmp_path):
    path=tmp_path/'invalid.xml'; path.write_text('<prescribingInformationCollection xmlns="urn:local:pi-corpus:1"/>')
    with pytest.raises(ValueError,match='XSD'):
        load_corpus(path)


def test_utf16_dtd_rejected_before_entity_expansion(tmp_path):
    path=tmp_path/'unsafe-utf16.xml'
    content='<?xml version="1.0" encoding="UTF-16"?><!DOCTYPE prescribingInformationCollection [<!ENTITY x "text">]><prescribingInformationCollection xmlns="urn:local:pi-corpus:1" schemaVersion="1"><sourceIndex/><products/><documents/>&x;</prescribingInformationCollection>'
    path.write_bytes(content.encode('utf-16'))
    with pytest.raises(ValueError,match='DTD'):
        load_corpus(path)


def test_readonly_validation_detects_changed_missing_and_new_sources(tmp_path):
    from amgen_explorer.xml_store import validate_source_files
    sources=tmp_path/'Documents'; sources.mkdir()
    pdf(sources/'one.pdf',['Exact source text.'])
    output=tmp_path/'corpus.xml'; build_corpus(sources,output)
    c=load_corpus(output); before=output.read_bytes(); original=(sources/'one.pdf').read_bytes()
    result=validate_source_files(c,sources)
    assert result['sourcePdfHashesVerified']==1 and result['pageTextRoundTripsVerified']==1
    pdf(sources/'two.pdf',['New unaccounted source.'])
    with pytest.raises(ValueError,match='inventory'): validate_source_files(c,sources)
    (sources/'two.pdf').unlink(); (sources/'one.pdf').unlink()
    with pytest.raises(ValueError,match='inventory'): validate_source_files(c,sources)
    pdf(sources/'one.pdf',['Changed source text.'])
    with pytest.raises(ValueError,match='hash'): validate_source_files(c,sources)
    (sources/'one.pdf').write_bytes(original)
    validate_source_files(c,sources)
    assert output.read_bytes()==before


def test_source_validation_detects_archive_text_mismatch(tmp_path):
    from dataclasses import replace
    from amgen_explorer.xml_store import validate_source_files
    sources=tmp_path/'Documents'; sources.mkdir(); pdf(sources/'one.pdf',['Exact source text.'])
    output=tmp_path/'corpus.xml'; build_corpus(sources,output); c=load_corpus(output)
    archive=next(b for b in c.blocks if b.section_kind=='sourcePageArchive')
    c.blocks[c.blocks.index(archive)]=replace(archive,text='Changed archive text.')
    with pytest.raises(ValueError,match='text'): validate_source_files(c,sources)
