"""Navigation and repeat-action regressions against the real Streamlit app."""
import sys
from types import SimpleNamespace

import pytest
from streamlit.testing.v1 import AppTest

from amgen_explorer.models import Document, Product, TeachingResponse
from test_app_flows import FakeService, ROOT, click, navigate, source_passages


@pytest.fixture
def app(monkeypatch, tmp_path):
    service = FakeService(tmp_path)
    service.config.validate = lambda **kwargs: []
    service.active_value = {
        'run_id': 'published', 'xml_hash': 'xml-sha',
        'product_ids': ['repatha', 'other'], 'document_ids': ['doc', 'variant', 'other-doc'],
    }
    service.data.products.append(Product('other', 'OTHER', 'other generic', ['other-doc']))
    service.data.documents.extend([
        Document('variant', 'repatha', 'variant.pdf', 'variant-sha', 1),
        Document('other-doc', 'other', 'other.pdf', 'other-sha', 1),
    ])
    def answer(question, product_id, **kwargs):
        service.calls.append(('answer', product_id, question, kwargs))
        document = kwargs.get('document_id') or 'other-doc'
        return TeachingResponse(f'Explanation for {document}', [{
            'document_id': document, 'filename': f'{document}.pdf',
            'page_start': 1, 'page_end': 1, 'text': f'Exact source for {document}',
        }])
    service.answer = answer
    monkeypatch.setitem(sys.modules, 'amgen_explorer.service', SimpleNamespace(ExplorerService=lambda: service))
    at = AppTest.from_file(str(ROOT / 'app.py'), default_timeout=15)
    at.query_params['legacy']='1'
    at.run()
    navigate(at, 'Learn with chat')
    at.selectbox(key='document_id').set_value('doc').run()
    return at, service


def choose_quiz(at):
    next(r for r in at.radio if r.label == 'Learning steps').set_value('Check your understanding').run()


def quiz_answer(at):
    return next(r for r in at.radio if r.label == 'Your answer')


def test_checked_quiz_survives_leaving_the_learning_page(app):
    at, service = app
    choose_quiz(at)
    click(at, 'Create a source-based quiz')
    quiz_answer(at).set_value(0).run()
    click(at, 'Check answer')
    navigate(at, 'My learning')
    assert next(m for m in at.metric if m.label == 'Quizzes checked').value == '1'
    navigate(at, 'Learn with chat')
    at.selectbox(key='document_id').set_value('doc').run()
    choose_quiz(at)
    assert quiz_answer(at).value == 0
    assert any('Correct.' in item.value for item in at.success)
    navigate(at, 'My learning')
    assert next(m for m in at.metric if m.label == 'Quizzes checked').value == '1'
    assert service.calls.count('quiz') == 1


def test_medicine_and_source_switches_isolate_history_citations_and_progress(app):
    at, service = app
    click(at, 'Begin the lesson')
    click(at, 'Mark this lesson understood')
    assert 'Exact source for doc' in source_passages(at)
    at.selectbox(key='document_id').set_value('variant').run()
    assert source_passages(at) == []
    assert not any('Mark this lesson' in b.label for b in at.button)
    at.chat_input[0].set_value('Variant question').run()
    assert source_passages(at) == ['Exact source for variant']
    request = [c for c in service.calls if isinstance(c, tuple) and c[0] == 'answer'][-1]
    assert request[3]['history'] == []
    assert request[3]['document_id'] == 'variant'
    at.selectbox(key='product_id').set_value('other').run()
    assert at.selectbox(key='document_id').value is None
    assert source_passages(at) == []
    at.chat_input[0].set_value('Other medicine question').run()
    assert source_passages(at) == ['Exact source for other-doc']
    request = [c for c in service.calls if isinstance(c, tuple) and c[0] == 'answer'][-1]
    assert request[1] == 'other' and request[3]['history'] == []
    at.selectbox(key='product_id').set_value('repatha').run()
    at.selectbox(key='document_id').set_value('doc').run()
    assert source_passages(at) == ['Exact source for doc']
    assert not any('Mark this lesson' in b.label for b in at.button)
    for _ in range(3):
        at.run()
    assert len([c for c in service.calls if isinstance(c, tuple) and c[0] == 'answer']) == 3
    navigate(at, 'My learning')
    assert next(m for m in at.metric if m.label == 'Lessons understood').value == '1'
    assert next(m for m in at.metric if m.label == 'Questions explored').value == '3'


def test_failed_chat_retains_prior_answer_without_repeating_on_rerun(app):
    at, service = app
    at.chat_input[0].set_value('First question').run()
    def fail(*args, **kwargs):
        service.calls.append('failed-answer')
        raise RuntimeError('SECRET_PROVIDER_RESPONSE')
    service.answer = fail
    at.chat_input[0].set_value('Second question').run()
    assert not at.exception
    assert any('Create explanation failed' in e.value for e in at.error)
    assert 'SECRET_PROVIDER_RESPONSE' not in str(at)
    assert source_passages(at) == ['Exact source for doc']
    for _ in range(3):
        at.run()
    assert service.calls.count('failed-answer') == 1
    assert not any(m.value == 'Second question' for m in at.markdown)
    navigate(at, 'My learning')
    assert next(m for m in at.metric if m.label == 'Questions explored').value == '1'


