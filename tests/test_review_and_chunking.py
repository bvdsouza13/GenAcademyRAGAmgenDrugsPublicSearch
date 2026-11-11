from dataclasses import replace
from pathlib import Path
import hashlib
import json
import pytest
from amgen_explorer.models import Corpus, Product, Document, SourceBlock
from amgen_explorer.review import ReviewStore
from amgen_explorer.chunking import ChunkConfig, prepare_chunks


def block(text='A supported statement. ', *, id='b1', page=1, section='s1', warnings=None, kind='fullPrescribingInformation'):
    return SourceBlock(id,'product-one','doc-one','a'*64,text,section,'WARNINGS',kind,page,page,hashlib.sha256(text.encode()).hexdigest(),[{'page':page,'block_id':f'archive{page}','start':0,'end':len(text)}],warnings=warnings or [])


def corpus(blocks):
    return Corpus(Path('test.xml'),'b'*64,[Product('product-one','ONE')],[Document('doc-one','product-one','one.pdf','a'*64,10)],blocks)


def test_review_hash_scope_persistence_and_audit(tmp_path):
    b=block(); c=corpus([b]); store=ReviewStore(tmp_path/'review.sqlite')
    assert store.status(b)=='needs-review' and not store.path.exists()
    initial=store.fingerprint(c)
    store.record(b,'accepted','Curator','Checked PDF text/order')
    assert ReviewStore(store.path).status(b)=='accepted'
    assert store.fingerprint(c)!=initial
    assert store.status(replace(b,document_sha256='c'*64))=='needs-review'
    assert store.status(replace(b,parser_version='new'))=='needs-review'
    assert store.status(replace(b,spans=[{'page':2,'start':0,'end':len(b.text)}]))=='needs-review'
    assert store.summary(c)['accepted']==1
    with pytest.raises(ValueError): store.record(b,'accepted','')
    with pytest.raises(ValueError): store.record(replace(b,text='changed'),'accepted','C')


@pytest.mark.parametrize('settings',[{'target_tokens':299},{'target_tokens':1201},{'overlap_tokens':201},{'overlap_tokens':600},{'overlap_tokens':-1}])
def test_invalid_config(settings):
    with pytest.raises(ValueError): ChunkConfig(**settings)


def test_source_coverage_cross_page_and_determinism(tmp_path):
    a=block('First sentence with qualifier if appropriate. '*12)
    b=block('Second page continuation with a condition. '*10,id='b2',page=2)
    c=corpus([a,b]); reviews=ReviewStore(tmp_path/'r.sqlite')
    for item in c.blocks: reviews.record(item,'accepted','curator')
    config=ChunkConfig(target_tokens=300,overlap_tokens=0)
    plan=prepare_chunks(c,reviews,config)
    assert len(plan.chunks)>1 and not plan.excluded
    spans=[]
    for chunk in plan.chunks:
        assert len(chunk.text.encode())+8 <=2048
        assert chunk.metadata['review_state']=='accepted'
        assert chunk.metadata['chunk_config_hash']==config.fingerprint()
        assert chunk.metadata['xml_hash']==c.xml_hash
        spans.extend(json.loads(chunk.metadata['source_spans']))
    for original in c.blocks:
        covered=set()
        for span in spans:
            if span['source_block_id']==original.id: covered.update(range(span['block_start'],span['block_end']))
        assert covered==set(range(len(original.text)))
    again=prepare_chunks(c,reviews,config)
    assert plan==again
    assert config.fingerprint()!=ChunkConfig(target_tokens=301,overlap_tokens=0).fingerprint()
    assert plan.fingerprint!=prepare_chunks(c,reviews,ChunkConfig(target_tokens=301,overlap_tokens=0)).fingerprint


def test_unreviewed_and_unresolved_are_excluded_and_not_joined(tmp_path):
    blocks=[block(),block('Table 1: units mg. * footnote',id='table',warnings=['unresolved_table']),block('Boxed warning',id='warning',section='warning'),block('After table.',id='last',page=2)]
    c=corpus(blocks); reviews=ReviewStore(tmp_path/'r.sqlite')
    for item in (blocks[0],blocks[1],blocks[3]): reviews.record(item,'accepted','curator')
    plan=prepare_chunks(c,reviews,ChunkConfig())
    assert {e['block_id'] for e in plan.excluded}=={'table','warning'}
    assert len(plan.chunks)==2
    assert all('Table 1' not in ch.text for ch in plan.chunks)
    artifact=block('Two columns.',id='two',warnings=['unresolved_reading_order'])
    reviews.record(artifact,'accepted','curator')
    assert not prepare_chunks(corpus([artifact]),reviews,ChunkConfig()).chunks


