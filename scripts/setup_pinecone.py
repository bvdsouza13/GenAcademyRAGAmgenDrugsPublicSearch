#!/usr/bin/env python3
"""Preview, inspect, or explicitly create the project's empty Pinecone index.

Uses the documented Documents API control plane (2026-07) with Python's standard
library. It never uploads documents, queries a model, or activates a corpus.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import re
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import HTTPRedirectHandler, Request, build_opener


CONTROL_URL = "https://api.pinecone.io"
API_VERSION = "2026-07"


class SetupError(Exception):
    """A safe, actionable error; never include raw API responses or credentials."""


class PineconeHTTPError(SetupError):
    def __init__(self, status: int):
        self.status = status
        advice = {
            401: "Check the Pinecone API key.",
            403: "Check the key's project and permissions.",
            404: "The named index was not found in the key's project.",
            409: "The index may now exist; run --check before retrying.",
            429: "Pinecone rate-limited this request; retry later.",
        }.get(status, "Check the Pinecone console and API status before retrying.")
        super().__init__(f"Pinecone returned HTTP {status}. {advice}")


class NoRedirect(HTTPRedirectHandler):
    """Do not forward an authenticated request to a redirected destination."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise HTTPError(CONTROL_URL, code, "Redirect refused", headers, None)


class PineconeControlPlane:
    def __init__(self, api_key: str, api_version: str, request_timeout: float = 30):
        if not api_key:
            raise SetupError("Set PINECONE_API_KEY before using --check or --create.")
        if api_version != API_VERSION:
            raise SetupError("This bootstrap supports Pinecone API version 2026-07 only.")
        self._api_key = api_key
        self._api_version = api_version
        self.request_timeout = request_timeout
        self._opener = build_opener(NoRedirect())

    def _request(self, method: str, path: str, payload=None, timeout=None) -> dict:
        body = None if payload is None else json.dumps(payload).encode("utf-8")
        request = Request(CONTROL_URL + path, data=body, method=method, headers={
            "Api-Key": self._api_key,
            "X-Pinecone-Api-Version": self._api_version,
            "Content-Type": "application/json",
            "Accept": "application/json",
        })
        try:
            with self._opener.open(request, timeout=timeout or self.request_timeout) as response:
                raw = response.read()
        except HTTPError as error:
            # Body, reason and URL are intentionally omitted: servers/proxies can
            # reflect headers. A 404 is the only missing-index signal we accept.
            status = error.code
            error.close()
            raise PineconeHTTPError(status) from None
        except (URLError, OSError, ValueError):
            raise SetupError("Pinecone request failed. Check HTTPS connectivity and retry.") from None
        try:
            result = json.loads(raw)
        except (ValueError, UnicodeError):
            raise SetupError("Pinecone returned an invalid JSON response.") from None
        if not isinstance(result, dict):
            raise SetupError("Pinecone returned an unexpected response shape.")
        return result

    def describe(self, index_name: str, *, timeout=None) -> dict:
        return self._request("GET", "/indexes/" + quote(index_name, safe=""), timeout=timeout)

    def create(self, payload: dict) -> dict:
        return self._request("POST", "/indexes", payload)


def build_create_payload(config) -> dict:
    settings = config.settings["pinecone"]
    return {
        "name": settings["index_name"],
        "deployment": {
            "deployment_type": "managed", "cloud": settings["cloud"], "region": settings["region"],
        },
        "read_capacity": {"mode": "OnDemand"},
        "deletion_protection": "enabled",
        "schema": {"fields": {settings["text_field"]: {
            "type": "string", "store_text": True, "full_text_search": {},
            "embed": {
                "model": settings["embedding_model"], "dimension": settings["dimension"],
                "metric": settings["metric"],
                "write_parameters": {"truncate": settings["truncate"]},
                "read_parameters": {"truncate": settings["truncate"]},
            },
        }}},
    }


