"""Independent condition acceptance grading; no provider or ranking fixtures."""
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from amgen_explorer.models import Corpus, Document, Product, SourceBlock
from amgen_explorer.search import SearchResults

ROOT = Path(__file__).resolve().parents[1]


def evaluator():
    spec = importlib.util.find_spec('scripts.check_condition_search')
    assert spec is not None, 'The independent condition evaluation runner must exist'
    return __import__('scripts.check_condition_search', fromlist=['validate_fixture'])


@pytest.fixture
def source():
    quote = 'MED is indicated for migraine prevention in adults.'
    digest = hashlib.sha256(quote.encode()).hexdigest()
    span = {'page': 1, 'block_id': 'archive', 'start': 0, 'end': len(quote)}
    block = SourceBlock('indication', 'medicine', 'label', 'b'*64, quote, 's1',
                        '1 INDICATIONS AND USAGE', 'fullPrescribingInformation',
                        1, 1, digest, [span])
    archive = SourceBlock('archive', 'medicine', 'label', 'b'*64, quote, 'page1',
                          'Page 1', 'sourcePageArchive', 1, 1, digest, [span])
    corpus = Corpus(Path('fixture.xml'), 'a'*64, [Product('medicine', 'MED')],
                    [Document('label', 'medicine', 'label.pdf', 'b'*64, 1)], [block, archive])
    case = {'id': 'migraine', 'query': 'What can treat migraine?', 'query_variants': ['migraine treatment'],
            'expected_treatment_product_ids': ['medicine'],
            'supporting_evidence_refs': ['source'], 'negative_or_qualifying_evidence_refs': [],
            'expected_leading_evidence': {'medicine': ['source']}}
    evidence = {'product_id': 'medicine', 'document_id': 'label', 'pdf_filename': 'label.pdf',
                'pdf_sha256': 'b'*64, 'block_id': 'indication', 'block_sha256': digest,
                'quote_exact': quote, 'source_spans': [span], 'physical_pdf_page': 1,
                'section_id': 's1', 'section_title': block.section_title,
                'section_kind': block.section_kind}
    fixture = {'schema_version': 1, 'corpus': {'xml_sha256': 'a'*64},
               'source_documents': [{'document_id': 'label', 'product_id': 'medicine',
                                     'filename': 'label.pdf', 'sha256': 'b'*64, 'page_count': 1}],
               'evidence': {'source': evidence}, 'acceptance_cases': [case]}
    return corpus, fixture, case


def hit(product='medicine', block='indication', document='label'):
    return {'id': 'chunk-'+block, 'product_id': product, 'document_id': document,
            'xml_hash': 'a'*64, 'text': 'MED is indicated for migraine prevention in adults.',
            'metadata': {'product_id': product, 'document_id': document,
                         'document_sha256': 'b'*64, 'block_ids': [block],
                         'page_start': 1, 'page_end': 1,
                         'source_spans': [{'page': 1, 'archive_block_id': 'archive',
                                           'source_block_id': block, 'start': 0, 'end': 50}]}}


def test_wrong_product_tail_and_missing_expected_are_failures(source):
    _, fixture, case = source
    score = evaluator().score_case
    good = score(case, [hit()], fixture['evidence'])
    noisy = score(case, [hit(), hit('unrelated', 'other', 'another')], fixture['evidence'])
    missing = score(case, [], fixture['evidence'])
    assert good['passed']
    assert not noisy['passed'] and noisy['unexpected_product_ids'] == ['unrelated']
    assert not missing['passed'] and missing['missing_product_ids'] == ['medicine']


def test_first_evidence_per_product_must_be_audited_indication(source):
    _, fixture, case = source
    result = evaluator().score_case(case, [hit(block='adverse'), hit()], fixture['evidence'])
    assert not result['passed']
    assert result['leading_evidence_failures'] == ['medicine']
    # A later non-indication passage for the same medicine is outside this metric.
    limited = evaluator().score_case(case, [hit(), hit(block='study')], fixture['evidence'])
    assert limited['passed']


def test_negative_cases_require_empty_hits_and_live_disallows_degradation(source):
    _, fixture, case = source
    negative = {**case, 'expected_treatment_product_ids': [], 'expected_leading_evidence': {}}
    score = evaluator().score_case
    assert score(negative, [], fixture['evidence'])['passed']
    assert not score(negative, [hit()], fixture['evidence'])['passed']
    assert not score(negative, [], fixture['evidence'], live=True, degraded=True)['passed']
    assert score(negative, [], fixture['evidence'], live=False, degraded=True)['passed']


@pytest.mark.parametrize('mutation,reason', [
    ('xml', 'XML'), ('pdf', 'PDF'), ('quote', 'quote'), ('block_hash', 'hash'), ('span', 'span')])
