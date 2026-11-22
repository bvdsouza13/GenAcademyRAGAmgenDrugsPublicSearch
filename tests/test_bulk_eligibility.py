"""Real source fixtures catch bulk verification bypasses and legacy-policy drift."""
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import pytest
import pymupdf
from amgen_explorer.models import Corpus, Product, Document, SourceBlock, EvidenceBundle
from amgen_explorer.review import ReviewStore
from amgen_explorer.chunking import ChunkConfig, prepare_chunks
from amgen_explorer.teaching import teach

BULK = 'bulk_source_verified_v1'


def source_corpus(tmp_path, text='First source sentence. Second source sentence.', *, sections=None, warnings=None):
    source_dir = tmp_path / 'sources'
    source_dir.mkdir(exist_ok=True)
    pdf = pymupdf.open()
    page = pdf.new_page(width=1000, height=3000)
    page.insert_text((25, 25), text, fontsize=9)
    path = source_dir / 'one.pdf'
    pdf.save(path)
    pdf.close()
    with pymupdf.open(path) as saved:
        archived = saved[0].get_text('text', sort=False)
    sha = hashlib.sha256(path.read_bytes()).hexdigest()
    def block(bid, lo, hi, kind):
        value = archived[lo:hi]
        return SourceBlock(bid, 'one', 'doc-one', sha, value, 'section-'+bid, 'Source text', kind,
                           1, 1, hashlib.sha256(value.encode()).hexdigest(),
                           [{'page':1, 'block_id':'archive', 'start':lo, 'end':hi}], warnings=warnings or [])
    blocks = [block('archive', 0, len(archived), 'sourcePageArchive')]
    for i, (lo, hi) in enumerate(sections if sections is not None else [(0, len(archived))]):
        blocks.append(block('section-'+str(i), lo, hi, 'fullPrescribingInformation'))
    corpus = Corpus(tmp_path/'one.xml', 'f'*64, [Product('one','ONE')],
                    [Document('doc-one','one','one.pdf',sha,1)], blocks)
    return corpus, source_dir


def test_bulk_without_review_records_preserves_provenance_without_faking_human_approval(tmp_path):
    corpus, source_dir = source_corpus(tmp_path)
    reviews = ReviewStore(tmp_path/'empty.sqlite')
    plan = prepare_chunks(corpus, reviews, ChunkConfig(), policy=BULK, source_dir=source_dir)
    assert plan.chunks and not reviews.path.exists()
    assert plan.eligibility_policy == BULK
    assert all(c.metadata['source_verified'] is True and c.metadata['human_review_status']=='not_assessed'
               and c.metadata.get('review_state') != 'accepted' for c in plan.chunks)
    assert plan.coverage['complete'] is True
    assert plan.expected_document_ids == ['doc-one'] and plan.expected_product_ids == ['one']


def test_legacy_policy_still_requires_reviews_and_honors_revocation(tmp_path):
    corpus, _ = source_corpus(tmp_path)
    reviews = ReviewStore(tmp_path/'reviews.sqlite')
    assert not prepare_chunks(corpus, reviews, ChunkConfig()).chunks
    reviews.record(corpus.blocks[1], 'accepted', 'Curator')
    assert prepare_chunks(corpus, reviews, ChunkConfig()).chunks
    reviews.record(corpus.blocks[1], 'rejected', 'Curator')
    assert not prepare_chunks(corpus, reviews, ChunkConfig()).chunks


@pytest.mark.parametrize('mutation', ['pdf', 'content', 'span', 'owner'])
def test_bulk_rejects_changed_source_or_false_spans(tmp_path, mutation):
    corpus, source_dir = source_corpus(tmp_path)
    if mutation == 'pdf': (source_dir/'one.pdf').write_bytes(b'changed')
    if mutation == 'content': corpus.blocks[1].content_hash = '0'*64
    if mutation == 'span': corpus.blocks[1].spans[0]['start'] = 1
    if mutation == 'owner': corpus.blocks[1].product_id = 'other'
    with pytest.raises(ValueError):
        prepare_chunks(corpus, None, ChunkConfig(), policy=BULK, source_dir=source_dir)


