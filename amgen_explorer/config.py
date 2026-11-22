"""Load and validate local settings without making network calls.

Nonblank environment credentials override the ignored local secrets TOML.
Blank/whitespace environment values fall back to the file. This module never
creates resources, directories, credentials, or an active corpus.
"""

from dataclasses import dataclass, field
import os
from pathlib import Path
import re
from string import Formatter
import tomllib
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
_SCHEMA = {
    "app": {"name": str, "mode": str, "auth_enabled": bool,
            "auto_create_index": bool, "auto_reindex": bool},
    "paths": {name: str for name in (
        "source_dir", "xml_template", "xml_output", "extraction_report", "corpus_dir",
        "review_database", "ingestion_database", "manifest_dir", "active_corpus_manifest")},
    "pinecone": {
        "api_family": str, "api_version": str, "index_name": str, "index_host": str,
        "cloud": str, "region": str, "embedding_model": str, "text_field": str,
        "dimension": int, "metric": str, "truncate": str, "max_input_tokens": int,
        "batch_size": int, "max_batch_bytes": int, "namespace_strategy": str,
        "namespace_prefix": str},
    "chunking": {"strategy": str, "target_tokens": int, "overlap_tokens": int,
                 "prefix_template": str},
    "retrieval": {"top_k": int, "evidence_token_budget": int},
    "openai": {"provider": str, "api": str, "model": str, "reasoning_effort": str,
               "max_output_tokens": int, "request_timeout_seconds": int,
               "store_responses": bool},
}
_OPTIONAL_SCHEMA = {
    'reliability': {key: int for key in ('response_deadline_seconds', 'max_attempts',
        'retry_budget_seconds', 'backoff_base_seconds', 'backoff_cap_seconds')},
    'search': {'result_limit': int, 'semantic_candidates': int},
}


def _structure_errors(settings: dict[str, Any]) -> list[str]:
    errors = []
    if set(settings) - set(_SCHEMA) - set(_OPTIONAL_SCHEMA):
        errors.append("Unknown configuration table; remove unsupported settings.")
    for table, fields in _SCHEMA.items():
        values = settings.get(table)
        if not isinstance(values, dict):
            errors.append(f"[{table}] must be present and contain a TOML table.")
            continue
        if set(values) - set(fields):
            errors.append(f"[{table}] contains unsupported fields.")
        for name, expected_type in fields.items():
            if name not in values:
                errors.append(f"Missing setting: {table}.{name}.")
            elif type(values[name]) is not expected_type:
                errors.append(f"{table}.{name} must be {expected_type.__name__}.")
    for table, fields in _OPTIONAL_SCHEMA.items():
        if table not in settings:
            continue
        values = settings[table]
        if not isinstance(values, dict):
            errors.append(f'[{table}] must contain a TOML table.')
            continue
        if set(values) - set(fields):
            errors.append(f'[{table}] contains unsupported fields.')
        for key, value in values.items():
            if key in fields and type(value) is not fields[key]:
                errors.append(f'{table}.{key} must be {fields[key].__name__}.')
    return errors


def _read_toml(path: Path, label: str, *, optional: bool = False) -> dict[str, Any]:
    try:
        with path.open("rb") as handle:
            return tomllib.load(handle)
    except FileNotFoundError:
        if optional:
            return {}
        raise ValueError(f"{label} file does not exist.") from None
    except (tomllib.TOMLDecodeError, UnicodeDecodeError):
        # TOML parser diagnostics can contain a source line with credentials.
        raise ValueError(f"Unable to parse {label} TOML; check its syntax locally.") from None
    except OSError:
        raise ValueError(f"Unable to read {label} file; check local permissions.") from None


def _root_path(value: str | Path) -> Path:
    path = Path(value).expanduser()
    return (path if path.is_absolute() else ROOT / path).resolve()


