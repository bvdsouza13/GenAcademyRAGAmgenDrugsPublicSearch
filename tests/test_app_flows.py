"""Exercise the explicit ?legacy=1 recovery UI with a provider-free facade.

Old review/publication assertions stay intact outside the routine bulk navigation.
"""
from pathlib import Path
from types import SimpleNamespace
import sys
import pytest
from streamlit.testing.v1 import AppTest
from amgen_explorer.models import BuildReport, Chunk, ChunkPlan, Corpus, Document, Product, SourceBlock, TeachingResponse

ROOT = Path(__file__).resolve().parents[1]

class FakeService:
    def __init__(self, tmp_path):
        self.config = SimpleNamespace(root=tmp_path, settings={"chunking": {"target_tokens":600,"overlap_tokens":80}, "openai":{"model":""}}, validate=lambda **kw:["OPENAI_API_KEY is missing."] if kw.get("require_chat") else [])
        self.calls = []
        self.present = True
        self.fail_build = False
        self.active_value = None
        self.run_values=[]
        self.chunk_values=[]
        self.load_status="verifying"
        self.xml = tmp_path / 'AmgenProducts.xml'
        self.xml.write_text('<corpus/>')
        self.product = Product('repatha','REPATHA','evolocumab',['doc'])
        self.block = SourceBlock('block','repatha','doc','sha','Original label passage.','s1','Indications','indications',1,1,'hash')
        self.data = Corpus(self.xml,'xml-sha',[self.product],[Document('doc','repatha','repatha.pdf','sha',12)], [self.block])
        self.reviews = SimpleNamespace(status=lambda b:'needs-review', summary=lambda c:{'accepted':0,'needs-review':1})
        self.index = SimpleNamespace(runs=lambda:self.run_values)
    def corpus(self): return self.data if self.present else None
    def inventory(self): return [{'filename':'repatha.pdf','status':'Available'}]
    def active(self): return self.active_value
    def build(self):
        self.calls.append('build')
        if self.fail_build: raise RuntimeError('SECRET_SHOULD_NOT_RENDER')
        self.present = True
        return BuildReport(str(self.xml),'xml-sha',1,1,12,1,True)
    def source_pdf(self, document_id): return b'%PDF-test'
    def source_page(self, document_id, page): return b''
    def connection_status(self): self.calls.append('connections'); return {'pinecone':{'status':'missing','message':'PINECONE_API_KEY is missing.'}}
    def chunk_config(self,target_tokens=600,overlap_tokens=80): return SimpleNamespace(target_tokens=target_tokens,overlap_tokens=overlap_tokens)
    def preview(self, config, **kwargs):
        self.calls.append('preview')
        return ChunkPlan(self.chunk_values, [] if self.chunk_values else [{'block_id':'block','reason':'needs-review'}], 'fp','xml-sha','config','review',{})
    def load(self,plan,on_progress=None):
        self.calls.append('load')
        result={'run_id':'staged','status':self.load_status,'namespace':'staging','xml_hash':'xml-sha','product_ids':['repatha'],'record_count':len(plan.chunks),'succeeded':len(plan.chunks)}
        self.run_values=[result]
        return result
    def publish(self,run_id,plan):
        self.calls.append('publish'); self.active_value=self.run_values[0]; return self.active_value
    def rollback(self,run_id): self.calls.append('rollback'); return {}
    def presets(self): return {}
    def save_preset(self,*args): self.calls.append('preset')
    def review(self,*args): self.calls.append(('review',args))
    def answer(self, question, product_id, **kwargs):
        self.calls.append(('answer', product_id, question, kwargs))
        return TeachingResponse('An evidence-backed explanation.', [{'document_id':'doc','filename':'repatha.pdf','page_start':1,'page_end':1,'section_title':'Indications','text':'Original label passage.'}])
    def quiz(self,*args,**kwargs): self.calls.append('quiz'); return {'question':'Which section?','choices':['Indications','Other'],'correct_index':0,'rationale':'The cited section.','citations':[]}