def test_oversized_sentence_qualifier_and_table_never_truncated(tmp_path):
    long=block('a '*1400+'only if this condition applies.',id='long')
    table=block('units mg; headers and footnotes '+'x '*1300,id='table',kind='table')
    reviews=ReviewStore(tmp_path/'r.sqlite')
    for b in (long,table): reviews.record(b,'accepted','curator')
    plan=prepare_chunks(corpus([long,table]),reviews,ChunkConfig())
    assert not plan.chunks
    assert all(e['reason']=='indivisible_unit_exceeds_model_cap' for e in plan.excluded)


def test_overlap_and_document_isolation(tmp_path):
    a=block('A complete sentence with condition. '*40)
    b=replace(block('Other document sentence.',id='other'),document_id='doc-two',document_sha256='d'*64)
    c=corpus([a,b]); c.documents.append(Document('doc-two','product-one','other.pdf','d'*64,1))
    reviews=ReviewStore(tmp_path/'r.sqlite')
    for item in c.blocks: reviews.record(item,'accepted','C')
    p=prepare_chunks(c,reviews,ChunkConfig(target_tokens=300,overlap_tokens=80))
    assert all(len(set(ch.metadata['block_ids']))==1 for ch in p.chunks)
    assert len(p.chunks)>2
    spans=[json.loads(ch.metadata['source_spans']) for ch in p.chunks if ch.metadata['document_id']=='doc-one']
    assert any(left[-1]['block_end'] > right[0]['block_start'] for left,right in zip(spans,spans[1:]))


def test_review_snapshot_is_consistent_and_invalidates_after_update(tmp_path):
    b=block(); c=corpus([b]); r=ReviewStore(tmp_path/'reviews.sqlite')
    statuses, before=r.snapshot(c)
    assert statuses[b.id]=='needs-review'
    r.record(b,'accepted','C')
    statuses,after=r.snapshot(c)
    assert statuses[b.id]=='accepted' and before!=after
    assert r.fingerprint(c)==after


def test_verified_table_keeps_header_units_and_footnote_together(tmp_path):
    b=block('Table 1\nDose (mg) | Events (%)\n10 | 2\n* Includes all events.',kind='verifiedTable')
    r=ReviewStore(tmp_path/'r.sqlite');r.record(b,'accepted','C')
    plan=prepare_chunks(corpus([b]),r,ChunkConfig())
    assert len(plan.chunks)==1 and plan.chunks[0].metadata['source_text']==b.text
    assert '* Includes' in plan.chunks[0].text


def test_prefix_counted_and_oversize_context_is_reported(tmp_path):
    b=block('Preserve this complete statement and condition.')
    c=corpus([b]); c.products[0].name='x'*2050
    r=ReviewStore(tmp_path/'r.sqlite');r.record(b,'accepted','C')
    p=prepare_chunks(c,r,ChunkConfig())
    assert not p.chunks and p.excluded[0]['reason']=='indivisible_unit_exceeds_model_cap'


def test_local_tokenizer_hash_pin_and_byte_cap(tmp_path):
    from tokenizers import Tokenizer, models
    from amgen_explorer.chunking import token_count
    tokenizer=Tokenizer(models.WordLevel({'[UNK]':0,'a':1},unk_token='[UNK]'))
    path=tmp_path/'tokenizer.json'; tokenizer.save(str(path))
    config=ChunkConfig(tokenizer='local-tokenizer-json',tokenizer_path=str(path),tokenizer_sha256=hashlib.sha256(path.read_bytes()).hexdigest())
    assert token_count('a',config)==1
    b=block('x'*2100+'.')
    r=ReviewStore(tmp_path/'r.sqlite');r.record(b,'accepted','C')
    assert not prepare_chunks(corpus([b]),r,config).chunks
    path.write_text('{}')
    with pytest.raises(ValueError,match='hash'): token_count('a',config)
