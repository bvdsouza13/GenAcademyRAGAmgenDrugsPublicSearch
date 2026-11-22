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


def validate_registry(data):
    """Validate inventory identity without inferring an inventory from damaged data."""
    try:
        if (not isinstance(data, dict) or data.get('schema_version') != 1
                or not isinstance(data.get('documents'), list)
                or data.get('fingerprint') != digest(data['documents'])):
            raise ValueError()
        ids = []; names = []; hashes = []
        for document in data['documents']:
            if not isinstance(document, dict): raise ValueError()
            for field in ('document_id', 'product_id', 'product_name', 'filename', 'sha256'):
                if not isinstance(document.get(field), str) or not document[field]: raise ValueError()
            name = document['filename']
            if (Path(name).name != name or '/' in name or '\\' in name
                    or name in {'.', '..'} or not name.lower().endswith('.pdf')
                    or not re.fullmatch(r'[a-f0-9]{64}', document['sha256'])):
                raise ValueError()
            if not all(re.fullmatch(r'[A-Za-z_][A-Za-z0-9_.-]*', document[field])
                       for field in ('document_id', 'product_id')): raise ValueError()
            ids.append(document['document_id']); names.append(name.casefold()); hashes.append(document['sha256'])
        if len(ids) != len(set(ids)) or len(names) != len(set(names)) or len(hashes) != len(set(hashes)):
            raise ValueError()
        return data
    except (ValueError, TypeError, KeyError):
        raise UserFacingError('The source registry failed validation. Restore its saved version before building.') from None


def read_registry(config, corpus=None):
    path = config.root/'data/source-registry.json'
    if path.exists():
        try:
            return validate_registry(json.loads(path.read_text()))
        except (OSError, ValueError, TypeError):
            raise UserFacingError('The source registry failed validation. Restore its saved version before building.') from None
    names = {p.id:p.name for p in corpus.products} if corpus else {}
    return validate_registry(_registry([{'document_id':d.id,'product_id':d.product_id,'product_name':names[d.product_id],
                      'filename':Path(d.filename).name,'sha256':d.sha256} for d in corpus.documents] if corpus else []))


def save_registry(config, registry):
    data=(json.dumps(registry,ensure_ascii=False,indent=2)+'\n').encode()
    snapshot=config.root/'data/source-registries'/(registry['fingerprint']+'.json')
    if snapshot.exists():
        saved = snapshot.read_bytes()
        try:
            if validate_registry(json.loads(saved)) != registry: raise ValueError()
        except (ValueError, TypeError):
            raise UserFacingError('A source registry snapshot failed integrity validation.') from None
        data = saved  # Preserve the original immutable snapshot serialization.
    else:
        atomic_bytes(snapshot,data)
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
                if not target.resolve().is_relative_to(directory.resolve()):
                    raise UserFacingError('A source PDF points outside the configured Documents folder.')
                existing = writes.get(registered)
                if existing is None and target.exists(): existing = target.read_bytes()
                if existing is None:
                    writes[registered]=upload.payload
                    imported.append(registered)
                elif hashlib.sha256(existing).hexdigest() != sha:
                    if not upload.replace_existing:
                        raise UserFacingError('Replace matching filenames must be selected to restore a changed source PDF.')
                    writes[registered]=upload.payload
                    replaced.append(registered)
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
        # Reject traversal through registered destinations before reading rollback
        # bytes or replacing any path, including explicit source repairs.
        if any(not (directory/name).resolve().is_relative_to(directory.resolve()) for name in writes):
            raise UserFacingError('A source PDF points outside the configured Documents folder.')
        # Retain originals for rollback of local I/O failure (including registry write).
        originals={name:(directory/name).read_bytes() if (directory/name).exists() else None for name in writes}
        previous=(config.root/'data/source-registry.json').read_bytes() if (config.root/'data/source-registry.json').exists() else None
        try:
            for name,payload in writes.items(): atomic_bytes(directory/name,payload)
            if writes: save_registry(config,_registry(entries))
            if writes:
                from .durable_library import backend_enabled, sync_paths
                if backend_enabled():
                    paths=[directory/name for name in writes]
                    registry=_registry(entries)
                    paths.extend([config.root/'data/source-registry.json',
                                  config.root/'data/source-registries'/(registry['fingerprint']+'.json')])
                    sync_paths(config,paths)
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
