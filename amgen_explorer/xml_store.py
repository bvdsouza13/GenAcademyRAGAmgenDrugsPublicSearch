"""Safe local XML loading and exact-page provenance validation."""
from __future__ import annotations
import hashlib
from pathlib import Path
import xml.etree.ElementTree as ET
from .models import Corpus, Product, Document, SourceBlock

NS = 'urn:local:pi-corpus:1'
EXT = 'urn:local:pi-corpus:extraction:1'
P = {'p': NS, 'c': EXT}
def q(name): return '{' + NS + '}' + name
def x(name): return '{' + EXT + '}' + name
def sha(text): return hashlib.sha256(text.encode('utf-8')).hexdigest()


def _parse(path):
    data = Path(path).read_bytes()
    if b'<!DOCTYPE' in data.upper() or b'<!ENTITY' in data.upper():
        raise ValueError('DTD and entity declarations are not allowed')
    # A byte substring check alone misses UTF-16 declarations. Inspect document
    # metadata with entity/network resolution disabled before ElementTree sees it.
    from lxml import etree
    try:
        safe_tree = etree.fromstring(data, etree.XMLParser(resolve_entities=False, load_dtd=False, no_network=True)).getroottree()
    except etree.XMLSyntaxError as error:
        raise ValueError('Malformed corpus XML') from error
    if safe_tree.docinfo.doctype:
        raise ValueError('DTD and entity declarations are not allowed')
    try: root = ET.fromstring(data)
    except ET.ParseError as error: raise ValueError('Malformed corpus XML') from error
    if root.tag != q('prescribingInformationCollection'):
        raise ValueError('Wrong corpus root or namespace')
    return data, root


def validate_schema(path: Path) -> bool:
    """Validate compatible custom structure, never clinical truth or FDA SPL."""
    from lxml import etree
    _parse(path)
    parser = etree.XMLParser(resolve_entities=False, no_network=True)
    schema_path = Path(__file__).resolve().parents[1] / 'XML' / 'prescribing-information.xsd'
    schema = etree.XMLSchema(etree.parse(str(schema_path), parser))
    try: schema.assertValid(etree.parse(str(path), parser))
    except etree.DocumentInvalid as error: raise ValueError('Local structural XSD validation failed: ' + str(error.error_log.last_error)) from error
    return True


def load_corpus(path: Path) -> Corpus:
    path = Path(path)
    data, root = _parse(path)
    validate_schema(path)
    all_nodes = list(root.iter())
    ids = [n.get('id') for n in all_nodes if n.get('id')]
    if len(ids) != len(set(ids)): raise ValueError('Duplicate XML IDs')
    by_id = {n.get('id'): n for n in all_nodes if n.get('id')}
    for n in all_nodes:
        for attr in ('ref', 'documentRef', 'blockRef', 'sectionRef', x('fragmentRef')):
            if n.get(attr) and n.get(attr) not in by_id: raise ValueError('Unresolved source reference')
        for attr in ('variantRefs', 'figureRefs', 'footnoteRefs', 'indicationRefs'):
            if any(v not in by_id for v in n.get(attr, '').split()): raise ValueError('Unresolved source reference list')
    products = []
    for n in root.findall('p:products/p:product', P):
        name = n.findtext('p:brandName/p:textRaw', namespaces=P) or n.get('id', '').removeprefix('product-').upper()
        generic = n.findtext('p:genericName/p:textRaw', namespaces=P) or ''
        products.append(Product(n.get('id'), name, generic))
    product_map = {p.id: p for p in products}
    documents, blocks, warnings = [], [], []
    for n in root.findall('p:documents/p:document', P):
        did = n.get('id')
        product_refs = n.findall('p:coverage/p:productRef', P)
        if len(product_refs) != 1 or product_refs[0].get('ref') not in product_map: raise ValueError('Document must resolve to one product')
        pid = product_refs[0].get('ref')
        doc_hash = n.findtext('p:acquisition/p:sha256', namespaces=P) or ''
        import re
        if not re.fullmatch('[a-f0-9]{64}', doc_hash): raise ValueError('Missing/invalid document hash')
        local_path = n.findtext('p:acquisition/p:localPath', namespaces=P) or ''
        if not local_path or Path(local_path).is_absolute() or '..' in Path(local_path).parts: raise ValueError('Unsafe document source path')
        sections = n.findall('p:rawSections/p:section', P)
        archives = [s for s in sections if s.get('kind') == 'sourcePageArchive']
        count = int(n.findtext('p:extractionQuality/p:pageCount', default='0', namespaces=P))
        if count != len(archives): raise ValueError('Missing source archive pages')
        revision = n.find('p:labelMetadata/p:labelRevision', P)
        # Extracted dates do not become verified dates merely by parsing them.
        doc = Document(did, pid, Path(local_path).name, doc_hash, count,
                       revision.text if revision is not None and revision.get('reviewStatus') == 'reviewed' else '',
                       n.findtext('p:coverage/c:sourceScope', default='', namespaces=P))
        documents.append(doc); product_map[pid].document_ids.append(did)
        warnings.extend(i.text for i in n.findall('p:extractionQuality/p:issue', P) if i.text)
        archive_by_id = {}
        for page, section in enumerate(archives, 1):
            if section.get(x('pdfPage')) != str(page): raise ValueError('Invalid physical page order')
            paragraph = section.find(q('paragraph'))
            if paragraph is None: raise ValueError('Missing archived page paragraph')
            text = paragraph.text or ''
            if sha(text) != paragraph.get(x('sha256')): raise ValueError('Source page hash mismatch')
            archive_by_id[paragraph.get('id')] = (page, text)
        for section in sections:
            kind, sid = section.get('kind', 'unknown'), section.get('id')
            title = section.findtext(q('heading')) or ''
            for paragraph in section.findall(q('paragraph')):
                text, bid = paragraph.text or '', paragraph.get('id')
                if sha(text) != paragraph.get(x('sha256')): raise ValueError('Passage hash mismatch')
                if kind == 'sourcePageArchive':
                    page = int(section.get(x('pdfPage')))
                    spans = [{'page': page, 'block_id': bid, 'start': 0, 'end': len(text)}]
                else:
                    evs = [e for e in section.findall(q('evidence')) if e.get(x('fragmentRef')) == bid]
                    if len(evs) != 1: raise ValueError('Passage requires one precise page span')
                    ev = evs[0]
                    if ev.get('documentRef') != did: raise ValueError('Cross-document evidence')
                    if ev.get('blockRef') not in archive_by_id: raise ValueError('Missing page archive reference')
                    page, source = archive_by_id[ev.get('blockRef')]
                    lo, hi = int(ev.get(x('characterStart'))), int(ev.get(x('characterEndExclusive')))
                    if not 0 <= lo <= hi <= len(source) or source[lo:hi] != text: raise ValueError('Source span/hash mismatch')
                    if int(ev.get('pageStart')) != page or int(ev.get('pageEnd')) != page: raise ValueError('Evidence page mismatch')
                    spans = [{'page': page, 'block_id': ev.get('blockRef'), 'start': lo, 'end': hi}]
                block_warnings = []
                if not text.strip(): block_warnings.append('no_usable_text_ocr_unavailable')
                # Explicit unresolved structural warnings always remain hard exclusions.
                for issue in paragraph.get(x('warnings'), '').split(): block_warnings.append(issue)
                blocks.append(SourceBlock(bid, pid, did, doc_hash, text, sid, title, kind, page, page, sha(text), spans,
                                          root.get(x('parserVersion'), 'text-layer-v1'), block_warnings))
        for ev in n.findall('.//p:evidence', P):
            if ev.get('documentRef') != did: raise ValueError('Cross-document evidence reference')
            if not 1 <= int(ev.get('pageStart', '0')) <= int(ev.get('pageEnd', '0')) <= count: raise ValueError('Evidence page out of bounds')
    for ev in root.findall('.//p:evidence', P):
        quote = ev.findtext(q('quote'))
        if quote is not None and ev.get('blockRef') and quote not in (by_id[ev.get('blockRef')].text or ''): raise ValueError('Metadata quote missing from source')
    return Corpus(path, hashlib.sha256(data).hexdigest(), products, documents, blocks, sorted(set(warnings)))


