"""Native geometry must never promote uncertain text into explainable evidence."""
from pathlib import Path
import json
import xml.etree.ElementTree as ET
import pymupdf
import pytest
from amgen_explorer.extraction import build_corpus
from amgen_explorer.xml_store import load_corpus, validate_source_files
from amgen_explorer.chunking import prepare_chunks, ChunkConfig
from amgen_explorer.eligibility import BULK_POLICY, validate_record_sources


def build_layout(tmp_path, *, kind='table', repeated=False):
    source = tmp_path/'Documents'; source.mkdir()
    pdf = pymupdf.open(); page = pdf.new_page()
    page.insert_text((50, 40), 'FULL PRESCRIBING INFORMATION\n12 CLINICAL PHARMACOLOGY\n12.1 Mechanism of Action')
    narrative = 'A precise native mechanism statement.'
    page.insert_text((50, 110), narrative)
    if repeated: page.insert_text((50, 145), narrative)
    if kind == 'table':
        page.insert_text((50, 190), 'Table 1: Observed values')
        for y in (210, 240, 270): page.draw_line((50,y),(350,y))
        for x in (50,200,350): page.draw_line((x,210),(x,270))
        for x,y,text in [(60,230,'Group'),(210,230,'Value'),(60,260,'A'),(210,260,'1')]: page.insert_text((x,y),text)
    elif kind == 'figure':
        pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0,0,20,20), 0)
        pix.clear_with(255); page.insert_image(pymupdf.Rect(50,210,350,310), pixmap=pix)
        page.insert_text((50,335),'Figure 1: Observed response')
    elif kind == 'ambiguous':
        page.insert_text((50,190),'Table 1: Continuing values\nGroup A\n1 2 3')
    elif kind == 'columns':
        page.insert_text((50,190),'Left column context.\nLeft continuation.')
        page.insert_text((330,190),'Right column context.\nRight continuation.')
    elif kind == 'reference':
        page.insert_text((50,190),'Table 1 summarizes the reported values.')
    pdf.save(source/'one.pdf'); pdf.close()
    output = tmp_path/'candidate.xml'; build_corpus(source,output)
    return load_corpus(output),source,narrative


@pytest.mark.parametrize('kind,reason',[('table','unresolved_table'),('figure','unresolved_figure')])
def test_demonstrably_separate_native_narrative_is_not_restricted_by_adjacent_layout(tmp_path,kind,reason):
    corpus,source,narrative = build_layout(tmp_path,kind=kind)
    plan=prepare_chunks(corpus,None,ChunkConfig(overlap_tokens=0),policy=BULK_POLICY,source_dir=source)
    narrative_chunks=[c for c in plan.chunks if narrative in c.metadata['source_text']]
    assert narrative_chunks and all(not c.metadata['extraction_limitations'] for c in narrative_chunks)
    assert any(reason in c.metadata['extraction_limitations'] for c in plan.chunks)
    assert plan.coverage['complete']
    records=[{**c.metadata,'_id':c.id,'chunk_text':c.text} for c in plan.chunks]
    assert validate_record_sources(records,corpus,vars(plan)) == plan.coverage


@pytest.mark.parametrize('kind,reason',[('ambiguous','unresolved_table'),('columns','unresolved_multicolumn')])
def test_ambiguous_native_layout_is_kept_restricted(tmp_path,kind,reason):
    corpus,source,narrative=build_layout(tmp_path,kind=kind)
    plan=prepare_chunks(corpus,None,ChunkConfig(),policy=BULK_POLICY,source_dir=source)
    assert all(reason in c.metadata['extraction_limitations'] for c in plan.chunks)


def test_table_reference_sentence_is_not_a_caption(tmp_path):
    corpus,source,_=build_layout(tmp_path,kind='reference')
    plan=prepare_chunks(corpus,None,ChunkConfig(),policy=BULK_POLICY,source_dir=source)
    reference=next(c for c in plan.chunks if 'Table 1 summarizes' in c.metadata['source_text'])
    assert not reference.metadata['extraction_limitations']
    assert all('unresolved_table' not in c.metadata['extraction_limitations'] for c in plan.chunks)


