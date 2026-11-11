"""Transactional local PDF imports and an authoritative, versioned inventory."""
from __future__ import annotations
from .errors import UserFacingError
from contextlib import contextmanager
from dataclasses import dataclass
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile

from .review import digest


@dataclass(frozen=True)
class SourceUpload:
    filename: str
    payload: bytes
    replace_existing: bool = False


@contextmanager
def library_lock(config):
    directory=config.root/'data'
    directory.mkdir(parents=True,exist_ok=True)
    with (directory/'library.lock').open('a+') as handle:
        try:
            fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:
            raise UserFacingError('Another library operation is running. Retry after it finishes.') from None
        try:
            yield
        finally:
            fcntl.flock(handle,fcntl.LOCK_UN)


def atomic_bytes(path, payload):
    path.parent.mkdir(parents=True,exist_ok=True)
    fd,name=tempfile.mkstemp(prefix='.import-',dir=path.parent)
    try:
        with os.fdopen(fd,'wb') as handle:
            handle.write(payload);handle.flush();os.fsync(handle.fileno())
        os.replace(name,path)
    finally:
        Path(name).unlink(missing_ok=True)


def _registry(documents):
    documents=sorted(documents,key=lambda d:d['document_id'])
    return {'schema_version':1,'documents':documents,'fingerprint':digest(documents)}


def read_registry(config, corpus=None):
    path=config.root/'data/source-registry.json'
    if path.exists():
        try:
            data=json.loads(path.read_text())
            if data['schema_version']!=1 or data['fingerprint']!=digest(data['documents']):
                raise UserFacingError()
            ids=[d['document_id'] for d in data['documents']]
            names=[d['filename'].casefold() for d in data['documents']]
            if len(ids)!=len(set(ids)) or len(names)!=len(set(names)):
                raise UserFacingError()
            for d in data['documents']:
                if Path(d['filename']).name!=d['filename'] or not re.fullmatch(r'[a-f0-9]{64}',d['sha256']):
                    raise UserFacingError()
            return data
        except (OSError,ValueError,KeyError,TypeError):
            raise UserFacingError('The source registry failed validation. Restore its saved version before building.') from None
    names={p.id:p.name for p in corpus.products} if corpus else {}
    return _registry([{'document_id':d.id,'product_id':d.product_id,'product_name':names[d.product_id],
                      'filename':Path(d.filename).name,'sha256':d.sha256} for d in corpus.documents] if corpus else [])


def save_registry(config, registry):
    data=(json.dumps(registry,ensure_ascii=False,indent=2)+'\n').encode()
    snapshot=config.root/'data/source-registries'/(registry['fingerprint']+'.json')
    if snapshot.exists() and snapshot.read_bytes()!=data:
        raise UserFacingError('A source registry snapshot failed integrity validation.')
    if not snapshot.exists(): atomic_bytes(snapshot,data)
    atomic_bytes(config.root/'data/source-registry.json',data)


def _identity(payload):
    import pymupdf
    try:
        with pymupdf.open(stream=payload,filetype='pdf') as document:
            if document.needs_pass or not len(document): raise UserFacingError()
            title=document[0].get_text('text',sort=False)
            # Read all pages now; corrupt later pages must not partially import.
            for page in document: page.get_text('text',sort=False)
    except Exception:
        raise UserFacingError('One uploaded PDF is invalid, encrypted, or unreadable; no files were imported.') from None
    cutoff=re.search(r'Initial\s+U\.?S\.?\s+Approval',title,re.I)
    title=title[:cutoff.start()] if cutoff else title[:1500]
    matches=list(re.finditer(r'(?m)^\s*([A-Za-z][A-Za-z0-9 -]{1,40})[®™]?\s*\(([A-Za-z][A-Za-z0-9 -]+)\)',title))
    if not matches:
        raise UserFacingError('A PDF title has unresolved medicine identity. Use a label with a readable brand and generic title.')
    brands={re.sub(r'\s+',' ',m.group(1).strip()).upper() for m in matches}
    # XR may be an additional title presentation of the same registered brand.
    base={b.removesuffix(' XR') for b in brands}
    if len(base)!=1: raise UserFacingError('A PDF title has conflicting medicine identity.')
    brand=sorted(base)[0]
    slug=re.sub(r'[^a-z0-9.-]+','-',brand.lower()).strip('-')
    return brand,slug


def _safe_name(filename):
    if not isinstance(filename,str) or Path(filename).name!=filename or '/' in filename or '\\' in filename or not filename.lower().endswith('.pdf'):
        raise UserFacingError('Each upload needs a plain PDF filename without directory components.')
    stem=re.sub(r'[^A-Za-z0-9_.-]+','-',Path(filename).stem).strip('.-')
    if not stem or len(stem)>160: raise UserFacingError('The uploaded PDF filename is empty or too long.')
    return stem+'.pdf'