@pytest.fixture
def app(monkeypatch,tmp_path):
    service = FakeService(tmp_path)
    monkeypatch.setitem(sys.modules,'amgen_explorer.service',SimpleNamespace(ExplorerService=lambda:service))
    at = AppTest.from_file(str(ROOT/'app.py'), default_timeout=15)
    at.query_params['legacy']='1'
    return at, service

def navigate(at, name):
    at.sidebar.radio(key='nav').set_value(name).run()
    assert not at.exception

def click(at,label):
    next(b for b in at.button if b.label == label).click().run()
    assert not at.exception

def test_initial_empty_and_missing_credentials_are_honest(app):
    at,s = app; s.present=False
    at.run()
    assert not at.exception
    assert any('No XML collection' in x.value for x in at.info)
    navigate(at,'Learn with chat')
    assert at.chat_input[0].disabled
    assert not s.calls

def test_build_is_explicit_and_does_not_repeat(app):
    at,s=app; at.run(); navigate(at,'Manage sources')
    assert 'build' not in s.calls
    click(at,'Build XML')
    assert s.calls.count('build')==1
    assert any('XML built' in x.value for x in at.success)
    at.run()
    assert s.calls.count('build')==1

def test_build_failure_is_honest_and_redacted(app):
    at,s=app; s.fail_build=True; at.run(); navigate(at,'Manage sources'); click(at,'Build XML')
    assert any('Build XML failed' in x.value for x in at.error)
    assert 'SECRET_SHOULD_NOT_RENDER' not in str(at)
    assert s.active_value is None

def test_connection_check_is_explicit(app):
    at,s=app; at.run(); navigate(at,'Manage sources')
    assert 'connections' not in s.calls
    click(at,'Test connections')
    assert s.calls.count('connections')==1
    at.run(); assert s.calls.count('connections')==1
    assert any('PINECONE_API_KEY' in x.value for x in at.warning)

def test_review_requires_reviewer_and_explicit_submit(app):
    at,s=app; at.run(); navigate(at,'Manage sources')
    assert next(b for b in at.button if b.label=='Save review').disabled
    at.text_input(key='reviewer').set_value('Local reviewer').run()
    click(at,'Save review')
    assert any(isinstance(x,tuple) and x[0]=='review' for x in s.calls)

def test_chat_is_scoped_and_never_repeats_on_rerun(app):
    at,s=app; s.active_value={'run_id':'live','namespace':'v1','xml_hash':'xml-sha','product_ids':['repatha']}
    s.config.validate=lambda **kw:[]
    at.run(); navigate(at,'Learn with chat')
    at.chat_input[0].set_value('What does the label say?').run()
    assert not at.exception
    answers=[x for x in s.calls if isinstance(x,tuple) and x[0]=='answer']
    assert len(answers)==1 and answers[0][1]=='repatha'
    assert any('evidence-backed' in x.value for x in at.markdown)
    at.run()
    assert len([x for x in s.calls if isinstance(x,tuple) and x[0]=='answer'])==1


def ready_chunk(s):
    s.chunk_values=[Chunk('chunk','Medicine: REPATHA\nOriginal label passage.',{'document_id':'doc','filename':'repatha.pdf','section_title':'Indications','block_ids':['block'],'source_text':'Original label passage.','page_start':1,'page_end':1},55)]

def test_empty_preview_cannot_load_or_publish(app):
    at,s=app; at.run(); navigate(at,'Manage sources'); click(at,'Preview Pinecone load')
    assert any('No eligible reviewed chunks' in x.value for x in at.warning)
    assert not any(b.label=='Load Pinecone' for b in at.button)
    assert 'load' not in s.calls and 'publish' not in s.calls