def test_invalid_frozen_source_evidence_fails_before_search(source, mutation, reason):
    corpus, fixture, _ = source
    evaluator().validate_fixture(fixture, corpus)
    bad = deepcopy(fixture)
    if mutation == 'xml': bad['corpus']['xml_sha256'] = 'c'*64
    elif mutation == 'pdf': bad['source_documents'][0]['sha256'] = 'c'*64
    elif mutation == 'quote': bad['evidence']['source']['quote_exact'] = 'A plausible but absent quote.'
    elif mutation == 'block_hash': bad['evidence']['source']['block_sha256'] = 'c'*64
    else: bad['evidence']['source']['source_spans'][0]['end'] = 3
    with pytest.raises(ValueError, match=reason):
        evaluator().validate_fixture(bad, corpus)


def test_committed_fixture_validates_against_canonical_sources():
    from amgen_explorer.xml_store import load_corpus
    path = ROOT/'evals/condition-search.json'
    assert path.is_file(), 'Audited expectations must be committed independently of runtime ranking'
    fixture = json.loads(path.read_text())
    evaluator().validate_fixture(fixture, load_corpus(ROOT/'XML/AmgenProducts.xml'))
    assert len(fixture['acceptance_cases']) == 12
    assert len(fixture['evidence']) == 31
    assert any('What can treat migraine?' in [c['query'], *c['query_variants']]
               for c in fixture['acceptance_cases'])


def test_runner_uses_unfiltered_local_search_and_resolves_each_pdf_once(source, tmp_path, monkeypatch):
    corpus, fixture, _ = source
    module = evaluator()
    run = {'run_id': 'run', 'xml_hash': corpus.xml_hash, 'status': 'verified', 'namespace': 'ns'}
    calls = []; resolved = []
    def search(query, actual_run, config, actual_corpus, **kwargs):
        calls.append((query, kwargs))
        assert actual_run == run and actual_corpus is corpus
        return SearchResults(query, 'run', 'ns', corpus.xml_hash, hits=[hit(), hit()])
    def source_pdf(document_id, xml_hash):
        resolved.append((document_id, xml_hash))
        return b'pdf bytes are hash-checked by ExplorerService.source_pdf'
    service = SimpleNamespace(config=SimpleNamespace(settings={'search': {'result_limit': 20}}),
                              _pinned_corpus=lambda _: corpus, source_pdf=source_pdf)
    monkeypatch.setattr(module, 'search_local', search)
    report = module.evaluate_fixture(service, run, fixture)
    assert report['failed_query_count'] == 0 and report['query_count'] == 2
    assert len(calls) == 2 and all(kwargs == {'limit': 20} for _, kwargs in calls)
    assert resolved == [('label', corpus.xml_hash)]
    assert report['resolved_citation_document_count'] == 1


def test_unresolved_pdf_and_wrong_citation_identity_fail(source, monkeypatch):
    corpus, fixture, _ = source
    module = evaluator()
    run = {'run_id': 'run', 'xml_hash': corpus.xml_hash, 'status': 'verified', 'namespace': 'ns'}
    bad = hit(); bad['metadata']['document_sha256'] = 'c'*64
    def unavailable(*args): raise ValueError('Do not expose provider paths or secrets')
    service = SimpleNamespace(config=SimpleNamespace(settings={}), _pinned_corpus=lambda _: corpus,
                              source_pdf=unavailable)
    monkeypatch.setattr(module, 'search_local', lambda query, *a, **k:
                        SearchResults(query, 'run', 'ns', corpus.xml_hash, hits=[hit(), bad]))
    report = module.evaluate_fixture(service, run, fixture)
    assert report['failed_query_count'] == 2
    assert all(r['citation_failure_count'] == 2 for r in report['results'])
    assert 'Do not expose' not in json.dumps(report)


def test_live_runner_uses_explicit_service_query_without_expected_filters(source):
    corpus, fixture, _ = source
    module = evaluator()
    run = {'run_id': 'run', 'xml_hash': corpus.xml_hash, 'status': 'verified', 'namespace': 'ns'}
    calls = []
    def search(query, **kwargs):
        calls.append(kwargs)
        return SearchResults(query, 'run', 'ns', corpus.xml_hash, hits=[hit()], degraded=True)
    service = SimpleNamespace(config=SimpleNamespace(settings={}), _pinned_corpus=lambda _: corpus,
                              source_pdf=lambda *a: b'pdf', search_library=search)
    report = module.evaluate_fixture(service, run, fixture, live=True)
    assert report['failed_query_count'] == 2
    assert calls == [{'run_id': 'run', 'limit': 20}]*2
    assert all('degraded_live_search' in r['failures'] for r in report['results'])