def test_layout_warnings_remain_searchable_and_teaching_uses_exact_excerpt_without_provider(tmp_path):
    corpus, source_dir = source_corpus(tmp_path, warnings=['unresolved_table'])
    plan = prepare_chunks(corpus, None, ChunkConfig(), policy=BULK, source_dir=source_dir)
    assert plan.chunks and not plan.excluded
    chunk = plan.chunks[0]
    assert 'unresolved_table' in chunk.metadata['extraction_limitations']
    evidence = EvidenceBundle('Explain this source', 'one', 'bulk', corpus.xml_hash,
        [{'id':chunk.id, 'text':chunk.metadata['source_text'], 'metadata':chunk.metadata, 'namespace':'bulk'}],
        eligibility_policy=BULK, eligibility_fingerprint=plan.eligibility_fingerprint)
    class NoProvider:
        def generate(self, *args, **kwargs): raise AssertionError('Unsafe layout must not be paraphrased')
    response = teach('Explain this source', evidence, None, client=NoProvider())
    assert response.abstained and response.usage['source_fallback']
    assert response.citations[0]['supporting_quote'] == chunk.metadata['source_text']
    assert 'layout' in response.answer.lower()

# These fixtures retain the existing fake Documents API boundary, while real
# plans/records/manifests exercise the policy and publication logic.
from test_indexing import config, FakeDocuments
from amgen_explorer.indexing import IndexService, atomic_json, manifest_records
from amgen_explorer.retrieval import retrieve


def test_bulk_ingestion_requires_complete_policy_and_search_artifact_before_activation(tmp_path, config):
    corpus, source_dir = source_corpus(tmp_path)
    plan = prepare_chunks(corpus, None, ChunkConfig(), policy=BULK, source_dir=source_dir)
    fake = FakeDocuments()
    index = IndexService(config, fake, sleep=lambda _:None, verification_attempts=1)
    run = index.ingest(plan)
    assert run['eligibility_policy'] == BULK and run['coverage']['complete']
    assert manifest_records(run, config)
    with pytest.raises(ValueError, match='artifact'):
        index.activate(run['run_id'], plan)
    assert index.active() is None


def test_bulk_partial_inventory_cannot_upload_and_manifest_cannot_relabel_policy(tmp_path, config):
    corpus, source_dir = source_corpus(tmp_path)
    plan = prepare_chunks(corpus, None, ChunkConfig(), policy=BULK, source_dir=source_dir)
    fake = FakeDocuments()
    index = IndexService(config, fake, sleep=lambda _:None, verification_attempts=1)
    plan.expected_document_ids.append('missing-document')
    with pytest.raises(ValueError, match='inventory'):
        index.ingest(plan)
    assert fake.writes == []
    plan.expected_document_ids.remove('missing-document')
    run = index.ingest(plan)
    run.pop('eligibility_policy')
    with pytest.raises(ValueError, match='reviewed'):
        manifest_records(run, config)