def test_pending_ingestion_never_enables_publication(app):
    at,s=app; ready_chunk(s); at.run(); navigate(at,'Manage sources')
    click(at,'Preview Pinecone load'); click(at,'Load Pinecone')
    assert s.active_value is None
    assert any('verifying' in x.value for x in at.caption)
    assert next(b for b in at.button if b.label=='Publish configuration').disabled
    at.run(); assert s.calls.count('load')==1 and 'publish' not in s.calls

def test_verified_staging_requires_explicit_publication_and_current_settings(app):
    at,s=app; ready_chunk(s); s.load_status='verified'; at.run(); navigate(at,'Manage sources')
    click(at,'Preview Pinecone load'); click(at,'Build test index')
    assert s.active_value is None
    assert not next(b for b in at.button if b.label=='Publish configuration').disabled
    at.slider(key='target_tokens').set_value(650).run()
    assert next(b for b in at.button if b.label=='Publish configuration').disabled
    at.slider(key='target_tokens').set_value(600).run()
    click(at,'Publish configuration')
    assert s.calls.count('publish')==1 and s.active_value is not None
    at.run(); assert s.calls.count('publish')==1

def test_quiz_only_runs_on_request_and_records_checked_progress(app):
    at,s=app; s.active_value={'run_id':'live','xml_hash':'xml-sha','product_ids':['repatha']}; s.config.validate=lambda **kw:[]
    at.run(); navigate(at,'Learn with chat')
    lesson=next(r for r in at.radio if r.label=='Learning steps')
    lesson.set_value('Check your understanding').run()
    assert 'quiz' not in s.calls
    click(at,'Create a source-based quiz')
    assert s.calls.count('quiz')==1
    answer=next(r for r in at.radio if r.label=='Your answer')
    answer.set_value(0).run(); click(at,'Check answer')
    assert any('Correct.' in x.value for x in at.success)
    navigate(at,'My learning')
    assert next(m for m in at.metric if m.label=='Quizzes checked').value=='1'
    assert s.calls.count('quiz')==1


def test_missing_chat_credential_disables_a_published_medicine(app):
    at,s=app; s.active_value={'run_id':'live','xml_hash':'xml-sha','product_ids':['repatha']}
    at.run(); navigate(at,'Learn with chat')
    assert at.chat_input[0].disabled
    assert any('OPENAI_API_KEY is missing' in x.value for x in at.info)
    assert not any(isinstance(x,tuple) and x[0]=='answer' for x in s.calls)


def test_multiple_document_scopes_require_a_document_before_chat(app):
    at,s=app; s.active_value={'run_id':'live','xml_hash':'xml-sha','product_ids':['repatha'],'document_ids':['doc','variant']}; s.config.validate=lambda **kw:[]
    s.data.documents.append(Document('variant','repatha','repatha-latex.pdf','sha2',10,variant_hint='Device-specific label'))
    at.run(); navigate(at,'Learn with chat')
    assert at.chat_input[0].disabled
    assert any('multiple source scopes' in x.value for x in at.info)
    at.selectbox(key='document_id').set_value('variant').run()
    assert not at.chat_input[0].disabled
    at.chat_input[0].set_value('Explain this presentation').run()
    request=next(x for x in s.calls if isinstance(x,tuple) and x[0]=='answer')
    assert request[3]['document_id']=='variant'


def test_style_switch_is_local_until_a_question_is_submitted(app):
    at,s=app; s.active_value={'run_id':'live','xml_hash':'xml-sha','product_ids':['repatha']}; s.config.validate=lambda **kw:[]
    at.run(); navigate(at,'Learn with chat')
    at.radio(key='learning_mode').set_value('Technical detail').run()
    assert not any(isinstance(x,tuple) and x[0]=='answer' for x in s.calls)
    at.chat_input[0].set_value('Explain the mechanism').run()
    request=next(x for x in s.calls if isinstance(x,tuple) and x[0]=='answer')
    assert request[3]['mode']=='Technical detail'


