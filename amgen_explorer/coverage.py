"""Visible native-text page coverage, separate from immutable record coverage."""
from .models import Corpus

COVERAGE_POLICY_VERSION = 'native-page-coverage-v1'


def coverage_summary(corpus: Corpus) -> dict:
    """Report physical pages; no text does not prove a page is unreadable.

    Counts retain duplicate supplied documents, unlike source-character coverage
    which deduplicates identical physical PDF bytes. No provider or OCR is used.
    """
    archives = {(b.document_id,b.page_start): b for b in corpus.blocks if b.section_kind == 'sourcePageArchive'}
    page_reasons = {}
    for block in corpus.blocks:
        for span in block.spans:
            page_reasons.setdefault((block.document_id,span['page']),set()).update(
                w for w in block.warnings if w.startswith('unresolved_'))
    limitations = []; documents = []; total = searchable = characters = 0
    for document in corpus.documents:
        doc_text = doc_chars = 0
        for page in range(1, document.page_count + 1):
            block = archives.get((document.id,page))
            reasons = []
            if block is None:
                reasons.append('missing_page_archive')
            elif block.text.strip():
                doc_text += 1; doc_chars += len(block.text)
                reasons.extend(page_reasons.get((document.id,page),set()))
            else:
                reasons.append('blank_or_image_only_ocr_unavailable')
            if reasons:
                limitations.append({'document_id':document.id,'page':page,'reasons':sorted(set(reasons))})
        documents.append({'document_id':document.id,'total_pages':document.page_count,
                          'searchable_text_pages':doc_text,'no_text_pages':document.page_count-doc_text,
                          'readable_characters':doc_chars})
        total += document.page_count; searchable += doc_text; characters += doc_chars
    return {'policy_version':COVERAGE_POLICY_VERSION,'total_pages':total,
            'searchable_text_pages':searchable,'no_text_pages':total-searchable,
            'readable_characters':characters,'limitations':limitations,'documents':documents}