def test_bulk_retrieval_pins_policy_and_continuation_context_does_not_silently_disappear(tmp_path, config):
    corpus, source_dir = source_corpus(tmp_path, ('é'*80+'\n')*80)
    plan = prepare_chunks(corpus, None, ChunkConfig(target_tokens=300, overlap_tokens=0), policy=BULK, source_dir=source_dir)
    fake = FakeDocuments()
    index = IndexService(config, fake, sleep=lambda _:None, verification_attempts=1)
    run = index.ingest(plan)
    # Bound evidence so the full parent cannot fit; this must constrain teaching.
    config.settings['retrieval']['evidence_token_budget'] = 700
    bundle = retrieve('Explain source text', 'one', run, config, 'doc-one', client=fake)
    assert not bundle.passages and bundle.eligibility_policy == BULK
    assert bundle.eligibility_fingerprint == plan.eligibility_fingerprint
    assert bundle.run_id == run['run_id']
    assert any('continuation context' in warning.lower() for warning in bundle.warnings)
    class NoProvider:
        def generate(self,*args,**kwargs): raise AssertionError('Incomplete parent must not be explained')
    response = teach('Explain source text', bundle, config, client=NoProvider())
    assert response.abstained and not response.citations
    assert 'continuation context' in response.answer
    # With adequate budget all exact intervals, including repeated text at
    # different offsets, must survive deduplication.
    config.settings['retrieval']['evidence_token_budget'] = 25000
    full = retrieve('Explain source text', 'one', run, config, 'doc-one', client=fake)
    assert len(full.passages) == len(plan.chunks)
    assert not any('continuation context' in warning.lower() for warning in full.warnings)


def test_bulk_activation_verifies_matching_lexical_artifact_and_preserves_active_on_tampering(tmp_path, config):
    from dataclasses import asdict
    from amgen_explorer.search import build_search_artifact
    from amgen_explorer.extraction import build_corpus
    from amgen_explorer.xml_store import load_corpus
    corpus, source_dir = source_corpus(tmp_path)
    build_corpus(source_dir, corpus.xml_path)
    corpus = load_corpus(corpus.xml_path)
    plan = prepare_chunks(corpus, None, ChunkConfig(), policy=BULK, source_dir=source_dir)
    fake = FakeDocuments()
    index = IndexService(config, fake, sleep=lambda _:None, verification_attempts=1)
    run = index.ingest(plan)
    run['search_artifact'] = asdict(build_search_artifact(run, manifest_records(run, config), corpus, config))
    atomic_json(index._run_path(run['run_id']), run)
    with pytest.raises(ValueError, match='snapshot'):
        index.activate(run['run_id'], plan)
    snapshot = config.path('corpus_dir') / corpus.xml_hash / 'AmgenProducts.xml'
    snapshot.parent.mkdir(parents=True)
    snapshot.write_bytes(corpus.xml_path.read_bytes())
    active = index.activate(run['run_id'], plan)
    assert active['run_id'] == run['run_id']
    original_xml = snapshot.read_bytes()
    snapshot.write_bytes(b'changed snapshot')
    with pytest.raises(ValueError, match='snapshot'):
        index.rollback(run['run_id'])
    assert index.active() == active
    snapshot.write_bytes(original_xml)
    artifact = config.root / run['search_artifact']['path']
    artifact.write_bytes(artifact.read_bytes()+b'changed')
    with pytest.raises(ValueError, match='artifact'):
        index.rollback(run['run_id'])
    assert index.active() == active


def test_bulk_policy_does_not_depend_on_later_manual_review_decisions(tmp_path):
    corpus, source_dir = source_corpus(tmp_path)
    reviews = ReviewStore(tmp_path/'review.sqlite')
    before = prepare_chunks(corpus, reviews, ChunkConfig(), policy=BULK, source_dir=source_dir)
    reviews.record(corpus.blocks[1], 'rejected', 'Curator')
    after = prepare_chunks(corpus, reviews, ChunkConfig(), policy=BULK, source_dir=source_dir)
    assert before == after


