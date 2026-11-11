"""Versioned source eligibility; extraction verification is never human approval."""
from __future__ import annotations
from dataclasses import dataclass, field, replace
import hashlib
import json
from pathlib import Path
import re
from .models import Corpus, SourceBlock
from .review import digest, block_scope
from .xml_store import validate_source_files

MANUAL_POLICY = 'manual_review_v1'
BULK_POLICY = 'bulk_source_verified_v1'
SCHEMA_VERSION = 2


def policy_for(value):
    policy = value.get('eligibility_policy', MANUAL_POLICY) if isinstance(value, dict) else getattr(value, 'eligibility_policy', MANUAL_POLICY)
    if policy not in {MANUAL_POLICY, BULK_POLICY}:
        raise ValueError('Unsupported source eligibility policy.')
    return policy


def validate_record_policy(record, policy, fingerprint=''):
    """Shared fail-closed admission gate for records and teaching passages."""
    policy_for({'eligibility_policy':policy})
    if policy == MANUAL_POLICY:
        if policy_for(record) != MANUAL_POLICY or record.get('review_state') != 'accepted':
            raise ValueError('Only explicitly accepted reviewed chunks can be loaded or used.')
    else:
        actual = record.get('eligibility_fingerprint', '')
        if (record.get('eligibility_policy') != BULK_POLICY or record.get('source_verified') is not True
                or record.get('human_review_status') != 'not_assessed'
                or record.get('review_state') == 'accepted'
                or not isinstance(actual, str) or not re.fullmatch('[a-f0-9]{64}', actual)
                or (fingerprint and actual != fingerprint)):
            raise ValueError('A bulk record failed source eligibility policy validation.')


@dataclass
class EligibilityReport:
    eligible_span_units: list[SourceBlock]
    limitations: list[dict] = field(default_factory=list)
    expected_document_ids: list[str] = field(default_factory=list)
    expected_product_ids: list[str] = field(default_factory=list)
    coverage: dict = field(default_factory=dict)
    fingerprint: str = ''
    policy: str = MANUAL_POLICY
    excluded: list[dict] = field(default_factory=list)


def _remaining(start, end, occupied):
    cursor = start
    for lo, hi in sorted(occupied):
        if hi <= cursor: continue
        if lo >= end: break
        if lo > cursor: yield cursor, min(lo, end)
        cursor = max(cursor, hi)
        if cursor >= end: return
    if cursor < end: yield cursor, end


def _merge(intervals):
    merged = []
    for lo, hi in sorted(intervals):
        if merged and lo <= merged[-1][1]: merged[-1][1] = max(merged[-1][1],hi)
        else: merged.append([lo,hi])
    return merged


def coverage_for(corpus, spans):
    """Count unique physical-source character intervals, excluding blank pages."""
    expected = {}
    blank_pages = []
    for block in corpus.blocks:
        if block.section_kind != 'sourcePageArchive': continue
        key = (block.document_sha256, block.page_start)
        if block.text.strip(): expected[key] = len(block.text)
        else: blank_pages.append({'document_id':block.document_id, 'page':block.page_start, 'reason':'blank_or_image_only_ocr_unavailable'})
    intervals = {}
    for document_hash, span in spans:
        key = (document_hash,span['page'])
        lo, hi = span['start'],span['end']
        if key not in expected or not 0 <= lo <= hi <= expected[key]:
            raise ValueError('Coverage interval is outside the archived source.')
        intervals.setdefault(key,[]).append((lo,hi))
    missing = []
    covered = 0
    for (document_hash,page), end in expected.items():
        occupied = _merge(intervals.get((document_hash,page), []))
        covered += sum(hi-lo for lo,hi in occupied)
        missing += [{'document_sha256':document_hash,'page':page,'start':lo,'end':hi}
                    for lo,hi in _remaining(0,end,occupied)]
    return {'expected_characters':sum(expected.values()), 'covered_characters':covered,
            'expected_pages':len(expected), 'blank_pages':blank_pages,
            'missing_intervals':missing, 'complete':not missing}


