"""Deterministic section chunks with explicit source coverage and safe byte cap.

The default counter is a conservative UTF-8 byte upper bound, not an exact
model token count. Every embedded string also passes bytes+8 <=2048, including
prefix. Legacy manual plans retain indivisible sentences/tables. Bulk plans
split oversized units at Unicode character boundaries with exact continuation
metadata, preserving every archived interval without provider truncation.
"""
from __future__ import annotations
from dataclasses import dataclass, asdict
import hashlib
import json
from pathlib import Path
import re
from string import Formatter
from .models import Chunk, ChunkPlan
from .review import digest, canonical
from .eligibility import BULK_POLICY, MANUAL_POLICY, SCHEMA_VERSION, assess_corpus, coverage_for, policy_for


@dataclass(frozen=True)
class ChunkConfig:
    target_tokens: int = 600
    overlap_tokens: int = 80
    prefix_template: str = '{product_name} — {section_title}\n'
    strategy: str = 'section_aware'
    tokenizer: str = 'utf8-byte-upper-bound'
    tokenizer_version: str = '1'
    prefix_version: str = '1'
    chunker_version: str = 'section-sentence-v1'
    provenance_policy_version: str = 'exact-spans-v1'
    max_input_tokens: int = 2048
    tokenizer_path: str = ''
    tokenizer_sha256: str = ''

    def __post_init__(self):
        if type(self.target_tokens) is not int or not 300 <= self.target_tokens <= 1200: raise ValueError('Target must be 300–1200')
        if type(self.overlap_tokens) is not int or not 0 <= self.overlap_tokens <= 200 or self.overlap_tokens >= self.target_tokens: raise ValueError('Overlap must be 0–200 and below target')
        if self.strategy != 'section_aware' or self.max_input_tokens != 2048: raise ValueError('Unsupported chunk strategy/model cap')
        try:
            parts = list(Formatter().parse(self.prefix_template))
            if {p[1] for p in parts if p[1] is not None} != {'product_name','section_title'} or any(p[2] or p[3] for p in parts): raise ValueError()
        except ValueError: raise ValueError('Prefix requires only product_name and section_title') from None
        if self.tokenizer not in {'utf8-byte-upper-bound','local-tokenizer-json'}: raise ValueError('Unsupported token counter')
        if self.tokenizer == 'local-tokenizer-json' and (not self.tokenizer_path or not re.fullmatch('[a-f0-9]{64}',self.tokenizer_sha256)): raise ValueError('Local tokenizer requires path and SHA256')

    def as_dict(self): return asdict(self)
    def fingerprint(self): return digest(self.as_dict())


def token_count(text: str, config: ChunkConfig | None = None):
    """Default is a byte upper bound plus reserved special tokens, explicitly."""
    config = config or ChunkConfig()
    if config.tokenizer == 'local-tokenizer-json':
        from tokenizers import Tokenizer
        data = Path(config.tokenizer_path).read_bytes()
        if hashlib.sha256(data).hexdigest() != config.tokenizer_sha256: raise ValueError('Local tokenizer hash changed')
        return len(Tokenizer.from_str(data.decode()).encode(text, add_special_tokens=True).ids)
    return len(text.encode('utf-8')) + 8


def _units(text, atomic=False):
    if atomic: return [(0,len(text))]
    # Consume trailing whitespace with each sentence: no characters disappear.
    result=[]; start=0
    for match in re.finditer(r'[.!?](?:[\"\u201d\u2019\)]*)(?=\s|$)\s*', text):
        end=match.end()
        if end > start: result.append((start,end)); start=end
    if start < len(text): result.append((start,len(text)))
    return result


def _source_spans(group, start, end):
    result=[]
    for block, lo, hi in group:
        a,b=max(start,lo),min(end,hi)
        if a>=b: continue
        # SourceBlock has exact page span(s); convert relative passage positions.
        relative_start,relative_end=a-lo,b-lo
        cursor=0
        for source in block.spans:
            length=source['end']-source['start']
            sa,sb=max(relative_start,cursor),min(relative_end,cursor+length)
            if sa<sb:
                result.append({'source_block_id':block.id,'page':source['page'],'archive_block_id':source.get('block_id',''),
                               'start':source['start']+sa-cursor,'end':source['start']+sb-cursor,
                               'block_start':sa+block.source_offset,'block_end':sb+block.source_offset})
            cursor+=length
        if cursor != len(block.text): raise ValueError('Source span length does not match passage')
    return result