def test_new_browser_session_has_no_other_session_learning_state(app):
    at, service = app
    click(at, 'Begin the lesson')
    click(at, 'Mark this lesson understood')
    choose_quiz(at)
    click(at, 'Create a source-based quiz')
    quiz_answer(at).set_value(0).run()
    click(at, 'Check answer')
    second = AppTest.from_file(str(ROOT / 'app.py'), default_timeout=15)
    second.query_params['legacy']='1'
    second.run()
    navigate(second, 'My learning')
    assert {m.label: m.value for m in second.metric} == {
        'Lessons understood': '0', 'Quizzes checked': '0', 'Questions explored': '0',
    }
    navigate(second, 'Learn with chat')
    second.selectbox(key='document_id').set_value('doc').run()
    assert source_passages(second) == []
    choose_quiz(second)
    assert not any(r.label == 'Your answer' for r in second.radio)
    navigate(at, 'My learning')
    assert {m.label: m.value for m in at.metric} == {
        'Lessons understood': '1', 'Quizzes checked': '1', 'Questions explored': '1',
    }
    assert service.calls.count('quiz') == 1


def test_demo_checked_answer_survives_back_and_return(app):
    at, service = app
    navigate(at, 'Demo tour')
    for _ in range(4):
        at.button(key='demo_next').click().run()
    at.radio(key='demo_answer').set_value(0).run()
    at.button(key='demo_check').click().run()
    assert any('Correct' in message.value for message in at.success)
    at.button(key='demo_back').click().run()
    at.button(key='demo_next').click().run()
    assert at.radio(key='demo_answer').value == 0
    assert any('Correct' in message.value for message in at.success)
    assert not any('Look again' in message.value for message in at.info)
    assert service.calls == []


def test_quiz_choices_and_checks_remain_separate_across_sources_and_medicines(app):
    at, service = app
    choose_quiz(at)
    click(at, 'Create a source-based quiz')
    quiz_answer(at).set_value(0).run()
    click(at, 'Check answer')
    at.selectbox(key='document_id').set_value('variant').run()
    choose_quiz(at)
    assert not any(r.label == 'Your answer' for r in at.radio)
    click(at, 'Create a source-based quiz')
    quiz_answer(at).set_value(1).run()
    click(at, 'Check answer')
    assert any('Review this answer' in item.value for item in at.info)
    at.selectbox(key='product_id').set_value('other').run()
    choose_quiz(at)
    assert not any(r.label == 'Your answer' for r in at.radio)
    assert not any('Correct.' in item.value for item in at.success)
    at.selectbox(key='product_id').set_value('repatha').run()
    for document, answer, correct in [('doc', 0, True), ('variant', 1, False)]:
        at.selectbox(key='document_id').set_value(document).run()
        choose_quiz(at)
        assert quiz_answer(at).value == answer
        assert any('Correct.' in item.value for item in at.success) is correct
    navigate(at, 'My learning')
    assert next(m for m in at.metric if m.label == 'Quizzes checked').value == '2'
    assert service.calls.count('quiz') == 2


def test_quiz_replacement_clears_old_choice_but_failed_generation_preserves_it(app):
    at, service = app
    choose_quiz(at)
    click(at, 'Create a source-based quiz')
    quiz_answer(at).set_value(0).run()
    click(at, 'Check answer')
    original_quiz = service.quiz
    def fail(*args, **kwargs):
        service.calls.append('failed-quiz')
        raise RuntimeError('SECRET_QUIZ_RESPONSE')
    service.quiz = fail
    click(at, 'Create a source-based quiz')
    assert any('Create quiz failed' in item.value for item in at.error)
    assert 'SECRET_QUIZ_RESPONSE' not in str(at)
    assert quiz_answer(at).value == 0
    assert any('Correct.' in item.value for item in at.success)
    at.run()
    assert service.calls.count('failed-quiz') == 1
    service.quiz = original_quiz
    click(at, 'Create a source-based quiz')
    assert quiz_answer(at).value is None
    assert not any('Correct.' in item.value for item in at.success)
    assert next(b for b in at.button if b.label == 'Check answer').disabled
    at.run()
    assert service.calls.count('quiz') == 2


def test_demo_exit_reentry_restart_and_missing_source_keep_state_honest(app, monkeypatch):
    from amgen_explorer.demo import DemoUnavailable
    from ui import demo
    at, service = app
    navigate(at, 'Demo tour')
    for _ in range(4):
        at.button(key='demo_next').click().run()
    at.radio(key='demo_answer').set_value(0).run()
    at.button(key='demo_check').click().run()
    at.query_params['demo'] = '1'
    at.query_params['keep'] = 'retained'
    at.button(key='demo_exit').click().run()
    assert at.sidebar.radio(key='nav').value == 'Explore medicines'
    assert at.query_params == {'legacy':'1','keep': 'retained'}
    navigate(at, 'Demo tour')
    assert at.radio(key='demo_answer').value == 0
    assert any('Correct' in item.value for item in at.success)
    load_example = demo.load_example
    def unavailable():
        raise DemoUnavailable('Example could not be verified.')
    monkeypatch.setattr(demo, 'load_example', unavailable)
    at.run()
    assert not at.exception
    assert any('could not be verified' in item.value for item in at.warning)
    assert not any(r.key == 'demo_answer' for r in at.radio)
    assert not at.success
    at.button(key='demo_restart_missing').click().run()
    monkeypatch.setattr(demo, 'load_example', load_example)
    at.run()
    assert at.button(key='demo_back').disabled
    for _ in range(4):
        at.button(key='demo_next').click().run()
    assert at.radio(key='demo_answer').value is None
    assert not at.success
    assert at.button(key='demo_check').disabled
    assert service.calls == []