def validate_source_files(corpus: Corpus, source_dir: Path) -> dict:
    """Read-only verification of current PDFs against canonical archived text.

    Unlike XML-only loading, this requires an exact current input inventory and
    compares the actual PDF bytes, physical pages and sort=False text extraction.
    Source bytes are opened from the same in-memory snapshot that was hashed.
    Errors omit filesystem paths and parser/provider exception details.
    """
    import pymupdf
    source_dir = Path(source_dir)

    def inventory():
        try:
            return {p.name: p for p in source_dir.iterdir()
                    if p.is_file() and p.suffix.lower() == '.pdf'}
        except OSError:
            raise ValueError('Unable to read source PDF inventory.') from None

    paths = inventory()
    names = [document.filename for document in corpus.documents]
    if len(names) != len(set(names)) or set(names) != set(paths):
        raise ValueError('Current PDF inventory differs from the canonical XML; rebuild is required.')
    archives = {}
    for block in corpus.blocks:
        if block.section_kind == 'sourcePageArchive':
            key = (block.document_id, block.page_start)
            if key in archives or block.page_end != block.page_start:
                raise ValueError('Source archive page inventory is inconsistent.')
            archives[key] = block
    hashes_verified = pages_verified = 0
    for document in corpus.documents:
        try:
            source_bytes = paths[document.filename].read_bytes()
        except OSError:
            raise ValueError('Unable to read a canonical source PDF.') from None
        if hashlib.sha256(source_bytes).hexdigest() != document.sha256:
            raise ValueError('Current source PDF hash differs from the canonical XML; rebuild is required.')
        hashes_verified += 1
        try:
            with pymupdf.open(stream=source_bytes, filetype='pdf') as source:
                if len(source) != document.page_count:
                    raise ValueError('Source PDF page count differs from the canonical XML.')
                document_archives = [key for key in archives if key[0] == document.id]
                if len(document_archives) != len(source):
                    raise ValueError('Source archive page count differs from the current PDF.')
                for page_number, page in enumerate(source, 1):
                    archived = archives.get((document.id, page_number))
                    if archived is None or archived.text != page.get_text('text', sort=False):
                        raise ValueError('Source PDF page text differs from the canonical XML archive.')
                    if sha(archived.text) != archived.content_hash:
                        raise ValueError('Source archive text hash is inconsistent.')
                    pages_verified += 1
        except ValueError:
            raise
        except Exception:
            raise ValueError('Unable to extract a source PDF during validation.') from None
        try:
            unchanged = hashlib.sha256(paths[document.filename].read_bytes()).hexdigest() == document.sha256
        except OSError:
            unchanged = False
        if not unchanged:
            raise ValueError('Source PDF hash changed during validation; rebuild is required.')
    if set(inventory()) != set(paths):
        raise ValueError('PDF inventory changed during validation; rebuild is required.')
    return {'status': 'passed', 'sourceInventoryComplete': True,
            'sourcePdfHashesVerified': hashes_verified,
            'pageTextRoundTripsVerified': pages_verified, 'xml_hash': corpus.xml_hash}
