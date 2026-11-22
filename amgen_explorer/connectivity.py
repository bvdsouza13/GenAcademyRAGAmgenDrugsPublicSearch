"""Explicit, sanitized cloud checks and the pinned Documents API transport."""
from __future__ import annotations
from http.client import HTTPException
import json
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, build_opener
from scripts.setup_pinecone import (NoRedirect, PineconeControlPlane, SetupError,
                                    normalize_host, validate_index)

class ProviderError(RuntimeError):
    def __init__(self, provider, status=None, *, retry_after=None):
        self.status = status
        self.retry_after = retry_after
        self.retryable = status in (408, 429, 500, 502, 503, 504) or status is None
        super().__init__(f"{provider} request failed" + (f" (HTTP {status})" if status else "") + ". Check connectivity, configuration and service permissions.")

def request_json(url, payload=None, *, headers=None, method="POST", timeout=30):
    """Never follow redirects or expose remote bodies/headers in exceptions."""
    from .reliability import deadline_timeout, check_deadline, parse_retry_after
    timeout = deadline_timeout(timeout)
    body = None if payload is None else json.dumps(payload, ensure_ascii=False, allow_nan=False).encode()
    req = Request(url, data=body, method=method,
                  headers={"Content-Type": "application/json", "Accept": "application/json", **(headers or {})})
    try:
        with build_opener(NoRedirect()).open(req, timeout=timeout) as response:
            result = json.loads(response.read())
    except HTTPError as exc:
        code = exc.code
        retry_after = parse_retry_after(exc.headers.get('Retry-After')) if exc.headers else None
        exc.close()
        raise ProviderError("Cloud", code, retry_after=retry_after) from None
    except (URLError, OSError, HTTPException, ValueError, UnicodeError):
        raise ProviderError("Cloud") from None
    if not isinstance(result, dict):
        raise ProviderError("Cloud")
    check_deadline()
    return result

class DocumentsClient:
    """REST shapes pinned to Pinecone Documents API 2026-07; no legacy fallback."""
    def __init__(self, config, *, transport=None):
        self.config = config
        self.pc = config.settings["pinecone"]
        self.transport = transport or request_json
        self.host = self.pc.get("index_host", "")

    def check(self):
        errors = self.config.validate(require_secrets=True)
        if errors:
            raise ValueError(" ".join(errors))
        description = PineconeControlPlane(self.config.pinecone_api_key, self.pc["api_version"]).describe(self.pc["index_name"])
        self.host = validate_index(description, self.config)
        return {"ready": True, "host": self.host, "api_version": self.pc["api_version"]}

    def _call(self, operation, namespace, body):
        from .reliability import retry_call, deadline_timeout
        if not self.config.pinecone_api_key:
            raise ValueError("PINECONE_API_KEY is missing.")
        host = normalize_host(self.host)
        def request():
            return self.transport(f"https://{host}/namespaces/{quote(namespace, safe='')}/documents/{operation}", body,
                              headers={"Api-Key": self.config.pinecone_api_key,
                                       "X-Pinecone-Api-Version": self.pc["api_version"]}, timeout=deadline_timeout(30))
        return retry_call(request, settings=self.config.settings) if operation in {'fetch', 'search'} else request()

    def upsert(self, namespace, documents):
        return self._call("upsert", namespace, {"documents": documents})

    def fetch(self, namespace, ids):
        response = self._call("fetch", namespace, {"ids": ids, "include_fields": ["*"]})
        if response.get("namespace", namespace) != namespace or not isinstance(response.get("documents"), dict):
            raise ValueError("Fetch returned an unexpected namespace or document shape.")
        return response["documents"]

    def search(self, namespace, question, filters, top_k):
        response = self._call("search", namespace, {
            "top_k": top_k, "score_by": [{"type": "embed", "fields": [self.pc["text_field"]], "query": question}],
            "filter": filters, "include_fields": ["*"]})
        if response.get("namespace", namespace) != namespace or not isinstance(response.get("matches"), list):
            raise ValueError("Search returned an unexpected namespace or match shape.")
        self.last_usage = response.get("usage", {}) if isinstance(response.get("usage", {}), dict) else {}
        return response["matches"]

def check_connections(config):
    """Read-only index/schema check and model availability check, on explicit call."""
    result = {"pinecone": {"ok": False}, "openai": {"ok": False}}
    try:
        status = DocumentsClient(config).check()
        result["pinecone"] = {"ok": True, **status}
    except (SetupError, ProviderError, ValueError) as error:
        result["pinecone"]["message"] = "Pinecone unavailable or index/schema incompatible. Check settings, key and index readiness."
        result['pinecone']['http_status'] = getattr(error, 'status', None)
    try:
        errors = config.validate(require_chat=True)
        if errors:
            raise ValueError()
        model = config.settings["openai"]["model"]
        request_json("https://api.openai.com/v1/models/" + quote(model, safe=""),
                     method="GET", headers={"Authorization": "Bearer " + config.openai_api_key},
                     timeout=config.settings["openai"]["request_timeout_seconds"])
        result["openai"] = {"ok": True, "model": model,
                            "generation_checked": False,
                            "message": "Model is available; generation was not requested."}
    except (ProviderError, ValueError) as error:
        result["openai"]["message"] = "OpenAI unavailable. Check key, model access and settings."
        result['openai']['http_status'] = getattr(error, 'status', None)
    return result
