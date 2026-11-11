"""Synthetic source/chunk regressions: no live corpus or provider dependencies."""
from collections import Counter
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import random

import pymupdf
import pytest

from amgen_explorer.chunking import ChunkConfig, prepare_chunks
from amgen_explorer.extraction import CorpusBuildError, build_corpus
from amgen_explorer.models import Corpus, Document, Product, SourceBlock
from amgen_explorer.review import ReviewStore
from amgen_explorer.xml_store import load_corpus, validate_source_files


def _pdf(path, pages):
    with pymupdf.open() as document:
        for text in pages:
            document.new_page().insert_text((50, 50), text)
        document.save(path)


def _accepted(corpus, tmp_path):
    reviews = ReviewStore(tmp_path / 'reviews.sqlite')
    for block in corpus.blocks:
        reviews.record(block, 'accepted', 'synthetic regression fixture')
    return reviews


def _synthetic_corpus(texts):
    blocks = [SourceBlock(
        f'block-{i}', 'product-test', 'doc-test', 'a' * 64, text,
        f'section-{i // 2}', 'Synthetic section', 'fullPrescribingInformation',
        i + 1, i + 1, hashlib.sha256(text.encode()).hexdigest(),
        [{'page': i + 1, 'block_id': f'archive-{i}', 'start': 17, 'end': 17 + len(text)}],
    ) for i, text in enumerate(texts)]
    return Corpus(Path('synthetic.xml'), 'b' * 64, [Product('product-test', 'TEST')],
                  [Document('doc-test', 'product-test', 'test.pdf', 'a' * 64, len(texts))], blocks)


def test_full_pi_without_numbered_headings_retains_complete_archive_for_chunking(tmp_path):
    sources = tmp_path / 'Documents'
    sources.mkdir()
    _pdf(sources / 'sample.pdf', [
        'Highlights text.\nFULL PRESCRIBING INFORMATION\n'
        'Unnumbered source statement with an essential condition.'])
    output = tmp_path / 'corpus.xml'
    build_corpus(sources, output)
    corpus = load_corpus(output)
    plan = prepare_chunks(corpus, _accepted(corpus, tmp_path), ChunkConfig())
    assert any('essential condition' in chunk.metadata['source_text'] for chunk in plan.chunks)
    assert not any(item['reason'] == 'duplicate_page_archive_use_section_passages' for item in plan.excluded)


def test_pdf_replaced_while_extracting_cannot_bind_old_text_to_new_hash(tmp_path, monkeypatch):
    import amgen_explorer.extraction as extraction

    sources = tmp_path / 'Documents'
    sources.mkdir()
    source = sources / 'sample.pdf'
    _pdf(source, ['Old source text.'])
    replacement = tmp_path / 'replacement.pdf'
    _pdf(replacement, ['New source text.'])
    output = tmp_path / 'corpus.xml'
    build_corpus(sources, output)
    previous = output.read_bytes()
    previous_report = output.with_suffix('.report.json').read_bytes()
    original_open = pymupdf.open

    class ReplaceOnClose:
        def __init__(self, document):
            self.document = document

        def __enter__(self):
            return self.document

        def __exit__(self, *args):
            self.document.close()
            source.write_bytes(replacement.read_bytes())

    monkeypatch.setattr(extraction.pymupdf, 'open', lambda *a, **kw: ReplaceOnClose(original_open(*a, **kw)))
    with pytest.raises(CorpusBuildError, match='Source changed'):
        build_corpus(sources, output)
    assert output.read_bytes() == previous
    assert output.with_suffix('.report.json').read_bytes() == previous_report