def normalize_host(host: str) -> str:
    """Accept only a Pinecone hostname or an HTTPS URL without path/credentials."""
    if not isinstance(host, str) or not host:
        raise SetupError("The index describe response has no usable host yet.")
    candidate = host.removeprefix("https://")
    if not re.fullmatch(r"[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?", candidate):
        raise SetupError("Index host must be a Pinecone hostname or a plain HTTPS host URL.")
    if not candidate.endswith(".pinecone.io") or ".." in candidate:
        raise SetupError("Index host must end in .pinecone.io.")
    if len(candidate) > 253:
        raise SetupError("Index host exceeds the DNS hostname length limit.")
    if any(not label or len(label) > 63 or label.startswith("-") or label.endswith("-")
           for label in candidate.split(".")):
        raise SetupError("Index host has an invalid DNS label.")
    return candidate


def _mapping(value) -> dict:
    return value if isinstance(value, dict) else {}


def validate_index(description: dict, config, *, require_ready: bool = True) -> str | None:
    """Check the actual describe result, never infer schema from an index name."""
    expected = build_create_payload(config)
    settings = config.settings["pinecone"]
    if description.get("name") != expected["name"]:
        raise SetupError("Incompatible index: name does not match configuration.")
    deployment = _mapping(description.get("deployment"))
    for key, value in expected["deployment"].items():
        if deployment.get(key) != value:
            raise SetupError(f"Incompatible index: deployment.{key} does not match configuration.")
    capacity = _mapping(description.get("read_capacity"))
    if capacity.get("mode") != "OnDemand":
        raise SetupError("Incompatible index: read_capacity.mode must be OnDemand.")
    schema = _mapping(description.get("schema"))
    field = _mapping(_mapping(schema.get("fields")).get(settings["text_field"]))
    if field.get("type") != "string":
        raise SetupError("Incompatible index: the configured text field must be a document string field.")
    if field.get("store_text") is not True:
        raise SetupError("Incompatible index: the text field must have store_text enabled.")
    if not isinstance(field.get("full_text_search"), dict):
        raise SetupError("Incompatible index: the text field must support full_text_search.")
    actual_embed = _mapping(field.get("embed"))
    expected_embed = expected["schema"]["fields"][settings["text_field"]]["embed"]
    for key in ("model", "dimension", "metric"):
        if actual_embed.get(key) != expected_embed[key]:
            raise SetupError(f"Incompatible index: embed.{key} does not match configuration.")
    for key, role in (("write_parameters", "passage"), ("read_parameters", "query")):
        parameters = _mapping(actual_embed.get(key))
        if parameters.get("truncate") != settings["truncate"]:
            raise SetupError(f"Incompatible index: embed.{key}.truncate does not match configuration.")
        if parameters.get("dimension", settings["dimension"]) != settings["dimension"]:
            raise SetupError(f"Incompatible index: embed.{key}.dimension does not match configuration.")
        if parameters.get("input_type", role) != role:
            raise SetupError(f"Incompatible index: embed.{key}.input_type is not the retrieval role.")
    host = normalize_host(description["host"]) if description.get("host") else None
    configured_host = settings.get("index_host")
    if configured_host and host and normalize_host(configured_host) != host:
        raise SetupError("Incompatible index: configured index_host does not match the describe host.")
    if require_ready:
        if _mapping(description.get("status")).get("ready") is not True:
            raise SetupError("The index is not ready yet. Retry --check after initialization finishes.")
        if host is None:
            raise SetupError("The index describe response has no usable host yet.")
    return host


