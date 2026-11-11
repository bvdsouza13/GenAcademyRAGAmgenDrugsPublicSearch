"""Expected page coordinates are hand-derived independently of chunk output."""
import json
from amgen_explorer.chunking import ChunkConfig, prepare_chunks
from test_bulk_eligibility import source_corpus, BULK


def test_missing_section_intervals_are_filled_from_archive_without_duplicate_coverage(tmp_path):
    corpus, source_dir = source_corpus(tmp_path, 'Alpha beta gamma delta.', sections=[(0,5), (3,10)])
    plan = prepare_chunks(corpus, None, ChunkConfig(overlap_tokens=0), policy=BULK, source_dir=source_dir)
    counts = [0] * len(corpus.blocks[0].text)
    for chunk in plan.chunks:
        for span in json.loads(chunk.metadata['source_spans']):
            assert chunk.metadata['document_sha256'] == corpus.documents[0].sha256
            for i in range(span['start'], span['end']): counts[i] += 1
    assert counts == [1] * len(counts)
    assert plan.coverage['expected_characters'] == len(counts)
    assert plan.coverage['covered_characters'] == len(counts)
    assert plan.coverage['missing_intervals'] == []


def test_oversized_unicode_units_split_at_character_boundaries_without_losing_context(tmp_path):
    corpus, source_dir = source_corpus(tmp_path, ('é'*80+'\n')*80)
    plan = prepare_chunks(corpus, None, ChunkConfig(target_tokens=300,overlap_tokens=0), policy=BULK, source_dir=source_dir)
    assert len(plan.chunks) > 2 and not plan.excluded
    text = ''.join(c.metadata['source_text'] for c in plan.chunks)
    assert text == corpus.blocks[0].text
    assert all(len(c.text.encode('utf-8'))+8 <= 2048 for c in plan.chunks)
    assert all(c.metadata['continuation_parent_ids'] == ['section-0'] for c in plan.chunks)
    assert [c.metadata['continuation_index'] for c in plan.chunks] == list(range(len(plan.chunks)))
    assert all(c.metadata['continuation_count'] == len(plan.chunks) for c in plan.chunks)
    assert plan.coverage['complete']


def test_complete_supplied_collection_preserves_every_archived_character_and_exact_parent_offsets():
    from pathlib import Path
    from amgen_explorer.xml_store import load_corpus
    corpus = load_corpus(Path(__file__).resolve().parents[1] / 'XML' / 'AmgenProducts.xml')
    plan = prepare_chunks(corpus, None, ChunkConfig(), policy=BULK,
                          source_dir=corpus.xml_path.parents[1] / 'Documents')
    assert len(plan.expected_document_ids) == 37
    assert len(plan.expected_product_ids) == 36
    blocks = {b.id:b for b in corpus.blocks}
    archives = {b.id:b for b in corpus.blocks if b.section_kind == 'sourcePageArchive'}
    covered = {bid:bytearray(len(block.text)) for bid,block in archives.items()}
    assert sum(map(len,covered.values())) == 3398430
    for chunk in plan.chunks:
        snippets=[]
        assert len(chunk.text.encode('utf-8'))+8 <= 2048
        for span in json.loads(chunk.metadata['source_spans']):
            archive = archives[span['archive_block_id']]
            parent = blocks[span['source_block_id']]
            snippet = archive.text[span['start']:span['end']]
            assert snippet == parent.text[span['block_start']:span['block_end']]
            assert archive.document_id == parent.document_id == chunk.metadata['document_id']
            assert archive.page_start == span['page']
            snippets.append(snippet)
            covered[archive.id][span['start']:span['end']] = b'\1'*(span['end']-span['start'])
        assert ''.join(snippets) == chunk.metadata['source_text']
    assert all(all(page) for page in covered.values())
    assert not plan.excluded
    from amgen_explorer.eligibility import validate_record_sources
    records=[{**c.metadata,'_id':c.id,'chunk_text':c.text} for c in plan.chunks]
    assert validate_record_sources(records,corpus,vars(plan)) == plan.coverage


def test_blank_image_only_page_is_reported_separately_from_readable_coverage(tmp_path):
    import hashlib
    from dataclasses import replace
    import pymupdf
    corpus,source_dir = source_corpus(tmp_path)
    path=source_dir/'one.pdf'
    with pymupdf.open(path) as pdf:
        pdf.new_page()
        data=pdf.tobytes()
    path.write_bytes(data)
    sha=hashlib.sha256(data).hexdigest()
    corpus.documents[0]=replace(corpus.documents[0],sha256=sha,page_count=2)
    corpus.blocks=[replace(b,document_sha256=sha) for b in corpus.blocks]
    corpus.blocks.append(replace(corpus.blocks[0],id='blank',text='',content_hash=hashlib.sha256(b'').hexdigest(),
        page_start=2,page_end=2,spans=[{'page':2,'block_id':'blank','start':0,'end':0}]))
    plan=prepare_chunks(corpus,None,ChunkConfig(),policy=BULK,source_dir=source_dir)
    assert plan.coverage['complete'] and plan.coverage['expected_pages']==1
    assert plan.coverage['blank_pages']==[{'document_id':'doc-one','page':2,'reason':'blank_or_image_only_ocr_unavailable'}]