@pytest.mark.parametrize('seed', [2, 17, 91])
@pytest.mark.parametrize('overlap', [0, 80, 200])
def test_seeded_unicode_sentence_boundaries_preserve_exact_coverage(tmp_path, seed, overlap):
    rng = random.Random(seed)
    words = ['café', 'e\u0301', '患者', '🧬', 'dose\u00a0units', 'αβ', 'qualifier']
    endings = ['. ', '!\t', '?\n', '.\u201d\u2003', '!\u2019\n\n', '?)\u00a0']
    texts = ['\t' + ''.join(' '.join(rng.choices(words, k=rng.randrange(2, 10))) + rng.choice(endings)
                           for _ in range(35)) + '  \n' for _ in range(4)]
    corpus = _synthetic_corpus(texts)
    reviews = _accepted(corpus, tmp_path)
    config = ChunkConfig(target_tokens=300, overlap_tokens=overlap)
    plan = prepare_chunks(corpus, reviews, config)
    assert plan == prepare_chunks(corpus, reviews, config)
    assert not plan.excluded
    seen = {block.id: Counter() for block in corpus.blocks}
    by_id = {block.id: block for block in corpus.blocks}
    for chunk in plan.chunks:
        assert len(chunk.text.encode('utf-8')) + 8 <= 2048
        spans = json.loads(chunk.metadata['source_spans'])
        assert {by_id[span['source_block_id']].section_id for span in spans} == {chunk.metadata['section_id']}
        fragments = []
        previous_id = None
        for span in spans:
            block = by_id[span['source_block_id']]
            source = 'padding is exact!' + block.text
            fragment = source[span['start']:span['end']]
            assert fragment == block.text[span['block_start']:span['block_end']]
            if previous_id is not None and previous_id != block.id:
                fragments.append('\n')
            fragments.append(fragment)
            previous_id = block.id
            seen[block.id].update(range(span['block_start'], span['block_end']))
        assert ''.join(fragments) == chunk.metadata['source_text']
    for block in corpus.blocks:
        assert set(seen[block.id]) == set(range(len(block.text)))
        if overlap == 0:
            assert set(seen[block.id].values()) == {1}


@pytest.mark.parametrize('delta', [0, 1])
def test_unicode_prefix_and_sentence_enforce_exact_byte_boundary(tmp_path, delta):
    corpus = _synthetic_corpus(['x'])
    corpus.products[0].name = '🧬'
    config = ChunkConfig(prefix_template='{product_name}{section_title}', overlap_tokens=0)
    prefix = config.prefix_template.format(product_name=corpus.products[0].name, section_title=corpus.blocks[0].section_title)
    available = 2048 - 8 - len(prefix.encode())
    text = '界' * (available // 3) + 'a' * (available % 3 + delta)
    corpus.blocks[0] = replace(corpus.blocks[0], text=text, content_hash=hashlib.sha256(text.encode()).hexdigest(),
                               spans=[{'page': 1, 'block_id': 'archive-0', 'start': 17, 'end': 17 + len(text)}])
    plan = prepare_chunks(corpus, _accepted(corpus, tmp_path), config)
    if delta == 0:
        assert len(plan.chunks) == 1
        assert plan.chunks[0].token_count == 2048
        assert plan.chunks[0].metadata['source_text'] == text
    else:
        assert not plan.chunks
        assert sum(item['character_count'] for item in plan.excluded) == len(text)
        assert {item['reason'] for item in plan.excluded} == {'indivisible_unit_exceeds_model_cap'}


def test_mixed_pdf_names_and_blank_pages_roundtrip_without_state_changes(tmp_path):
    sources = tmp_path / 'Documents'
    sources.mkdir()
    names = ['Alpha label.PDF', 'βeta_label.PdF', 'gamma.v2.pdf']
    for name in names:
        _pdf(sources / name, ['Roundtrip text < & >.', '', 'A third page.'])
    (sources / 'ignored.txt').write_text('Not a source PDF.')
    output = tmp_path / 'corpus.xml'
    build_corpus(sources, output)
    corpus = load_corpus(output)
    before = output.read_bytes()
    hashes = {name: hashlib.sha256((sources / name).read_bytes()).hexdigest() for name in names}
    assert {doc.filename for doc in corpus.documents} == set(names)
    assert validate_source_files(corpus, sources)['pageTextRoundTripsVerified'] == 9
    assert output.read_bytes() == before
    assert hashes == {name: hashlib.sha256((sources / name).read_bytes()).hexdigest() for name in names}


def test_colliding_sanitized_filenames_preserve_last_build_and_report(tmp_path):
    sources = tmp_path / 'Documents'
    sources.mkdir()
    _pdf(sources / 'a_b.pdf', ['Initial source.'])
    output = tmp_path / 'corpus.xml'
    build_corpus(sources, output)
    before = output.read_bytes()
    report_before = output.with_suffix('.report.json').read_bytes()
    _pdf(sources / 'a-b.PDF', ['Distinct source with colliding XML ID.'])
    with pytest.raises(CorpusBuildError, match='duplicate XML IDs'):
        build_corpus(sources, output)
    assert output.read_bytes() == before
    assert output.with_suffix('.report.json').read_bytes() == report_before