def import_documents(config, files, corpus=None):
    """Validate the entire batch before writes. Repeated byte-identical uploads are no-ops."""
    with library_lock(config):
        registry=read_registry(config,corpus)
        entries=[dict(d) for d in registry['documents']]
        by_name={d['filename'].casefold():d for d in entries}
        by_hash={d['sha256']:d for d in entries}
        directory=config.path('source_dir')
        writes={}; imported=[]; duplicates=[]; replaced=[]
        for upload in files:
            safe=_safe_name(upload.filename)
            if not isinstance(upload.payload,bytes) or not upload.payload:
                raise UserFacingError('The uploaded PDF has no bytes.')
            sha=hashlib.sha256(upload.payload).hexdigest()
            if sha in by_hash:
                registered=by_hash[sha]['filename']
                target=directory/registered
                if not target.exists() and registered not in writes:
                    writes[registered]=upload.payload
                    imported.append(registered)
                else:
                    duplicates.append(upload.filename)
                continue
            try:
                brand,slug=_identity(upload.payload)
            except UserFacingError as error:
                raise UserFacingError(upload.filename+': '+str(error)) from None
            entry=by_name.get(upload.filename.casefold()) or by_name.get(safe.casefold())
            if entry:
                if not upload.replace_existing:
                    raise UserFacingError('Replace matching filenames must be selected to update an existing source PDF.')
                if entry['product_name'].upper().removesuffix(' XR')!=brand:
                    raise UserFacingError('Replacement PDF identity does not match the registered medicine.')
                name=entry['filename']; old_hash=entry['sha256'];entry['sha256']=sha
                by_hash.pop(old_hash,None);replaced.append(name)
            else:
                # The extractor derives the base medicine from the filename. Canonical
                # names preserve supplied titles even when uploads have arbitrary names.
                suffix=Path(safe).stem
                name=safe if suffix.split('_')[0].lower()==slug else slug+'_'+safe
                if name.casefold() in by_name or (directory/name).exists():
                    raise UserFacingError('PDF filenames collide after normalization; rename the upload explicitly.')
                doc_id='doc-'+re.sub(r'[^A-Za-z0-9_.-]','-',Path(name).stem.replace('_','-'))
                if any(d['document_id']==doc_id for d in entries):
                    raise UserFacingError('PDF filenames produce the same document identity; rename the upload.')
                product_id=next((d['product_id'] for d in entries if d['product_name'].upper().removesuffix(' XR')==brand),'product-'+slug)
                entry={'document_id':doc_id,'product_id':product_id,'product_name':brand,'filename':name,'sha256':sha}
                entries.append(entry);by_name[name.casefold()]=entry;imported.append(name)
            by_hash[sha]=entry;writes[name]=upload.payload
        # Retain originals for rollback of local I/O failure (including registry write).
        originals={name:(directory/name).read_bytes() if (directory/name).exists() else None for name in writes}
        previous=(config.root/'data/source-registry.json').read_bytes() if (config.root/'data/source-registry.json').exists() else None
        try:
            for name,payload in writes.items(): atomic_bytes(directory/name,payload)
            if writes: save_registry(config,_registry(entries))
        except Exception:
            for name,payload in originals.items():
                if payload is None: (directory/name).unlink(missing_ok=True)
                else: atomic_bytes(directory/name,payload)
            if previous is not None: atomic_bytes(config.root/'data/source-registry.json',previous)
            else: (config.root/'data/source-registry.json').unlink(missing_ok=True)
            raise
        return {'imported':imported,'duplicates':duplicates,'replaced':replaced}


def inspect_inventory(config, corpus=None):
    """Resolve the full collection without modifying the registry or any source."""
    registry=read_registry(config,corpus)
    entries=[dict(d) for d in registry['documents']]
    directory=config.path('source_dir')
    paths={p.name:p for p in directory.iterdir() if p.is_file() and p.suffix.lower()=='.pdf'} if directory.exists() else {}
    missing=[d['filename'] for d in entries if d['filename'] not in paths]
    if missing: raise UserFacingError('Missing registered source PDFs: '+', '.join(missing))
    known={d['filename']:d for d in entries}
    hashes={}
    for name,path in sorted(paths.items()):
        if not path.resolve().is_relative_to(directory):
            raise UserFacingError('A source PDF points outside the configured Documents folder.')
        payload=path.read_bytes();sha=hashlib.sha256(payload).hexdigest()
        if sha in hashes: raise UserFacingError('Duplicate PDF bytes in the source folder: '+name+' / '+hashes[sha])
        hashes[sha]=name
        if name in known:
            entry=known[name]
            if entry['sha256']!=sha:
                brand,_=_identity(payload)
                if entry['product_name'].upper().removesuffix(' XR')!=brand:
                    raise UserFacingError('Changed source identity does not match its registered medicine: '+name)
                entry['sha256']=sha
        else:
            brand,slug=_identity(payload)
            _safe_name(name)
            product_id=next((d['product_id'] for d in entries if d['product_name'].upper().removesuffix(' XR')==brand),'product-'+slug)
            entry={'document_id':'doc-'+re.sub(r'[^A-Za-z0-9_.-]','-',Path(name).stem.replace('_','-')),
                   'product_id':product_id,'product_name':brand,'filename':name,'sha256':sha}
            entries.append(entry)
    if not entries: raise UserFacingError('Add PDF source documents before building the library.')
    if len({d['document_id'] for d in entries})!=len(entries): raise UserFacingError('Source filenames produce duplicate document identities.')
    return _registry(entries)
