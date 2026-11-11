from test_search_experience import library_app
from test_app_flows import click, navigate


def experiment_report(s):
    def evaluate(config,suite_id='global-search',on_progress=None):
        s.calls.append(('test_settings',config,suite_id))
        return {'baseline_run_id':'first','candidate_run_id':'candidate','suite_id':'global-search','compatibility_fingerprint':'fixed-sources','metrics':{'baseline':{'document_recall_at_k':0.5,'mean_latency_ms':40},'candidate':{'document_recall_at_k':1.0,'mean_latency_ms':42}},'rows':[{'question':'latex','baseline':{'hits':[{'text':'Old cited passage','metadata':{'filename':'repatha.pdf','page_start':2}}]},'candidate':{'hits':[{'text':'Candidate cited passage','metadata':{'filename':'repatha.pdf','page_start':2}}]}}],'candidate':{'run_id':'candidate','status':'verified','is_full_library':True}}
    s.test_chunk_configuration=evaluate


def test_reset_is_draft_only_and_test_measures_without_rerun_calls(library_app):
    at,s=library_app;experiment_report(s);at.run();navigate(at,'Admin')
    at.slider(key='experiment_size').set_value(900).run()
    click(at,'Reset to defaults')
    assert at.slider(key='experiment_size').value==600
    assert not s.calls
    assert s.active_value['run_id']=='first'
    click(at,'Test settings')
    assert len([c for c in s.calls if isinstance(c,tuple) and c[0]=='test_settings'])==1
    assert any('document_recall_at_k' in x.value for x in at.json)
    assert any('Old cited passage' in x.value for x in at.get('html'))
    assert any('Candidate cited passage' in x.value for x in at.get('html'))
    assert not next(b for b in at.button if b.label=='Use this configuration').disabled
    at.run()
    assert len([c for c in s.calls if isinstance(c,tuple) and c[0]=='test_settings'])==1
    click(at,'Use this configuration')
    assert ('use_configuration','candidate') in s.calls


def test_changed_settings_cannot_activate_earlier_measurements(library_app):
    at,s=library_app;experiment_report(s);at.run();navigate(at,'Admin');click(at,'Test settings')
    at.slider(key='experiment_size').set_value(900).run()
    assert next(b for b in at.button if b.label=='Use this configuration').disabled
    click(at,'Restore current settings')
    assert at.slider(key='experiment_size').value==600
    assert len([c for c in s.calls if isinstance(c,tuple) and c[0]=='test_settings'])==1
    assert not any(isinstance(c,tuple) and c[0]=='use_configuration' for c in s.calls)


def test_local_preview_is_full_inventory_and_revert_is_explicit(library_app):
    at,s=library_app;at.run();navigate(at,'Admin');click(at,'Preview locally')
    assert any(m.label=='Prepared chunks' for m in at.metric)
    assert len([c for c in s.calls if isinstance(c,tuple) and c[0]=='preview_library'])==1
    assert not any(isinstance(c,tuple) and c[0] in {'build_library','test_settings'} for c in s.calls)
    at.run();assert 'revert_library' not in s.calls
    click(at,'Revert to previous version')
    assert s.calls.count('revert_library')==1


def test_unverified_candidate_cannot_be_chosen_even_when_report_is_returned(library_app):
    at,s=library_app
    s.test_chunk_configuration=lambda *a,**kw:{'baseline_run_id':'first','candidate_run_id':'partial','compatible':True,'candidate':{'run_id':'partial','status':'verifying','full_library':True},'metrics':{},'rows':[]}
    at.run();navigate(at,'Admin');click(at,'Test settings')
    assert next(b for b in at.button if b.label=='Use this configuration').disabled


def test_large_comparison_shows_one_selected_question_without_retesting(library_app):
    at,s=library_app;experiment_report(s)
    original=s.test_chunk_configuration
    def many(*a,**kw):
        report=original(*a,**kw)
        report['rows']=[{'question':f'Question {i}','baseline':{'hits':[{'text':f'Baseline passage {i}','metadata':{}}]},'candidate':{'hits':[{'text':f'Candidate passage {i}','metadata':{}}]}} for i in range(20)]
        return report
    s.test_chunk_configuration=many
    at.run();navigate(at,'Admin');click(at,'Test settings')
    assert len(at.get('html'))<12
    at.selectbox(key='experiment_question').set_value(3).run()
    assert any('Baseline passage 3' in h.value for h in at.get('html'))
    assert not any('Baseline passage 0' in h.value for h in at.get('html'))
    assert len([c for c in s.calls if isinstance(c,tuple) and c[0]=='test_settings'])==1