def test_reexplain_is_explicit_and_reuses_the_prior_evidence(app):
    from amgen_explorer.models import EvidenceBundle
    at,s=app; s.active_value={'run_id':'live','xml_hash':'xml-sha','product_ids':['repatha']}; s.config.validate=lambda **kw:[]
    evidence=EvidenceBundle('Question','repatha','v1','xml-sha',[{'id':'source','text':'Original passage'}])
    def answer(question,product_id,**kwargs):
        s.calls.append(('answer',product_id,question,kwargs))
        return TeachingResponse('Plain explanation.',evidence=evidence)
    def reexplain(question,prior_response,mode,product_id,document_id=None):
        s.calls.append(('reexplain',prior_response.evidence,mode))
        return TeachingResponse('Technical explanation.',evidence=prior_response.evidence)
    s.answer=answer; s.reexplain=reexplain
    at.run(); navigate(at,'Learn with chat'); at.chat_input[0].set_value('Question').run()
    at.radio(key='learning_mode').set_value('Technical detail').run()
    assert not any(isinstance(x,tuple) and x[0]=='reexplain' for x in s.calls)
    click(at,'Re-explain last answer')
    call=next(x for x in s.calls if isinstance(x,tuple) and x[0]=='reexplain')
    assert call[1] is evidence and call[2]=='Technical detail'
    assert len([x for x in s.calls if isinstance(x,tuple) and x[0]=='answer'])==1
    at.run()
    assert len([x for x in s.calls if isinstance(x,tuple) and x[0]=='reexplain'])==1


class SourceViewHarness:
    """Small rendered-output spy for source cache provenance, with no providers."""
    def __init__(self):
        self.session_state={}
        self.images=[]
        self.clicked=True
    def caption(self,*args,**kwargs): pass
    def download_button(self,*args,**kwargs): pass
    def button(self,*args,**kwargs): return self.clicked
    def image(self,data,**kwargs): self.images.append((data,kwargs.get('caption')))


@pytest.mark.parametrize('change', ['document','xml','page','working-pdf'])
def test_source_page_cache_never_relabels_another_source(monkeypatch,change):
    from ui import common
    view=SourceViewHarness()
    pdf={'bytes':b'VERIFIED PDF A'}
    renders=[]
    service=SimpleNamespace(source_pdf=lambda *a,**kw:pdf['bytes'],source_page=lambda *a,**kw:renders.append((a,kw)) or b'OLD ORIGINAL PAGE')
    monkeypatch.setattr(common,'st',view)
    monkeypatch.setattr(common,'action',lambda label,fn,**kw:(True,fn()))
    document,xml,page='document-a','xml-a',2
    if change=='working-pdf': xml=None
    common.source_view(service,document,'same-filename.pdf','reused',page=page,xml_hash=xml)
    assert view.images==[(b'OLD ORIGINAL PAGE','Original PDF · page 2')]
    view.images.clear();view.clicked=False
    if change=='document': document='document-b'
    elif change=='xml': xml='xml-b'
    elif change=='page': page=9
    else: pdf['bytes']=b'CHANGED WORKING PDF WITH SAME FILENAME'
    common.source_view(service,document,'same-filename.pdf','reused',page=page,xml_hash=xml)
    assert view.images==[], 'A different source must never display the previously rendered page'
    assert len(renders)==1, 'Changing identity must not implicitly render a new page'


def test_source_page_cache_reuses_the_identical_verified_source(monkeypatch):
    from ui import common
    view=SourceViewHarness();renders=[]
    service=SimpleNamespace(source_pdf=lambda *a,**kw:b'VERIFIED PDF',source_page=lambda *a,**kw:renders.append((a,kw)) or b'CURRENT ORIGINAL PAGE')
    monkeypatch.setattr(common,'st',view)
    monkeypatch.setattr(common,'action',lambda label,fn,**kw:(True,fn()))
    common.source_view(service,'doc','source.pdf','reused',page=2,xml_hash='xml-a')
    view.images.clear();view.clicked=False
    common.source_view(service,'doc','source.pdf','reused',page=2,xml_hash='xml-a')
    assert view.images==[(b'CURRENT ORIGINAL PAGE','Original PDF · page 2')]
    assert len(renders)==1