def test_repeated_native_strings_retain_distinct_exact_offsets(tmp_path):
    corpus,source,narrative=build_layout(tmp_path,repeated=True)
    plan=prepare_chunks(corpus,None,ChunkConfig(overlap_tokens=0),policy=BULK_POLICY,source_dir=source)
    archive=next(b for b in corpus.blocks if b.section_kind=='sourcePageArchive')
    intervals=[]
    for c in plan.chunks:
        if narrative in c.metadata['source_text']:
            assert not c.metadata['extraction_limitations']
        for span in json.loads(c.metadata['source_spans']):
            intervals.append((span['start'],span['end']))
    assert sorted(intervals)[0][0]==0
    counts=[0]*len(archive.text)
    for lo,hi in intervals:
        for i in range(lo,hi): counts[i]+=1
    assert counts==[1]*len(archive.text)
    assert validate_source_files(corpus,source)['pageTextRoundTripsVerified']==1


def test_page_coverage_distinguishes_native_text_from_unknown_blank_or_image_only(tmp_path):
    from amgen_explorer.coverage import coverage_summary
    corpus,source,_=build_layout(tmp_path,kind='reference')
    with pymupdf.open(source/'one.pdf') as pdf:
        pdf.new_page(); pdf.save(source/'replacement.pdf')
    (source/'one.pdf').unlink(); (source/'replacement.pdf').rename(source/'one.pdf')
    output=tmp_path/'candidate.xml'; build_corpus(source,output); corpus=load_corpus(output)
    summary=coverage_summary(corpus)
    assert summary['total_pages']==2 and summary['searchable_text_pages']==1 and summary['no_text_pages']==1
    assert summary['readable_characters']==sum(len(b.text) for b in corpus.blocks if b.section_kind=='sourcePageArchive' and b.text.strip())
    assert {'document_id':'doc-one','page':2,'reasons':['blank_or_image_only_ocr_unavailable']} in summary['limitations']
    assert 'unreadable_pages' not in summary


def test_parser_upgrade_creates_new_candidate_without_modifying_old_snapshot(tmp_path,monkeypatch):
    import amgen_explorer.extraction as extraction
    corpus,source,_=build_layout(tmp_path)
    before=corpus.xml_path.read_bytes()
    monkeypatch.setattr(extraction,'PARSER_VERSION','text-layer-layout-next')
    report=build_corpus(source,corpus.xml_path)
    assert report.xml_hash != corpus.xml_hash
    assert Path(report.snapshot_path).read_bytes()==before
    assert load_corpus(Path(report.snapshot_path)).xml_hash==corpus.xml_hash


def test_unassociated_caption_stays_restricted_even_if_another_table_is_detected(tmp_path):
    corpus,source,narrative=build_layout(tmp_path)
    with pymupdf.open(source/'one.pdf') as pdf:
        pdf[0].insert_text((50,550),'Table 2: Separate unresolved table\nA B C')
        pdf.save(source/'replacement.pdf')
    (source/'one.pdf').unlink(); (source/'replacement.pdf').rename(source/'one.pdf')
    build_corpus(source,corpus.xml_path); corpus=load_corpus(corpus.xml_path)
    plan=prepare_chunks(corpus,None,ChunkConfig(),policy=BULK_POLICY,source_dir=source)
    assert all('unresolved_table' in c.metadata['extraction_limitations'] for c in plan.chunks)


def test_unresolved_continuing_table_keeps_following_page_restricted(tmp_path):
    source=tmp_path/'Documents'; source.mkdir(); pdf=pymupdf.open()
    pdf.new_page().insert_text((50,50),'FULL PRESCRIBING INFORMATION\n12 CLINICAL PHARMACOLOGY\n12.1 Mechanism of Action\nTable 1: Values (continued)\nA B C')
    pdf.new_page().insert_text((50,50),'Group values\nD E F')
    pdf.save(source/'one.pdf'); pdf.close()
    output=tmp_path/'candidate.xml'; build_corpus(source,output); corpus=load_corpus(output)
    plan=prepare_chunks(corpus,None,ChunkConfig(),policy=BULK_POLICY,source_dir=source)
    assert all('unresolved_table' in c.metadata['extraction_limitations'] for c in plan.chunks)


def test_heading_only_mechanism_does_not_gain_generation_eligibility(tmp_path):
    source=tmp_path/'Documents'; source.mkdir(); pdf=pymupdf.open()
    pdf.new_page().insert_text((50,50),'FULL PRESCRIBING INFORMATION\n12 CLINICAL PHARMACOLOGY\n12.1 Mechanism of Action\n12.3 Pharmacokinetics\nNative pharmacokinetics statement.')
    pdf.save(source/'one.pdf'); pdf.close()
    output=tmp_path/'candidate.xml'; build_corpus(source,output); corpus=load_corpus(output)
    block=next(b for b in corpus.blocks if b.section_id.endswith('section-12-1'))
    assert 'unresolved_heading_only' in block.warnings


