"""Routine administration never depends on learner scope or passage decisions."""
from test_search_experience import library_app
from test_app_flows import click, navigate


def test_entire_library_build_is_explicit_and_independent_of_learner_filters(library_app):
    at,s=library_app
    at.session_state['product_id']='actimmune'
    at.session_state['document_id']='act'
    at.run();navigate(at,'Admin')
    assert not s.calls
    assert not any(b.label in {'Save review','Load Pinecone','Build test index','Publish configuration'} for b in at.button)
    click(at,'Build / update entire library')
    assert any('ready to search' in msg.value for msg in at.success)
    assert len([c for c in s.calls if isinstance(c,tuple) and c[0]=='build_library'])==1
    assert next(c for c in s.calls if isinstance(c,tuple) and c[0]=='build_library')[2] is True
    at.run()
    assert len([c for c in s.calls if isinstance(c,tuple) and c[0]=='build_library'])==1
    assert next(m for m in at.metric if m.label=='Records at last build').value=='3'


def test_failed_build_preserves_search_and_offers_full_retry_without_secrets(library_app):
    at,s=library_app;s.fail_build=True;at.run();navigate(at,'Admin')
    click(at,'Build / update entire library')
    assert any('failed' in msg.value for msg in at.error)
    assert s.active_value['run_id']=='first'
    assert 'SECRET_SHOULD_NOT_RENDER' not in str(at)
    at.run()
    assert any(b.label=='Retry entire library build' for b in at.button)
    at.run()
    assert len([c for c in s.calls if isinstance(c,tuple) and c[0]=='build_library'])==1


def test_partial_build_must_not_be_presented_as_ready(library_app):
    at,s=library_app
    s.build_library=lambda *a,**kw:{'status':'verifying','record_count':100,'succeeded':2}
    at.run();navigate(at,'Admin');click(at,'Build / update entire library')
    assert not any('ready to search' in m.value for m in at.success)
    assert any('not completed verification' in m.value for m in at.error)


def test_verification_and_repair_require_separate_clicks(library_app):
    at,s=library_app
    def verify(run_id=None, *, repair=False):
        s.calls.append(('verify',run_id,repair))
        return {'run_id':'first','outcome':'verified' if repair else 'drift','checked_at':1795352400,
                'expected_count':3,'matched_count':3 if repair else 2,'missing_count':0 if repair else 1,
                'mismatched_count':0,'document_visibility':{'doc':True},'errors':[]}
    s.verify_library=verify
    at.run();navigate(at,'Admin')
    assert not s.calls
    click(at,'Verify stored library')
    assert s.calls==[('verify','first',False)]
    at.run();assert len(s.calls)==1
    click(at,'Repair missing or changed records')
    assert s.calls[-1]==('verify','first',True)
    assert any('Expected records verified' in msg.value for msg in at.success)
    at.run();assert len(s.calls)==2


def test_generation_readiness_is_explicit_and_timestamped(library_app):
    at,s=library_app
    def check(*,require_generation=False):
        s.calls.append(('readiness',require_generation))
        return {'checked_at':1795352400,'ok':False,'model_access':{'ok':True},
                'semantic_search':{'ok':True},'generation':{'ok':False,'state':'provider_unavailable'}}
    s.check_readiness=check;s.latest_readiness=lambda:None
    at.run();navigate(at,'Admin');assert not s.calls
    click(at,'Check search and generated answers')
    assert s.calls==[('readiness',True)]
    assert any('provider_unavailable' in m.value for m in at.warning)
    assert any('Last checked' in m.value for m in at.caption)
    at.run();assert len(s.calls)==1


def test_admin_status_failure_keeps_recovery_reachable(library_app):
    at,s=library_app
    def broken(): raise ValueError('damaged status')
    s.library_status=broken
    s.list_recoverable_versions=lambda:{'versions':[],'warnings':[]}
    at.run();navigate(at,'Admin')
    assert not at.exception
    assert any(m.value=='Library recovery' for m in at.subheader)


def test_readiness_for_another_library_is_marked_stale(library_app):
    at,s=library_app
    s.check_readiness=lambda **kw:None
    s.latest_readiness=lambda:{'run_id':'old','checked_at':1795352400,'ok':True,'generation':{'state':'verified'}}
    at.run();navigate(at,'Admin')
    assert any('earlier library' in msg.value for msg in at.warning)
    assert not any('generated answers passed' in msg.value for msg in at.success)


def test_access_only_readiness_cannot_claim_generated_answers_passed(library_app):
    at,s=library_app
    s.check_readiness=lambda **kw:None
    s.latest_readiness=lambda:{'run_id':'first','checked_at':1795352400,'ok':True,
        'generation_requested':False,'generation':{'ok':False,'state':'not_checked'}}
    at.run();navigate(at,'Admin')
    assert not any('generated answers passed' in msg.value for msg in at.success)
    assert any('not_checked' in msg.value for msg in at.warning)


def test_explicit_verified_generation_can_display_success(library_app):
    at,s=library_app
    s.check_readiness=lambda **kw:None
    s.latest_readiness=lambda:{'run_id':'first','checked_at':1795352400,'ok':True,
        'generation_requested':True,'generation':{'ok':True,'state':'verified'}}
    at.run();navigate(at,'Admin')
    assert any('generated answers passed' in msg.value for msg in at.success)