def prepare_chunks(corpus, reviews, config: ChunkConfig, *, policy=MANUAL_POLICY, source_dir=None) -> ChunkPlan:
    policy_for({'eligibility_policy':policy})
    bulk = policy == BULK_POLICY
    assessment = assess_corpus(corpus, source_dir, policy, reviews) if bulk else None
    excluded=[]; groups=[]; current=[]; previous_key=None
    if bulk:
        review_statuses, review_hash = {}, ''
    else:
        review_statuses, review_hash = reviews.snapshot(corpus)
    def flush():
        nonlocal current
        if current: groups.append(current); current=[]
    products={p.id:p for p in corpus.products}; documents={d.id:d for d in corpus.documents}
    has_sections={b.document_id for b in corpus.blocks if b.section_kind!='sourcePageArchive'}
    for block in (assessment.eligible_span_units if bulk else corpus.blocks):
        reason=None
        status=review_statuses.get(block.id)
        if bulk: pass
        elif status!='accepted': reason='review_'+status
        elif not block.text.strip(): reason='no_usable_text'
        elif any(w.startswith('unresolved_') or w.startswith('no_usable_text') for w in block.warnings): reason='unresolved_extraction_structure'
        elif block.section_kind=='sourcePageArchive' and block.document_id in has_sections: reason='duplicate_page_archive_use_section_passages'
        elif block.content_hash!=hashlib.sha256(block.text.encode()).hexdigest(): reason='invalid_content_hash'
        elif block.document_id not in documents or block.product_id not in products: reason='missing_document_product'
        elif documents[block.document_id].sha256!=block.document_sha256 or documents[block.document_id].product_id!=block.product_id: reason='document_scope_mismatch'
        elif not block.spans or any(s.get('page',0)<1 or s.get('page',0)>documents[block.document_id].page_count or s.get('start',-1)<0 or s.get('end',-1)<s.get('start',0) for s in block.spans): reason='invalid_provenance'
        if reason:
            flush(); previous_key=None
            excluded.append({'block_id':block.id,'reason':reason,'document_id':block.document_id,'content_hash':block.content_hash,'character_count':len(block.text)})
            continue
        key=(block.product_id,block.document_id,block.document_sha256,block.section_id,block.section_kind,block.section_title,block.parser_version)
        if bulk: key += (block.id, block.source_offset)
        if key!=previous_key: flush()
        current.append(block); previous_key=key
    flush()
    chunks=[]; config_hash=config.fingerprint()
    for blocks in groups:
        first=blocks[0]; doc=documents[first.document_id]; product=products[first.product_id]
        text=''; group=[]
        for block in blocks:
            if text: text+='\n'
            lo=len(text); text+=block.text; group.append((block,lo,len(text)))
        prefix=config.prefix_template.format(product_name=product.name,section_title=first.section_title)
        atomic=first.section_kind in {'table','verifiedTable'}
        units=_units(text,atomic=atomic)
        forced_split=False
        if bulk:
            safe=[]
            for start,end in units:
                if len((prefix+text[start:end]).encode())+8 <= 2048 and token_count(prefix+text[start:end],config) <= 2048:
                    safe.append((start,end)); continue
                forced_split=True
                cursor=start
                while cursor<end:
                    lo,hi=cursor+1,end
                    best=cursor
                    # Character indices preserve UTF-8 boundaries and exact offsets.
                    while lo<=hi:
                        middle=(lo+hi)//2
                        candidate=prefix+text[cursor:middle]
                        if len(candidate.encode())+8<=2048 and token_count(candidate,config)<=config.target_tokens:
                            best=middle; lo=middle+1
                        else: hi=middle-1
                    if best==cursor: raise ValueError('Chunk prefix leaves no room for a complete source character.')
                    if best<end:
                        boundary=max(text.rfind(' ',cursor,best),text.rfind('\n',cursor,best))
                        if boundary>cursor: best=boundary+1
                    safe.append((cursor,best)); cursor=best
            units=safe
        group_chunk_start=len(chunks)
        position=0
        while position<len(units):
            start,end=units[position]; selected=position
            candidate=prefix+text[start:end]
            if len(candidate.encode())+8>2048 or token_count(candidate,config)>2048:
                spans=_source_spans(group,start,end)
                for bid in dict.fromkeys(s['source_block_id'] for s in spans):
                    excluded.append({'block_id':bid,'reason':'indivisible_unit_exceeds_model_cap','document_id':doc.id,'start':start,'end':end,'source_spans':[s for s in spans if s['source_block_id']==bid],'character_count':sum(s['block_end']-s['block_start'] for s in spans if s['source_block_id']==bid)})
                position+=1; continue
            while selected+1<len(units):
                new_end=units[selected+1][1]; candidate=prefix+text[start:new_end]
                if len(candidate.encode())+8>2048 or token_count(candidate,config)>config.target_tokens: break
                selected+=1; end=new_end
            embedded=prefix+text[start:end]
            spans=_source_spans(group,start,end)
            if not spans: raise ValueError('Chunk has no exact source spans')
            ids=list(dict.fromkeys(s['source_block_id'] for s in spans))
            metadata={'product_id':product.id,'product_name':product.name,'document_id':doc.id,'document_sha256':doc.sha256,
                      'filename':doc.filename,'section_id':first.section_id,'section_title':first.section_title,'section_kind':first.section_kind,
                      'block_ids':ids,'page_start':min(s['page'] for s in spans),'page_end':max(s['page'] for s in spans),
                      'review_state':'accepted','content_hash':hashlib.sha256(embedded.encode()).hexdigest(),
                      'parser_version':first.parser_version,'chunker_version':config.chunker_version,'chunk_config_hash':config_hash,
                      'xml_hash':corpus.xml_hash,'source_spans':canonical(spans),'source_text':text[start:end],
                      'token_count_is_exact':False,'token_count_method':config.tokenizer + '+8-reserve' if config.tokenizer=='utf8-byte-upper-bound' else 'local-artifact-exact-provider-parity-unverified'}
            if bulk:
                metadata.pop('review_state')
                metadata.update(eligibility_policy=BULK_POLICY, eligibility_fingerprint=assessment.fingerprint,
                                source_verified=True, human_review_status='not_assessed',
                                extraction_method=first.parser_version,
                                extraction_limitations=list(dict.fromkeys(w for b in blocks for w in b.warnings)))
            if doc.variant_hint: metadata['source_variant_hint']=doc.variant_hint
            if doc.revision: metadata['label_revision']=doc.revision
            cid='chunk-'+digest({'document_hash':doc.sha256,'text_hash':metadata['content_hash'],'section_id':first.section_id,'spans':spans,'config':config_hash})
            if len(canonical(metadata).encode())>40_000: raise ValueError('Chunk metadata exceeds 40KB')
            chunks.append(Chunk(cid,embedded,metadata,token_count(embedded,config)))
            if selected==len(units)-1: break
            next_position=selected+1
            if config.overlap_tokens:
                overlap_start=selected
                while overlap_start>position and token_count(text[units[overlap_start-1][0]:end],config)<=config.overlap_tokens:
                    overlap_start-=1
                if overlap_start>position and token_count(text[units[overlap_start][0]:end],config)<=config.overlap_tokens:
                    next_position=overlap_start
            position=next_position
        if bulk and forced_split:
            continuations=chunks[group_chunk_start:]
            for index,chunk in enumerate(continuations):
                chunk.metadata.update(continuation_parent_ids=list(dict.fromkeys(b.id for b in blocks)),
                                      continuation_index=index, continuation_count=len(continuations))
    fingerprint=digest({'xml_hash':corpus.xml_hash,'reviews':review_hash,'config':config_hash,'chunks':[c.id for c in chunks],'excluded':excluded, **({'policy':policy,'eligibility':assessment.fingerprint} if bulk else {})})
    settings=config.as_dict(); settings.update(token_count_is_exact=False,token_count_method='UTF-8 byte upper bound + 8 reserve' if config.tokenizer=='utf8-byte-upper-bound' else 'local tokenizer artifact; provider parity unverified',target_overlap_units='UTF-8 bytes + reserve' if config.tokenizer=='utf8-byte-upper-bound' else 'local tokenizer tokens')
    plan=ChunkPlan(chunks,excluded,fingerprint,corpus.xml_hash,config_hash,review_hash,settings)
    if bulk:
        plan.schema_version=SCHEMA_VERSION
        plan.eligibility_policy=policy
        plan.eligibility_fingerprint=assessment.fingerprint
        plan.expected_document_ids=assessment.expected_document_ids
        plan.expected_product_ids=assessment.expected_product_ids
        plan.coverage=coverage_for(corpus, [(c.metadata['document_sha256'],span) for c in chunks
                                          for span in json.loads(c.metadata['source_spans'])])
        if not plan.coverage['complete']: raise ValueError('Bulk chunks do not cover every readable archived source interval.')
    return plan
