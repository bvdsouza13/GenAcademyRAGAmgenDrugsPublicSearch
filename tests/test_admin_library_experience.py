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
    assert next(m for m in at.metric if m.label=='Verified Pinecone records').value=='3'


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