@pytest.mark.parametrize('returned,expected_status', [([hit()], 0), ([], 1)])
def test_cli_exit_status_and_ignored_report_follow_actual_grades(source, tmp_path, monkeypatch, capsys,
                                                                returned, expected_status):
    corpus, fixture, _ = source
    module = evaluator()
    config = SimpleNamespace(root=tmp_path, settings={}, path=lambda _: tmp_path/'active.json')
    run = {'run_id': 'run', 'xml_hash': corpus.xml_hash, 'status': 'verified', 'namespace': 'ns'}
    (tmp_path/'active.json').write_text(json.dumps(run))
    fixture_path = tmp_path/'fixture.json'; fixture_path.write_text(json.dumps(fixture))
    service = SimpleNamespace(config=config, _pinned_corpus=lambda _: corpus, source_pdf=lambda *a: b'pdf')
    monkeypatch.setattr(module, 'load_config', lambda _: config)
    monkeypatch.setattr(module, 'ExplorerService', lambda _: service)
    monkeypatch.setattr(module, 'search_local', lambda query, *a, **k:
                        SearchResults(query, 'run', 'ns', corpus.xml_hash, hits=returned))
    output = tmp_path/'output/condition-search/report.json'
    assert module.main(['--fixture', str(fixture_path), '--output', str(output)]) == expected_status
    report = json.loads(output.read_text())
    assert report == json.loads(capsys.readouterr().out)
    assert report['failed_query_count'] == 2*expected_status
    assert report['mode'] == 'local_read_only' and report['provider_calls_requested'] == 0


def test_cli_refuses_to_overwrite_nonignored_paths_before_search(tmp_path, monkeypatch, capsys):
    module = evaluator()
    monkeypatch.setattr(module, 'load_config', lambda _: SimpleNamespace(root=tmp_path))
    target = tmp_path/'evals/untouched.json'
    target.parent.mkdir(); target.write_text('original')
    assert module.main(['--output', str(target)]) == 1
    assert target.read_text() == 'original'
    assert 'before grading' in capsys.readouterr().err


@pytest.fixture
def paired_source():
    evidence = {}
    hits = []
    for ref, quote, offset in [('parent', 'MED is indicated for the treatment of:\n', 10),
                               ('child', '1.3 Diabetic Macular Edema (DME)\n', 100)]:
        evidence[ref] = {'product_id': 'medicine', 'document_id': 'label', 'pdf_sha256': 'b'*64,
                         'block_id': ref, 'quote_exact': quote,
                         'source_spans': [{'block_id': 'archive', 'page': 1,
                                           'start': offset, 'end': offset+len(quote)}]}
        item = hit(block=ref)
        item['text'] = quote
        item['metadata']['xml_hash'] = 'a'*64
        item['metadata']['source_spans'] = [{'source_block_id': ref, 'archive_block_id': 'archive',
                                             'page': 1, 'start': offset, 'end': offset+len(quote),
                                             'block_start': 0, 'block_end': len(quote)}]
        hits.append(item)
    case = {'expected_treatment_product_ids': ['medicine'],
            'expected_leading_evidence': {'medicine': ['child']},
            'required_leading_evidence_pairs': {'medicine': {
                'xml_sha256': 'a'*64, 'evidence_refs': ['parent', 'child']}}}
    return case, hits, evidence


def test_contiguous_exact_parent_and_child_form_independent_leading_proof(paired_source):
    case, hits, evidence = paired_source
    result = evaluator().score_case(case, hits, evidence)
    assert result['passed']
    assert result['leading_source_block_ids']['medicine'] == ['parent', 'child']


@pytest.mark.parametrize('mutation', ['parent_only', 'child_only', 'nonadjacent', 'other_document',
                                      'other_product', 'other_xml', 'other_pdf', 'wrong_quote',
                                      'wrong_span', 'wrong_block', 'wrong_archive'])
def test_incomplete_or_mismatched_pairs_fail_even_with_claimed_matcher_group(paired_source, mutation):
    case, hits, evidence = paired_source
    hits = deepcopy(hits)
    if mutation == 'parent_only': hits = hits[:1]
    elif mutation == 'child_only': hits = hits[1:]
    elif mutation == 'nonadjacent': hits.insert(1, hit(block='unrelated'))
    elif mutation == 'other_document': hits[1]['metadata']['document_id'] = 'other-label'
    elif mutation == 'other_product': hits[1]['product_id'] = 'other-medicine'
    elif mutation == 'other_xml': hits[1]['xml_hash'] = 'c'*64
    elif mutation == 'other_pdf': hits[1]['metadata']['document_sha256'] = 'c'*64
    elif mutation == 'wrong_quote': hits[1]['text'] = 'A different condition'
    elif mutation == 'wrong_span': hits[1]['metadata']['source_spans'][0]['end'] -= 1
    elif mutation == 'wrong_block': hits[1]['metadata']['source_spans'][0]['source_block_id'] = 'other'
    else: hits[1]['metadata']['source_spans'][0]['archive_block_id'] = 'other-page'
    # Runtime assertions cannot substitute for the fixture's literal source proof.
    for item in hits: item['treatment_evidence_groups'] = ['claims-the-pair-is-valid']
    result = evaluator().score_case(case, hits, evidence)
    assert not result['passed']
    assert result['leading_evidence_failures'] == ['medicine']
