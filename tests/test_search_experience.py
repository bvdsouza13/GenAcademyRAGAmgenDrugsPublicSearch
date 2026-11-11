"""Provider-free UI boundary tests: submission, retained evidence versions and scope."""
import sys
from types import SimpleNamespace
import pytest
from streamlit.testing.v1 import AppTest
from amgen_explorer.chunking import ChunkConfig
from amgen_explorer.models import Document, Product
from test_app_flows import FakeService, ROOT, click

class LibraryService(FakeService):
    def __init__(self, tmp_path):
        super().__init__(tmp_path)
        self.config.validate=lambda **kw:[]
        self.active_value={'run_id':'first','xml_hash':'xml-sha','product_ids':['repatha','actimmune'],'document_ids':['doc','variant','act'],'is_full_library':True,'record_count':3}
        self.data.products.append(Product('actimmune','ACTIMMUNE','interferon gamma',['act']))
        self.data.documents.extend([Document('variant','repatha','repatha-latex.pdf','sha2',3),Document('act','actimmune','actimmune.pdf','sha3',4)])
        self.versions={'first':dict(self.active_value)}
        self.pdf_calls=[]
        self.fail_test=False
    def library_status(self):
        return {'active':self.active_value,'source_documents':3,'source_products':2,'searchable_documents':3 if self.active_value else 0,'searchable_products':2 if self.active_value else 0,'record_count':3 if self.active_value else 0,'is_full_library':bool(self.active_value),'versions':list(self.versions.values())}
    def library_version(self,run_id): return self.versions[run_id]
    def library_corpus(self,run_id): return self.data
    def search_library(self,query,**kwargs):
        self.calls.append(('search',query,kwargs))
        run=self.active_value['run_id']
        hits=[{'id':doc,'text':'The needle cover contains dry natural rubber (a derivative of latex).','run_id':run,'product_name':name,'filename':filename,'revision':'10/2025','metadata':{'product_id':product,'document_id':doc,'page_start':2,'section_title':'Warnings','xml_hash':'xml-sha'}} for doc,product,name,filename in [('act','actimmune','ACTIMMUNE','actimmune.pdf'),('doc','repatha','REPATHA','repatha.pdf'),('variant','repatha','REPATHA','repatha-latex.pdf')]]
        return SimpleNamespace(query=query,run_id=run,namespace=run,xml_hash='xml-sha',hits=hits,groups=[],warnings=[],degraded=False,ranking_version='v1')
    def source_pdf(self,document_id,xml_hash=None):
        self.pdf_calls.append((document_id,xml_hash));return b'%PDF-test'
    def latest_library_settings(self): return ChunkConfig()
    def preview_library(self,config):
        self.calls.append(('preview_library',config));return SimpleNamespace(chunks=[],excluded=[],coverage={'complete':True,'covered_characters':40,'total_characters':40})
    def build_library(self,config,activate=True,on_progress=None):
        self.calls.append(('build_library',config,activate))
        if self.fail_build: raise RuntimeError('SECRET_SHOULD_NOT_RENDER')
        result={**self.active_value,'status':'verified','record_count':3}
        return result
    def test_chunk_configuration(self,config,suite_id='global-search',on_progress=None):
        self.calls.append(('test_settings',config,suite_id))
        if self.fail_test: raise RuntimeError('SECRET_TEST_ERROR')
        return {'baseline_run_id':'first','candidate_run_id':'candidate','compatible':True,'compatibility_fingerprint':'fixed-sources','baseline':{'metrics':{'document_recall_at_k':0.5},'results':[]},'candidate':{'metrics':{'document_recall_at_k':1.0},'results':[]}}
    def use_configuration(self,run_id): self.calls.append(('use_configuration',run_id));return self.active_value
    def revert_library(self): self.calls.append('revert_library');return self.active_value

@pytest.fixture
def library_app(monkeypatch,tmp_path):
    service=LibraryService(tmp_path)
    monkeypatch.setitem(sys.modules,'amgen_explorer.service',SimpleNamespace(ExplorerService=lambda:service))
    return AppTest.from_file(str(ROOT/'app.py'),default_timeout=15),service

def test_body_text_search_requires_submit_and_retains_source_version(library_app):
    at,s=library_app;at.run()
    assert not at.exception
    assert at.sidebar.radio(key='nav').value=='Search & Learn'
    at.text_input(key='library_query').set_value('latex')
    assert not any(isinstance(c,tuple) and c[0]=='search' for c in s.calls)
    click(at,'Search')
    assert any('ACTIMMUNE' in m.value for m in at.markdown)
    assert any('repatha-latex.pdf' in m.value for m in at.markdown)
    assert any('repatha.pdf' in m.value for m in at.markdown)
    s.active_value={**s.active_value,'run_id':'second'}
    at.run()
    assert len([c for c in s.calls if isinstance(c,tuple) and c[0]=='search'])==1
    assert any('first' in c.value for c in at.caption)
    next(b for b in at.button if b.key=='ask_first_act').click().run()
    assert not at.exception
    assert not any(isinstance(c,tuple) and c[0]=='answer' for c in s.calls)
    assert any('latex' in c.value for c in at.caption)
    assert ('act','xml-sha') in s.pdf_calls
    at.chat_input[0].set_value('What does it say?').run()
    answer=next(c for c in s.calls if isinstance(c,tuple) and c[0]=='answer')
    assert answer[1]=='actimmune' and answer[3]['document_id']=='act' and answer[3]['run_id']=='first'
    at.run()
    assert len([c for c in s.calls if isinstance(c,tuple) and c[0]=='answer'])==1