def assess_corpus(corpus: Corpus, source_dir: Path, policy: str, reviews=None) -> EligibilityReport:
    policy_for({'eligibility_policy':policy})
    documents = {d.id:d for d in corpus.documents}
    products = {p.id:p for p in corpus.products}
    report = EligibilityReport([], expected_document_ids=sorted(documents), expected_product_ids=sorted(products), policy=policy)
    if policy == MANUAL_POLICY:
        if reviews is None: raise ValueError('Legacy manual policy requires the review store.')
        statuses, review_hash = reviews.snapshot(corpus)
        has_sections = {b.document_id for b in corpus.blocks if b.section_kind != 'sourcePageArchive'}
        for block in corpus.blocks:
            if statuses[block.id] != 'accepted': reason = 'review_'+statuses[block.id]
            elif not block.text.strip(): reason = 'no_usable_text'
            elif any(w.startswith(('unresolved_','no_usable_text')) for w in block.warnings): reason = 'unresolved_extraction_structure'
            elif block.section_kind == 'sourcePageArchive' and block.document_id in has_sections: reason = 'duplicate_page_archive_use_section_passages'
            else:
                report.eligible_span_units.append(block)
                continue
            report.excluded.append({'block_id':block.id,'reason':reason})
        report.fingerprint = review_hash
        return report
    if source_dir is None: raise ValueError('Bulk eligibility requires the configured source directory.')
    validate_source_files(corpus, Path(source_dir))
    if len(documents) != len(corpus.documents) or len(products) != len(corpus.products):
        raise ValueError('Duplicate document or product identity.')
    if {d.product_id for d in corpus.documents} != set(products):
        raise ValueError('The expected product/document inventory is incomplete.')
    archives = {(b.document_id,b.page_start):b for b in corpus.blocks if b.section_kind == 'sourcePageArchive'}
    for block in corpus.blocks:
        doc = documents.get(block.document_id)
        if (doc is None or block.product_id not in products or doc.product_id != block.product_id
                or doc.sha256 != block.document_sha256 or hashlib.sha256(block.text.encode()).hexdigest() != block.content_hash):
            raise ValueError('A source block failed content hash or document/product ownership validation.')
        if not block.spans: raise ValueError('A source block has no exact page spans.')
        pieces=[]
        for span in block.spans:
            page,lo,hi = span.get('page'),span.get('start'),span.get('end')
            archive = archives.get((block.document_id,page))
            if (archive is None or type(lo) is not int or type(hi) is not int or not 0 <= lo <= hi <= len(archive.text)
                    or span.get('block_id') != archive.id or not block.page_start <= page <= block.page_end):
                raise ValueError('A source block failed exact archived span validation.')
            pieces.append(archive.text[lo:hi])
        if ''.join(pieces) != block.text:
            raise ValueError('A source block text differs from its exact archived spans.')
    occupied = {}
    # Prefer section passages, but fill every uncovered interval on every page.
    for block in sorted(corpus.blocks, key=lambda b:b.section_kind == 'sourcePageArchive'):
        if not block.text.strip(): continue
        cursor = 0
        for span in block.spans:
            key = (block.document_sha256,span['page'])
            used = occupied.setdefault(key,[])
            for lo,hi in list(_remaining(span['start'],span['end'],used)):
                relative = cursor+lo-span['start']
                text = block.text[relative:relative+hi-lo]
                unit = replace(block, text=text, content_hash=hashlib.sha256(text.encode()).hexdigest(),
                               spans=[{**span,'start':lo,'end':hi}], page_start=span['page'], page_end=span['page'],
                               source_offset=relative)
                report.eligible_span_units.append(unit)
                used.append((lo,hi))
                if block.warnings:
                    report.limitations.append({'block_id':block.id,'document_id':block.document_id,'warnings':list(block.warnings)})
            cursor += span['end']-span['start']
    report.coverage = coverage_for(corpus, [(b.document_sha256,s) for b in report.eligible_span_units for s in b.spans])
    report.fingerprint = digest({'schema_version':SCHEMA_VERSION,'policy':policy,'xml_hash':corpus.xml_hash,
                                 'documents':[vars(d) for d in corpus.documents],
                                 'products':[vars(p) for p in corpus.products],
                                 'units':[block_scope(b) | {'source_offset':b.source_offset} for b in report.eligible_span_units],
                                 'coverage':report.coverage})
    return report