@dataclass
class AppConfig:
    settings: dict[str, Any]
    root: Path
    pinecone_api_key: str | None = field(default=None, repr=False)
    openai_api_key: str | None = field(default=None, repr=False)

    def path(self, name: str) -> Path:
        """Resolve an application data path inside this repository."""
        value = self.settings["paths"][name]
        path = (self.root / value).resolve()
        if not value.strip() or not path.is_relative_to(self.root):
            raise ValueError(f"paths.{name} must resolve inside the repository.")
        return path

    def validate(self, *, require_secrets: bool = False, require_chat: bool = False,
                 require_host: bool = False) -> list[str]:
        """Return sanitized errors, never key values. No filesystem writes/network.

        require_secrets requires the Pinecone key. require_chat separately requires
        the OpenAI key and model. require_host is for a configured data-plane host.
        None of these checks prove account access, ingestion, or live app readiness.
        """
        errors = _structure_errors(self.settings)
        if errors:
            return errors
        from .reliability import settings_for
        reliability = settings_for(self.settings)
        for key in ('response_deadline_seconds', 'retry_budget_seconds'):
            if not 1 <= reliability[key] <= 300:
                errors.append(f'reliability.{key} must be between 1 and 300.')
        if not 1 <= reliability['max_attempts'] <= 6:
            errors.append('reliability.max_attempts must be between 1 and 6.')
        if not 1 <= reliability['backoff_base_seconds'] <= reliability['backoff_cap_seconds'] <= 60:
            errors.append('reliability backoff must satisfy 1 <= base <= cap <= 60 seconds.')
        for key, value in self.settings.get('search', {}).items():
            if not 1 <= value <= 100:
                errors.append(f'search.{key} must be between 1 and 100.')
        app, pc = self.settings["app"], self.settings["pinecone"]
        chunk, retrieval, ai = (self.settings[k] for k in ("chunking", "retrieval", "openai"))
        if app["mode"] not in {"local", "hosted"}:
            errors.append("app.mode must be local or hosted.")
        elif app["mode"] == "local" and app["auth_enabled"]:
            errors.append("Local mode must keep auth_enabled=false so the offline workflow remains usable.")
        elif app["mode"] == "hosted" and not app["auth_enabled"]:
            errors.append("Hosted mode requires auth_enabled=true.")
        if not app["name"].strip():
            errors.append("app.name must be nonempty.")
        for name in ("auto_create_index", "auto_reindex"):
            if app[name]:
                errors.append(f"app.{name} must remain false; cloud changes require an explicit action.")
        for name in self.settings["paths"]:
            try:
                self.path(name)
            except (ValueError, OSError):
                errors.append(f"paths.{name} must resolve inside the repository.")

        profile = {"api_family": "documents", "api_version": "2026-07",
                   "embedding_model": "llama-text-embed-v2", "text_field": "chunk_text",
                   "dimension": 1024, "metric": "cosine",
                   "max_input_tokens": 2048, "namespace_strategy": "local_manifest"}
        for name, expected in profile.items():
            if pc[name] != expected:
                errors.append(f"pinecone.{name} is incompatible with the supported Documents API embedding profile.")
        if pc["truncate"] not in {"NONE", "END"}:
            errors.append("pinecone.truncate must match the existing index: NONE or END; local byte limits prevent truncation.")
        if not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,43}[a-z0-9])?", pc["index_name"]):
            errors.append("pinecone.index_name must use 1–45 lowercase letters, digits, or internal hyphens.")
        if pc["cloud"] not in {"aws", "gcp", "azure"} or not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", pc["region"]):
            errors.append("pinecone.cloud/region must identify a supported deployment; verify account availability before creation.")
        # Hostnames only; callers construct HTTPS themselves. Never accept an
        # arbitrary URL that could receive the Pinecone authorization header.
        host = pc["index_host"]
        label = r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?"
        if host and (len(host) > 253 or not re.fullmatch(rf"(?:{label}\.)+pinecone\.io", host)):
            errors.append("pinecone.index_host must be a bare *.pinecone.io hostname without scheme, credentials, port, or path.")
        elif require_host and not host:
            errors.append("pinecone.index_host is missing; copy the hostname returned by describe-index.")
        if not 1 <= pc["batch_size"] <= 96:
            errors.append("pinecone.batch_size must be between 1 and 96.")
        if not 1 <= pc["max_batch_bytes"] <= 2_000_000:
            errors.append("pinecone.max_batch_bytes must be between 1 and 2000000.")
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,31}", pc["namespace_prefix"]):
            errors.append("pinecone.namespace_prefix must contain lowercase letters, digits, or hyphens.")
        if chunk["strategy"] != "section_aware":
            errors.append("chunking.strategy must be section_aware.")
        if not 300 <= chunk["target_tokens"] <= 1200:
            errors.append("chunking.target_tokens must be between 300 and 1200.")
        if not 0 <= chunk["overlap_tokens"] <= 200 or chunk["overlap_tokens"] >= chunk["target_tokens"]:
            errors.append("chunking.overlap_tokens must be between 0 and 200 and below target_tokens.")
        try:
            parts = list(Formatter().parse(chunk["prefix_template"]))
            fields = {part[1] for part in parts if part[1] is not None}
            if fields != {"product_name", "section_title"} or any(part[2] or part[3] for part in parts):
                raise ValueError
        except ValueError:
            errors.append("chunking.prefix_template must contain only the product_name and section_title placeholders, without formatting modifiers.")
        if not 1 <= retrieval["top_k"] <= 100:
            errors.append("retrieval.top_k must be between 1 and 100.")
        if retrieval["evidence_token_budget"] < 1:
            errors.append("retrieval.evidence_token_budget must be positive.")
        if ai["provider"] != "openai" or ai["api"] != "responses":
            errors.append("openai.provider/api must select openai and responses.")
        if require_chat and not ai["model"].strip():
            errors.append("openai.model is required for chat.")
        if ai["model"] and not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]*", ai["model"]):
            errors.append("openai.model must be a model identifier without whitespace or URL components.")
        if ai["reasoning_effort"] not in {"none", "minimal", "low", "medium", "high", "xhigh", "max"}:
            errors.append("openai.reasoning_effort is unsupported; check the selected model's documented capabilities.")
        elif ai["model"] == "gpt-6.1-sol" and ai["reasoning_effort"] not in {"low", "medium", "high", "xhigh", "max"}:
            errors.append("openai.reasoning_effort for gpt-6.1-sol must be low, medium, high, xhigh, or max.")
        if ai["max_output_tokens"] < 1 or not 1 <= ai["request_timeout_seconds"] <= 300:
            errors.append("openai output tokens must be positive and timeout must be 1–300 seconds.")
        if ai["store_responses"]:
            errors.append("openai.store_responses must remain false for this local configuration.")
        if require_secrets and not self.pinecone_api_key:
            errors.append("PINECONE_API_KEY is missing.")
        if require_chat and not self.openai_api_key:
            errors.append("OPENAI_API_KEY is missing.")
        return errors