def test_unavailable_library_distinguishes_local_files(library_app):
    at,s=library_app;s.active_value=None;at.run()
    assert not at.exception
    assert next(b for b in at.button if b.label=='Search').disabled
    assert any(m.label=='Searchable documents' and m.value=='0' for m in at.metric)
    assert any('local' in c.value.lower() and '3' in c.value for c in at.caption)
    assert not s.calls


def test_quiz_and_reexplanation_stay_on_selected_result_after_activation(library_app):
    from amgen_explorer.models import EvidenceBundle,TeachingResponse
    at,s=library_app
    evidence=EvidenceBundle('Question','actimmune','first','xml-sha',[],run_id='first')
    def answer(question,product_id,**kwargs):
        s.calls.append(('answer',product_id,question,kwargs))
        return TeachingResponse('Pinned explanation',evidence=evidence)
    def quiz(product_id,**kwargs):
        s.calls.append(('quiz',product_id,kwargs))
        return {'question':'Question','choices':['A','B'],'correct_index':0,'citations':[]}
    def reexplain(question,prior,mode,product_id,document_id=None):
        s.calls.append(('reexplain',prior.evidence,document_id))
        return TeachingResponse('Pinned technical explanation',evidence=prior.evidence)
    s.answer=answer;s.quiz=quiz;s.reexplain=reexplain
    at.run();at.text_input(key='library_query').set_value('latex');click(at,'Search')
    next(b for b in at.button if b.key=='ask_first_act').click().run()
    s.active_value={**s.active_value,'run_id':'second','product_ids':['repatha'],'document_ids':['doc']}
    at.chat_input[0].set_value('Question').run()
    assert not at.chat_input[0].disabled
    at.radio(key='learning_mode').set_value('Technical detail').run()
    click(at,'Re-explain last answer')
    assert ('reexplain',evidence,'act') in s.calls
    next(r for r in at.radio if r.label=='Learning steps').set_value('Check your understanding').run()
    click(at,'Create a source-based quiz')
    assert ('quiz','actimmune',{'document_id':'act','run_id':'first'}) in s.calls
    at.run()
    assert len([c for c in s.calls if isinstance(c,tuple) and c[0]=='quiz'])==1


def test_view_source_download_uses_result_snapshot_after_activation(library_app):
    at,s=library_app;at.run();at.text_input(key='library_query').set_value('latex');click(at,'Search')
    s.active_value={**s.active_value,'run_id':'second'}
    next(b for b in at.button if b.key=='view_first_variant').click().run()
    assert ('variant','xml-sha') in s.pdf_calls
    assert not any(isinstance(c,tuple) and c[0]=='answer' for c in s.calls)


def test_active_search_survives_unreadable_working_xml(library_app):
    at,s=library_app
    def unavailable(): raise ValueError('working XML malformed')
    s.corpus=unavailable
    at.run()
    assert not at.exception
    assert any(b.label=='Search' and not b.disabled for b in at.button)
    at.text_input(key='library_query').set_value('latex');click(at,'Search')
    assert any('ACTIMMUNE' in m.value for m in at.markdown)


def test_legacy_pilot_does_not_advertise_ready_global_search(library_app):
    at,s=library_app
    s.active_value={**s.active_value,'is_full_library':False}
    s.library_status=lambda:{'active':s.active_value,'is_full_library':False,'source_documents':3,'searchable_documents':1,'searchable_products':1,'record_count':2}
    at.run()
    assert next(b for b in at.button if b.label=='Search').disabled
    assert any('full library' in m.value.lower() for m in at.info)


def test_each_passage_in_group_can_open_its_own_page(library_app):
    import copy
    at,s=library_app
    original=s.search_library
    def repeated(query,**kwargs):
        results=original(query,**kwargs)
        later=copy.deepcopy(results.hits[0]);later['id']='later';later['metadata']['page_start']=3
        results.hits.append(later);return results
    s.search_library=repeated
    at.run();at.text_input(key='library_query').set_value('latex');click(at,'Search')
    next(b for b in at.button if b.key=='view_passage_first_act_later').click().run()
    assert not at.exception
    assert any(b.label=='View original page 3' for b in at.button)
    assert ('act','xml-sha') in s.pdf_calls