def test_legacy_unbound_source_page_cache_is_not_displayed(monkeypatch):
    from ui import common
    view=SourceViewHarness();view.clicked=False
    view.session_state['page_image_reused']=b'LEGACY UNBOUND PAGE'
    service=SimpleNamespace(source_pdf=lambda *a,**kw:b'VERIFIED PDF')
    monkeypatch.setattr(common,'st',view)
    common.source_view(service,'doc','source.pdf','reused',page=9,xml_hash='xml-new')
    assert view.images==[]


def test_unavailable_pdf_cannot_reuse_a_cached_original_page(monkeypatch):
    from ui import common
    view=SourceViewHarness();pdf={'available':True}
    def source_pdf(*args,**kwargs):
        if not pdf['available']: raise ValueError('Unavailable')
        return b'VERIFIED PDF'
    service=SimpleNamespace(source_pdf=source_pdf,source_page=lambda *a,**kw:b'ORIGINAL PAGE')
    monkeypatch.setattr(common,'st',view)
    monkeypatch.setattr(common,'action',lambda label,fn,**kw:(True,fn()))
    common.source_view(service,'doc','source.pdf','reused',page=2)
    view.images.clear();view.clicked=False;pdf['available']=False
    common.source_view(service,'doc','source.pdf','reused',page=2)
    assert view.images==[]


def source_passages(at):
    from xml.etree import ElementTree as ET
    return [ET.fromstring(item.value).text or '' for item in at.get('html') if item.value.startswith('<div class="source-passage"')]


def published(s, documents=None):
    s.active_value={'run_id':'live','xml_hash':'xml-sha','product_ids':['repatha']}
    if documents is not None:
        s.active_value['document_ids']=documents
    s.config.validate=lambda **kw:[]


def test_source_scope_does_not_repeat_filename_as_variant(app):
    at,s=app
    s.data.documents[0].variant_hint='repatha.pdf'
    at.run(); navigate(at,'Learn with chat')
    assert at.selectbox(key='document_id').options==['All source documents for this medicine','repatha.pdf']
    assert not any(c.value=='repatha.pdf' for c in at.caption)


def test_source_fallback_is_labeled_without_claiming_evidence_is_missing(app):
    at,s=app; published(s)
    quote='\n  Exact <source> text & units.\n  Keep the 140 mg unit and line breaks.\n'
    s.answer=lambda *args,**kwargs:TeachingResponse('Reviewed source excerpt [1]',[{'document_id':'doc','filename':'repatha.pdf','page_start':1,'text':quote,'supporting_quote':quote}],True,usage={'source_fallback':True})
    at.run(); navigate(at,'Learn with chat')
    at.chat_input[0].set_value('Explain this passage').run()
    for _ in range(2):
        assert any('Source excerpt' in x.value and 'explanation not verified' in x.value for x in at.caption)
        assert not any('Not found' in x.value for x in at.caption)
        assert source_passages(at).count(quote)==1
        at.run()


def test_safety_decline_does_not_claim_the_library_has_no_evidence(app):
    at,s=app; published(s)
    s.answer=lambda *args,**kwargs:TeachingResponse('Ask your clinician about individual treatment.',abstained=True)
    at.run(); navigate(at,'Learn with chat')
    at.chat_input[0].set_value('Should I take this medicine?').run()
    assert any('Explanation withheld' in x.value for x in at.caption)
    assert not any('Not found' in x.value for x in at.caption)


def test_unpublished_selected_scope_disables_chat_and_quiz(app):
    at,s=app; published(s,['doc'])
    s.data.documents.append(Document('draft','repatha','draft.pdf','draft-sha',1))
    at.run(); navigate(at,'Learn with chat')
    at.selectbox(key='document_id').set_value('draft').run()
    assert at.chat_input[0].disabled
    assert any('source document' in x.value and 'published' in x.value for x in at.info)
    next(r for r in at.radio if r.label=='Learning steps').set_value('Check your understanding').run()
    assert next(b for b in at.button if b.label=='Create a source-based quiz').disabled
    assert 'quiz' not in s.calls