def load_config(config_path: str | Path | None = None,
                secrets_path: str | Path | None = None) -> AppConfig:
    """Load explicit complete settings and optional credentials, with safe errors."""
    settings = _read_toml(_root_path(config_path or "config/app.toml"), "configuration")
    errors = _structure_errors(settings)
    if errors:
        raise ValueError(" ".join(errors))
    mode = os.environ.get("AMGEN_APP_MODE")
    if mode is not None:
        if mode not in {"local", "hosted"}:
            raise ValueError("AMGEN_APP_MODE must be local or hosted.")
        settings["app"]["mode"] = mode
        settings["app"]["auth_enabled"] = mode == "hosted"
    names = ("PINECONE_API_KEY", "OPENAI_API_KEY")
    values = {name: os.environ.get(name, "").strip() for name in names}
    if not all(values.values()):
        secrets = _read_toml(_root_path(secrets_path or ".streamlit/secrets.toml"), "secrets", optional=True)
        for name in names:
            if values[name]:
                continue
            value = secrets.get(name, "")
            if not isinstance(value, str):
                raise ValueError(f"{name} must be a TOML string.")
            values[name] = value.strip()
    return AppConfig(settings=settings, root=ROOT,
                     pinecone_api_key=values["PINECONE_API_KEY"] or None,
                     openai_api_key=values["OPENAI_API_KEY"] or None)