def validate_record_sources(records, corpus, manifest, text_field='chunk_text'):
    """Re-prove bulk provenance and complete coverage from the pinned XML.

    This final publication gate protects direct indexing/rollback callers too;
    a source-verified marker alone is insufficient evidence of exact text.
    """
    documents = {d.id:d for d in corpus.documents}
    blocks = {b.id:b for b in corpus.blocks}
    covered=[]
    try:
        if (manifest['xml_hash'] != corpus.xml_hash
                or manifest['expected_document_ids'] != sorted(documents)
                or manifest['expected_product_ids'] != sorted(p.id for p in corpus.products)):
            raise ValueError()
        for record in records:
            validate_record_policy(record, BULK_POLICY, manifest['eligibility_fingerprint'])
            doc = documents[record['document_id']]
            if (doc.product_id != record['product_id'] or doc.sha256 != record['document_sha256']
                    or record['xml_hash'] != corpus.xml_hash or doc.filename != record['filename']):
                raise ValueError()
            spans = json.loads(record['source_spans'])
            if not isinstance(spans,list) or not spans:
                raise ValueError()
            snippets=[]; parents=[]; limitations=[]
            for span in spans:
                archive = blocks[span['archive_block_id']]
                parent = blocks[span['source_block_id']]
                page,lo,hi,pa,pb = (span[k] for k in ('page','start','end','block_start','block_end'))
                if (any(type(v) is not int for v in (page,lo,hi,pa,pb))
                        or archive.section_kind != 'sourcePageArchive' or archive.page_start != page
                        or not 0 <= lo < hi <= len(archive.text) or not 0 <= pa < pb <= len(parent.text)
                        or not 1 <= page <= doc.page_count):
                    raise ValueError()
                for block in (archive,parent):
                    if (block.document_id != doc.id or block.document_sha256 != doc.sha256
                            or block.product_id != doc.product_id):
                        raise ValueError()
                # Verify both parent offsets and archive offsets against the
                # original parent mapping, rather than only matching text.
                offset=0; matched=False
                for source in parent.spans:
                    if (source['page'] == page and source['block_id'] == archive.id
                            and source['start'] <= lo < hi <= source['end']
                            and pa == offset+lo-source['start'] and pb == offset+hi-source['start']):
                        matched=True
                    offset += source['end']-source['start']
                if not matched or archive.text[lo:hi] != parent.text[pa:pb]:
                    raise ValueError()
                for field in ('section_id','section_title','section_kind','parser_version'):
                    if record[field] != getattr(parent,field): raise ValueError()
                snippets.append(archive.text[lo:hi]); parents.append(parent.id)
                limitations.extend(parent.warnings)
                covered.append((doc.sha256,span))
            if (record['source_text'] != ''.join(snippets)
                    or record['block_ids'] != list(dict.fromkeys(parents))
                    or record['extraction_limitations'] != list(dict.fromkeys(limitations))
                    or record['page_start'] != min(s['page'] for s in spans)
                    or record['page_end'] != max(s['page'] for s in spans)
                    or not record[text_field].endswith(record['source_text'])
                    or hashlib.sha256(record[text_field].encode()).hexdigest() != record['content_hash']):
                raise ValueError()
        actual = coverage_for(corpus,covered)
        if not actual['complete'] or actual != manifest['coverage']:
            raise ValueError('Bulk coverage differs from the exact archived source intervals.')
    except (KeyError, TypeError, ValueError, AttributeError, IndexError):
        raise ValueError('Bulk source text, citation spans, limitations or coverage failed pinned XML verification.') from None
    return actual