@pytest.mark.parametrize('mutation', ['text', 'archive_span', 'parent_span', 'limitations', 'coverage'])
def test_direct_bulk_publication_rechecks_exact_records_against_pinned_xml(tmp_path, config, mutation):
    from dataclasses import asdict
    from amgen_explorer.extraction import build_corpus
    from amgen_explorer.xml_store import load_corpus
    from amgen_explorer.search import build_search_artifact
    corpus,source_dir=source_corpus(tmp_path,
        'FULL PRESCRIBING INFORMATION\n5 WARNINGS AND PRECAUTIONS\nTable 1\nValues have unverified row relationships.')
    build_corpus(source_dir,corpus.xml_path)
    corpus=load_corpus(corpus.xml_path)
    plan=prepare_chunks(corpus,None,ChunkConfig(),policy=BULK,source_dir=source_dir)
    chunk=next(c for c in plan.chunks if c.metadata['extraction_limitations'])
    if mutation=='text': chunk.metadata['source_text']='Invented source claim.'
    if mutation in {'archive_span','parent_span'}:
        spans=json.loads(chunk.metadata['source_spans'])
        spans[0]['start' if mutation=='archive_span' else 'block_start']+=1
        chunk.metadata['source_spans']=json.dumps(spans)
    if mutation=='limitations': chunk.metadata['extraction_limitations']=[]
    fake=FakeDocuments()
    index=IndexService(config,fake,sleep=lambda _:None,verification_attempts=1)
    run=index.ingest(plan)
    if mutation=='coverage':
        run['coverage']={**run['coverage'],'expected_characters':1,'covered_characters':1}
    run['search_artifact']=asdict(build_search_artifact(run,manifest_records(run,config),corpus,config))
    atomic_json(index._run_path(run['run_id']),run)
    snapshot=config.path('corpus_dir')/corpus.xml_hash/'AmgenProducts.xml'
    snapshot.parent.mkdir(parents=True)
    snapshot.write_bytes(corpus.xml_path.read_bytes())
    with pytest.raises(ValueError,match='source|coverage'):
        index.activate(run['run_id'],plan)
    assert index.active() is None


@pytest.mark.parametrize('experience', ['provider_fallback', 'quiz'])
def test_bulk_learning_does_not_describe_unreviewed_machine_sources_as_reviewed(tmp_path, experience):
    from amgen_explorer.connectivity import ProviderError
    from amgen_explorer.teaching import make_quiz
    corpus,source_dir=source_corpus(tmp_path)
    plan=prepare_chunks(corpus,None,ChunkConfig(),policy=BULK,source_dir=source_dir)
    chunk=plan.chunks[0]
    evidence=EvidenceBundle('Explain source text','one','bulk',corpus.xml_hash,
        [{'id':chunk.id,'text':chunk.metadata['source_text'],'metadata':chunk.metadata,'namespace':'bulk'}],
        eligibility_policy=BULK,eligibility_fingerprint=plan.eligibility_fingerprint)
    class OfflineProvider:
        def generate(self,*args,**kwargs): raise ProviderError('OpenAI',503)
    if experience=='provider_fallback':
        text=teach('Explain source text',evidence,None,client=OfflineProvider()).answer
    else:
        text=make_quiz(evidence,None)['rationale']
    assert 'reviewed' not in text.lower()


def test_direct_bulk_evidence_cannot_explain_incomplete_continuation_without_warning(tmp_path,config):
    corpus,directory=source_corpus(tmp_path,('é'*80+'\n')*80)
    plan=prepare_chunks(corpus,None,ChunkConfig(target_tokens=300,overlap_tokens=0),policy=BULK,source_dir=directory)
    fake=FakeDocuments();index=IndexService(config,fake,sleep=lambda _:None,verification_attempts=1)
    run=index.ingest(plan)
    config.settings['retrieval']['evidence_token_budget']=700
    bundle=retrieve('Explain source text','one',run,config,'doc-one',client=fake)
    bundle.passages=[{'id':plan.chunks[0].id,'text':plan.chunks[0].metadata['source_text'],
                      'metadata':plan.chunks[0].metadata,'namespace':run['namespace']}]
    bundle.warnings=[]  # Direct callers must not bypass context checks by omitting warnings.
    class NoProvider:
        def generate(self,*args,**kwargs):raise AssertionError('Incomplete context reached generation')
    response=teach('Explain source text',bundle,config,client=NoProvider())
    assert response.abstained and response.usage['source_fallback']