def test_review_decision_starts_with_the_recorded_status(app):
    at,s=app; s.reviews.status=lambda block:'accepted'
    at.run(); navigate(at,'Manage sources')
    assert at.selectbox(key='decision_block').value=='accepted'
    assert not any(isinstance(c,tuple) and c[0]=='review' for c in s.calls)


def test_catalog_ignores_accidental_outer_search_spaces(app):
    at,s=app; at.run()
    at.text_input(key='catalog_search').set_value('  evolocumab  ').run()
    assert any(b.key=='learn_repatha' for b in at.button)
    assert not any('No medicines match' in x.value for x in at.info)


def test_switching_scope_keeps_conversations_separate_and_resets_removed_source(app):
    at,s=app; published(s,['doc','variant'])
    s.data.documents.append(Document('variant','repatha','variant.pdf','sha2',1))
    at.run(); navigate(at,'Learn with chat')
    at.selectbox(key='document_id').set_value('doc').run()
    at.chat_input[0].set_value('Question for original source').run()
    at.selectbox(key='document_id').set_value('variant').run()
    assert not any('evidence-backed' in m.value for m in at.markdown)
    at.selectbox(key='document_id').set_value('doc').run()
    assert any('Question for original source' in m.value for m in at.markdown)
    s.data.documents=[d for d in s.data.documents if d.id!='doc']
    at.run()
    assert not at.exception
    assert at.selectbox(key='document_id').value is None
    assert not any('Question for original source' in m.value for m in at.markdown)


def test_empty_published_document_scope_cannot_enable_chat(app):
    at,s=app; published(s,[])
    at.run(); navigate(at,'Learn with chat')
    assert at.chat_input[0].disabled
    assert any('no source documents' in x.value.lower() for x in at.info)


def test_changed_quiz_choice_requires_checking_again(app):
    at,s=app; published(s)
    at.run(); navigate(at,'Learn with chat')
    next(r for r in at.radio if r.label=='Learning steps').set_value('Check your understanding').run()
    click(at,'Create a source-based quiz')
    next(r for r in at.radio if r.label=='Your answer').set_value(0).run()
    click(at,'Check answer')
    assert any('Correct.' in x.value for x in at.success)
    next(r for r in at.radio if r.label=='Your answer').set_value(1).run()
    assert not any('Correct.' in x.value for x in at.success)
    assert not any('Review this answer:' in x.value for x in at.info)
    click(at,'Check answer')
    assert any('Review this answer:' in x.value for x in at.info)


@pytest.fixture
def offline_service(monkeypatch,tmp_path):
    """Real service and generated PDF/XML, isolated from sources and credentials."""
    import copy
    import fitz
    import amgen_explorer.connectivity as connectivity
    from amgen_explorer.config import AppConfig, load_config
    from amgen_explorer.service import ExplorerService
    def no_network(*args,**kwargs):
        raise AssertionError('Read-only source browsing must not call a provider')
    monkeypatch.setattr(connectivity,'request_json',no_network)
    config=AppConfig(copy.deepcopy(load_config(secrets_path=tmp_path/'absent.toml').settings),tmp_path)
    config.path('source_dir').mkdir(parents=True)
    with fitz.open() as pdf:
        page=pdf.new_page()
        page.insert_text((72,72),'REPATHA (evolocumab)\nFULL PRESCRIBING INFORMATION\n1 INDICATIONS AND USAGE\nExact source reading fixture for offline UI review.')
        pdf.save(config.path('source_dir')/'repatha.pdf')
    service=ExplorerService(config)
    service.build()
    return service


