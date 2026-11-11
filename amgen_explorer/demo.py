"""Read-only prepared demo with local source integrity checks and no services."""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path
import xml.etree.ElementTree as ET

from .xml_store import load_corpus

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = 'demos/repatha-mechanism.json'


class DemoUnavailable(ValueError):
    """The prepared example cannot be verified against the included sources."""


@dataclass(frozen=True)
class DemoExample:
    prepared: dict
    pdf_bytes: bytes
    canonical_xml: str
    chunk_text: str

    @property
    def citation(self):
        return self.prepared['citation']

    def page_image(self):
        import pymupdf
        with pymupdf.open(stream=self.pdf_bytes, filetype='pdf') as pdf:
            return pdf[self.citation['page_start'] - 1].get_pixmap(matrix=pymupdf.Matrix(1.25, 1.25)).tobytes('png')


def load_example(root: Path = ROOT) -> DemoExample:
    """Recheck bytes on every render; never consult a manifest, DB or provider.

    A failed check hides all prepared clinical content. The fixture deliberately
    carries no index location, review decision, connection result or credentials.
    """
    try:
        return _load_example(Path(root))
    except (OSError, ValueError, KeyError, TypeError, IndexError, StopIteration, ET.ParseError):
        raise DemoUnavailable('The prepared demo source is missing, changed, or could not be verified. Restore the included XML, PDF and demo fixture, then restart the tour.') from None


def _load_example(root):
    import pymupdf
    fixture = json.loads((root / FIXTURE).read_text(encoding='utf-8'))
    if fixture['schema_version'] != 1 or fixture['kind'] != 'prepared-source-backed-example':
        raise ValueError('Unknown fixture')
    ref = fixture['citation']
    xml_path = root / 'XML' / 'AmgenProducts.xml'
    xml_bytes = xml_path.read_bytes()
    if sha256(xml_bytes).hexdigest() != ref['xml_hash']:
        raise ValueError('Changed XML')
    corpus = load_corpus(xml_path)
    if corpus.xml_hash != ref['xml_hash']:
        raise ValueError('Changed XML during validation')
    if Path(ref['filename']).name != ref['filename'] or '\\' in ref['filename']:
        raise ValueError('Unsafe PDF path')
    pdf_bytes = (root / 'Documents' / ref['filename']).read_bytes()
    doc = next(d for d in corpus.documents if d.id == ref['document_id'])
    product = next(p for p in corpus.products if p.id == ref['product_id'])
    if (sha256(pdf_bytes).hexdigest() != ref['document_sha256'] or
            doc.sha256 != ref['document_sha256'] or doc.filename != ref['filename'] or
            doc.product_id != product.id or product.name != ref['product_name']):
        raise ValueError('Document identity mismatch')
    blocks = {b.id: b for b in corpus.blocks}
    spans = fixture['source_spans']
    if not spans or list(dict.fromkeys(s['source_block_id'] for s in spans)) != ref['block_ids']:
        raise ValueError('Missing exact spans')
    texts = []
    for span in spans:
        block = blocks[span['source_block_id']]
        archive = blocks[span['archive_block_id']]
        lo, hi = span['block_start'], span['block_end']
        start, end = span['start'], span['end']
        if (block.document_id != doc.id or block.product_id != product.id or
                block.section_id != ref['section_id'] or block.section_title != ref['section_title'] or
                archive.document_id != doc.id or archive.section_kind != 'sourcePageArchive' or
                archive.page_start != span['page'] or block.page_start != span['page'] or
                not 0 <= lo < hi <= len(block.text) or not 0 <= start < end <= len(archive.text)):
            raise ValueError('Span scope mismatch')
        if block.text[lo:hi] != archive.text[start:end]:
            raise ValueError('Span text mismatch')
        if not any(s['block_id'] == archive.id and s['page'] == span['page'] and
                   s['start'] + lo == start and s['start'] + hi == end for s in block.spans):
            raise ValueError('Span coordinate mismatch')
        texts.append(block.text[lo:hi])
    if '\n'.join(texts) != ref['source_text'] or not ref['supporting_quote'] or ref['supporting_quote'] not in ref['source_text']:
        raise ValueError('Prepared quote mismatch')
    pages = [s['page'] for s in spans]
    if (min(pages), max(pages)) != (ref['page_start'], ref['page_end']):
        raise ValueError('Citation pages mismatch')
    with pymupdf.open(stream=pdf_bytes, filetype='pdf') as pdf:
        if len(pdf) != doc.page_count:
            raise ValueError('PDF pages mismatch')
        for span in spans:
            if pdf[span['page'] - 1].get_text('text', sort=False) != blocks[span['archive_block_id']].text:
                raise ValueError('PDF text mismatch')
    quiz = fixture['quiz']
    if (type(quiz['correct_index']) is not int or not 0 <= quiz['correct_index'] < len(quiz['choices']) or
            len(quiz['choices']) < 2 or not fixture['answer'] or not fixture['question']):
        raise ValueError('Invalid prepared content')
    # Show actual canonical XML, never a reconstructed or invented source node.
    section = next(n for n in ET.fromstring(xml_bytes).iter() if n.get('id') == ref['section_id'])
    canonical_xml = ET.tostring(section, encoding='unicode').strip()
    chunk_text = f"{product.name} — {ref['section_title']}\n{ref['source_text']}"
    return DemoExample(fixture, pdf_bytes, canonical_xml, chunk_text)
