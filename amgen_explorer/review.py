"""Append-only local review decisions bound to exact extraction and evidence."""
from __future__ import annotations
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
from .models import Corpus, SourceBlock

DECISIONS = {'accepted', 'rejected', 'needs-review'}

def canonical(value): return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False)
def digest(value): return hashlib.sha256(canonical(value).encode()).hexdigest()

def block_scope(block: SourceBlock):
    return {'block_id': block.id, 'document_id': block.document_id, 'document_sha256': block.document_sha256,
            'passage_sha256': block.content_hash, 'parser_version': block.parser_version,
            'product_id': block.product_id, 'section_id': block.section_id, 'section_kind': block.section_kind,
            'section_title': block.section_title, 'page_start': block.page_start, 'page_end': block.page_end,
            'warnings': block.warnings, 'evidence_coordinates': block.spans, 'scope': 'raw-passage-only'}

class ReviewStore:
    def __init__(self, path: Path): self.path = Path(path)

    def record(self, block: SourceBlock, decision: str, reviewer: str, note: str = ''):
        if decision not in DECISIONS: raise ValueError('Unknown review decision')
        if not reviewer.strip(): raise ValueError('Reviewer is required')
        if hashlib.sha256(block.text.encode()).hexdigest() != block.content_hash: raise ValueError('Passage hash does not match text')
        if not block.spans or block.page_start < 1 or block.page_end < block.page_start: raise ValueError('Valid evidence coordinates are required')
        scope = block_scope(block)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path, timeout=30) as db:
            db.execute('PRAGMA journal_mode=WAL')
            db.execute('CREATE TABLE IF NOT EXISTS reviews (id INTEGER PRIMARY KEY, scope_hash TEXT NOT NULL, block_id TEXT NOT NULL, decision TEXT NOT NULL, reviewer TEXT NOT NULL, note TEXT NOT NULL, recorded_at TEXT NOT NULL, scope_json TEXT NOT NULL)')
            db.execute('CREATE INDEX IF NOT EXISTS review_scope_idx ON reviews(scope_hash,id)')
            db.execute('INSERT INTO reviews(scope_hash,block_id,decision,reviewer,note,recorded_at,scope_json) VALUES (?,?,?,?,?,?,?)',
                       (digest(scope), block.id, decision, reviewer.strip(), note, datetime.now(timezone.utc).isoformat(), canonical(scope)))

    def _latest(self, block):
        if not self.path.exists(): return None
        # Read-only mode avoids creating state during application reruns.
        with sqlite3.connect(self.path.resolve().as_uri() + '?mode=ro', uri=True) as db:
            exists = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='reviews'").fetchone()
            if not exists: return None
            return db.execute('SELECT decision,reviewer,note,recorded_at,scope_json FROM reviews WHERE scope_hash=? ORDER BY id DESC LIMIT 1', (digest(block_scope(block)),)).fetchone()

    def status(self, block):
        if hashlib.sha256(block.text.encode()).hexdigest() != block.content_hash: return 'needs-review'
        row = self._latest(block)
        return row[0] if row else 'needs-review'

    def snapshot(self, corpus: Corpus):
        """One SQLite read snapshot for all statuses and their matching fingerprint."""
        rows = {}
        if self.path.exists():
            with sqlite3.connect(self.path.resolve().as_uri() + '?mode=ro', uri=True) as db:
                if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='reviews'").fetchone():
                    rows = {row[0]: row[1:] for row in db.execute('SELECT scope_hash,decision,reviewer,note,recorded_at,scope_json FROM reviews WHERE id IN (SELECT MAX(id) FROM reviews GROUP BY scope_hash)')}
        statuses, record = {}, []
        for block in sorted(corpus.blocks, key=lambda b:b.id):
            scope = block_scope(block)
            row = rows.get(digest(scope))
            valid = hashlib.sha256(block.text.encode()).hexdigest() == block.content_hash
            statuses[block.id] = row[0] if row and valid else 'needs-review'
            record.append({'scope': scope, 'review': row})
        return statuses, digest(record)

    def fingerprint(self, corpus: Corpus):
        return self.snapshot(corpus)[1]

    def summary(self, corpus: Corpus):
        statuses, _ = self.snapshot(corpus)
        result = {decision: 0 for decision in sorted(DECISIONS)}
        for status in statuses.values(): result[status] += 1
        result['total'] = len(corpus.blocks)
        return result