def ensure_index(config, client, *, create: bool, wait_timeout: float = 120,
                 poll_interval: float = 2) -> dict:
    """Only create on a genuine 404, and never modify an existing index."""
    name = config.settings["pinecone"]["index_name"]
    try:
        current = client.describe(name)
    except PineconeHTTPError as error:
        if error.status != 404:
            raise
        if not create:
            raise SetupError("Index not found. Preview the settings, then use --create to create it.") from None
        client.create(build_create_payload(config))
        current = None
    if not create:
        validate_index(current, config)
        return current

    deadline = time.monotonic() + wait_timeout
    while True:
        if current is not None:
            validate_index(current, config, require_ready=False)
            if _mapping(current.get("status")).get("ready") is True:
                validate_index(current, config)
                return current
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise SetupError("Timed out waiting for index readiness. Run --check later; nothing was deleted.")
        if current is not None:
            time.sleep(min(poll_interval, remaining))
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise SetupError("Timed out waiting for index readiness. Run --check later; nothing was deleted.")
        try:
            current = client.describe(name, timeout=min(30, remaining))
        except PineconeHTTPError as error:
            # Creation can briefly precede describe visibility. This path only
            # polls; it never issues a second POST, even after another 404.
            if error.status != 404:
                raise
            time.sleep(min(poll_interval, max(0, deadline - time.monotonic())))
            current = None


def load_app_config(config_path=None, secrets_path=None):
    # Permit direct execution from outside the project directory.
    project_root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(project_root))
    from amgen_explorer.config import load_config
    return load_config(config_path=config_path, secrets_path=secrets_path)


def _positive_seconds(value: str) -> float:
    result = float(value)
    if not math.isfinite(result) or result <= 0:
        raise argparse.ArgumentTypeError("must be a finite positive number of seconds")
    return result


def _redact(message: str, config) -> str:
    for secret in (config.pinecone_api_key, config.openai_api_key):
        if secret:
            message = message.replace(secret, "[REDACTED]")
    return message


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--dry-run", action="store_true", help="print the plan without network calls (default)")
    modes.add_argument("--check", action="store_true", help="read and validate the existing index")
    modes.add_argument("--create", action="store_true", help="create only if absent, then wait for readiness")
    parser.add_argument("--config", type=Path, help="alternative application TOML")
    parser.add_argument("--secrets", type=Path, help="alternative local secrets TOML; never prints its contents")
    parser.add_argument("--timeout", type=_positive_seconds, default=120, help="readiness wait budget in seconds")
    parser.add_argument("--poll-interval", type=_positive_seconds, default=2, help="readiness polling seconds")
    parser.add_argument("--request-timeout", type=_positive_seconds, default=30, help="initial HTTP request timeout")
    args = parser.parse_args(argv)
    try:
        config = load_app_config(args.config, args.secrets)
    except (OSError, ValueError, TypeError):
        # Parser errors may reproduce a secret-bearing TOML line.
        print("Configuration could not be loaded. Check app TOML and local secrets TOML syntax.", file=sys.stderr)
        return 1
    try:
        errors = config.validate(require_secrets=args.check or args.create)
        if errors:
            raise SetupError("Configuration errors: " + "; ".join(errors))
        if not (args.check or args.create):
            plan = {"method": "POST", "url": CONTROL_URL + "/indexes",
                    "api_version": config.settings["pinecone"]["api_version"],
                    "body": build_create_payload(config)}
            print("Dry run: no API calls, index creation, document upload, or configuration writes.")
            print(_redact(json.dumps(plan, indent=2), config))
            return 0
        client = PineconeControlPlane(config.pinecone_api_key, config.settings["pinecone"]["api_version"],
                                     request_timeout=args.request_timeout)
        result = ensure_index(config, client, create=args.create,
                              wait_timeout=args.timeout, poll_interval=args.poll_interval)
        host = normalize_host(result["host"])
        print("Index is ready and matches the configured document schema and embedding profile.")
        print("Host verified from Pinecone's describe response:")
        print(_redact(f'index_host = "{host}"', config))
        print("Save that value under [pinecone] in your app TOML. No local configuration was changed.")
        print("The index check does not verify an uploaded corpus; no documents or namespace were activated.")
        return 0
    except SetupError as error:
        print(_redact(str(error), config), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