def test_real_service_source_and_unpublished_library_render_without_network(monkeypatch,offline_service):
    service=offline_service
    monkeypatch.setitem(sys.modules,'amgen_explorer.service',SimpleNamespace(ExplorerService=lambda:service))
    at=AppTest.from_file(str(ROOT/'app.py'),default_timeout=15)
    at.query_params['legacy']='1'
    at.run()
    assert not at.exception
    navigate(at,'Learn with chat')
    assert at.chat_input[0].disabled
    assert len(at.get('download_button'))==1
    navigate(at,'Manage sources')
    assert any('Exact source reading fixture' in text for text in source_passages(at))
    click(at,'View original page 1')
    assert any('Original PDF · page 1' in str(image.proto) for image in at.get('image'))
    # No publish/review operation was invoked by browsing or by page rendering.
    assert service.active() is None
    assert service.reviews.summary(service.corpus()).get('accepted',0)==0


def test_real_service_provider_outage_shows_exact_source_without_false_missing_label(monkeypatch,offline_service):
    from amgen_explorer.models import EvidenceBundle
    from amgen_explorer.connectivity import ProviderError
    from amgen_explorer import retrieval, teaching
    service=offline_service
    corpus=service.corpus()
    block=next(b for b in corpus.blocks if b.section_kind!='sourcePageArchive' and 'Exact source reading fixture' in b.text)
    # This review/snapshot belongs to pytest's temporary root, never the user's corpus.
    service.review(block.id,'accepted','Offline test reviewer')
    plan=service.preview(service.chunk_config())
    service._snapshot(plan)
    chunk=plan.chunks[0]
    active={'run_id':'offline','status':'verified','namespace':'offline-fixture','xml_hash':corpus.xml_hash,'product_ids':[block.product_id],'document_ids':[block.document_id]}
    monkeypatch.setattr(service,'active',lambda:active)
    def offline_retrieval(question,product_id,*args,**kwargs):
        return EvidenceBundle(question,product_id,'offline-fixture',corpus.xml_hash,[{'id':chunk.id,'text':chunk.metadata['source_text'],'metadata':chunk.metadata,'namespace':'offline-fixture','xml_hash':corpus.xml_hash}])
    monkeypatch.setattr(retrieval,'retrieve',offline_retrieval)
    def provider_outage(*args,**kwargs):
        raise ProviderError('Offline fixture',503)
    monkeypatch.setattr(teaching,'request_json',provider_outage)
    service.config.pinecone_api_key='offline-test-key'
    service.config.openai_api_key='offline-test-key'
    service.config.settings['pinecone']['index_host']='offline-fixture.pinecone.io'
    service.config.settings['openai']['model']='fixture-model'
    monkeypatch.setitem(sys.modules,'amgen_explorer.service',SimpleNamespace(ExplorerService=lambda:service))
    at=AppTest.from_file(str(ROOT/'app.py'),default_timeout=15)
    at.query_params['legacy']='1'
    at.run()
    navigate(at,'Learn with chat')
    assert not at.chat_input[0].disabled
    at.chat_input[0].set_value('What approved uses does the source describe?').run()
    assert not at.exception
    assert any('Source excerpt' in x.value for x in at.caption)
    assert not any('Not found' in x.value for x in at.caption)
    assert source_passages(at).count(chunk.metadata['source_text'])==1
    assert any('provider is unavailable' in x.value for x in at.markdown)
    click(at,'View original page 1')
    assert any('Original PDF · page 1' in str(image.proto) for image in at.get('image'))
    at.run()
    assert any('Source excerpt' in x.value for x in at.caption)


@pytest.mark.parametrize('revision, expected', [
    (None, 'Revision not identified'),
    ('not identified', 'Revision not identified'),
    ('revision not identified', 'Revision not identified'),
    ('10/2025', 'Revision: 10/2025'),
])
def test_citation_revision_caption_does_not_repeat_its_label(revision, expected):
    at = AppTest.from_string(
        'from ui.common import citations\n'
        f'citations(None, [{{"revision": {revision!r}}}], "revision-test")'
    ).run()
    assert not at.exception
    assert at.caption[0].value == 'Selected medicine · ' + expected