def test_coverage_includes_existing_snapshot_section_limitations_without_rewriting(tmp_path):
    from amgen_explorer.coverage import coverage_summary
    corpus,_,_=build_layout(tmp_path)
    for block in corpus.blocks:
        if block.section_kind=='sourcePageArchive': block.warnings=[]
    summary=coverage_summary(corpus)
    assert any('unresolved_table' in item['reasons'] for item in summary['limitations'])


def test_adjacent_clean_native_blocks_share_a_chunk_without_crossing_risk_boundary(tmp_path):
    corpus,source,narrative=build_layout(tmp_path,repeated=True)
    plan=prepare_chunks(corpus,None,ChunkConfig(),policy=BULK_POLICY,source_dir=source)
    clean_mechanism=[c for c in plan.chunks if narrative in c.metadata['source_text']]
    assert len(clean_mechanism)==1
    assert clean_mechanism[0].metadata['source_text'].count(narrative)==2
    assert not clean_mechanism[0].metadata['extraction_limitations']


def test_unbounded_table_continuation_ends_only_at_new_numbered_section(tmp_path):
    source=tmp_path/'Documents'; source.mkdir(); pdf=pymupdf.open()
    pdf.new_page().insert_text((50,50),'FULL PRESCRIBING INFORMATION\n12 CLINICAL PHARMACOLOGY\n12.1 Mechanism of Action\nTable 1: Values\nA B C')
    pdf.new_page().insert_text((50,50),'D E F\n12.3 Pharmacokinetics\nA native pharmacokinetics statement.')
    pdf.save(source/'one.pdf'); pdf.close()
    output=tmp_path/'candidate.xml'; build_corpus(source,output); corpus=load_corpus(output)
    plan=prepare_chunks(corpus,None,ChunkConfig(),policy=BULK_POLICY,source_dir=source)
    continued=next(c for c in plan.chunks if 'D E F' in c.metadata['source_text'])
    assert 'unresolved_table' in continued.metadata['extraction_limitations']
    clean=next(c for c in plan.chunks if 'native pharmacokinetics' in c.metadata['source_text'])
    assert not clean.metadata['extraction_limitations']


def test_caption_like_prose_next_to_detected_table_remains_restricted(tmp_path):
    corpus,source,_=build_layout(tmp_path)
    with pymupdf.open(source/'one.pdf') as pdf:
        page=pdf[0]
        page.add_redact_annot(pymupdf.Rect(45,175,360,200)); page.apply_redactions()
        page.insert_text((50,190),'Table 1 summarizes the reported values.')
        pdf.save(source/'replacement.pdf')
    (source/'one.pdf').unlink(); (source/'replacement.pdf').rename(source/'one.pdf')
    build_corpus(source,corpus.xml_path); corpus=load_corpus(corpus.xml_path)
    plan=prepare_chunks(corpus,None,ChunkConfig(),policy=BULK_POLICY,source_dir=source)
    caption=next(c for c in plan.chunks if 'Table 1 summarizes' in c.metadata['source_text'])
    assert 'unresolved_table' in caption.metadata['extraction_limitations']


def test_continuation_ends_at_numbered_heading_printed_on_two_lines(tmp_path):
    source=tmp_path/'Documents'; source.mkdir(); pdf=pymupdf.open()
    pdf.new_page().insert_text((50,50),'FULL PRESCRIBING INFORMATION\n12 CLINICAL PHARMACOLOGY\nTable 1: Values\nA B C')
    pdf.new_page().insert_text((50,50),'D E F\n12.1\nMechanism of Action\nA native mechanism statement.')
    pdf.save(source/'one.pdf'); pdf.close()
    output=tmp_path/'candidate.xml'; build_corpus(source,output); corpus=load_corpus(output)
    plan=prepare_chunks(corpus,None,ChunkConfig(),policy=BULK_POLICY,source_dir=source)
    clean=next(c for c in plan.chunks if 'native mechanism' in c.metadata['source_text'])
    assert not clean.metadata['extraction_limitations']
