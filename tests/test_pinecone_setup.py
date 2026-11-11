"""Offline bootstrap tests. Every credential and HTTP response here is synthetic."""

import io
import os
from pathlib import Path
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from types import SimpleNamespace
from unittest.mock import Mock, patch
from urllib.error import HTTPError, URLError

from scripts import setup_pinecone as setup


def fake_config():
    return SimpleNamespace(
        settings={"pinecone": {
            "api_family": "documents", "api_version": "2026-07",
            "index_name": "test-medicines", "index_host": "",
            "cloud": "aws", "region": "us-east-1",
            "embedding_model": "llama-text-embed-v2", "text_field": "chunk_text",
            "dimension": 1024, "metric": "cosine", "truncate": "NONE",
        }},
        pinecone_api_key="synthetic-pinecone-secret",
        openai_api_key="synthetic-openai-secret",
        validate=Mock(return_value=[]),
    )


def description(config=None, ready=True):
    result = setup.build_create_payload(config or fake_config())
    result["host"] = "test-medicines-abc123.svc.us-east-1.pinecone.io"
    result["status"] = {"ready": ready, "state": "Ready" if ready else "Initializing"}
    result["schema"]["fields"]["chunk_text"]["full_text_search"] = {
        "language": "en", "stemming": False, "stop_words": False,
    }
    return result


class BootstrapTests(unittest.TestCase):
    def test_create_payload_uses_document_api_schema(self):
        self.assertEqual(setup.build_create_payload(fake_config()), {
            "name": "test-medicines",
            "deployment": {"deployment_type": "managed", "cloud": "aws", "region": "us-east-1"},
            "read_capacity": {"mode": "OnDemand"},
            "deletion_protection": "enabled",
            "schema": {"fields": {"chunk_text": {
                "type": "string", "store_text": True, "full_text_search": {},
                "embed": {"model": "llama-text-embed-v2", "dimension": 1024,
                          "metric": "cosine", "write_parameters": {"truncate": "NONE"},
                          "read_parameters": {"truncate": "NONE"}},
            }}},
        })

    def test_default_and_explicit_dry_run_make_no_http_calls(self):
        for args in ([], ["--dry-run"]):
            out = io.StringIO()
            with patch.object(setup, "load_app_config", return_value=fake_config()), \
                 patch.object(setup, "PineconeControlPlane") as client, redirect_stdout(out):
                self.assertEqual(setup.main(args), 0)
            client.assert_not_called()
            self.assertIn('"truncate": "NONE"', out.getvalue())
            self.assertNotIn("synthetic-pinecone-secret", out.getvalue())
            self.assertNotIn("synthetic-openai-secret", out.getvalue())

    def test_check_missing_never_creates(self):
        client = Mock()
        client.describe.side_effect = setup.PineconeHTTPError(404)
        with self.assertRaisesRegex(setup.SetupError, "--create"):
            setup.ensure_index(fake_config(), client, create=False)
        client.create.assert_not_called()

    def test_auth_permission_and_server_errors_never_create(self):
        for status in (401, 403, 429, 500, 503):
            client = Mock()
            client.describe.side_effect = setup.PineconeHTTPError(status)
            with self.assertRaises(setup.PineconeHTTPError):
                setup.ensure_index(fake_config(), client, create=True)
            client.create.assert_not_called()

    def test_create_after_404_then_readiness_poll(self):
        cfg, client = fake_config(), Mock()
        client.describe.side_effect = [setup.PineconeHTTPError(404), description(ready=False), description()]
        with patch.object(setup.time, "sleep") as sleep:
            actual = setup.ensure_index(cfg, client, create=True)
        client.create.assert_called_once_with(setup.build_create_payload(cfg))
        self.assertEqual(actual["host"], description()["host"])
        self.assertEqual(client.describe.call_count, 3)
        sleep.assert_called_once()

    def test_create_response_is_not_used_as_verified_host(self):
        client = Mock()
        client.describe.side_effect = [setup.PineconeHTTPError(404), description()]
        client.create.return_value = {"host": "unverified.example.com"}
        self.assertEqual(setup.ensure_index(fake_config(), client, create=True)["host"], description()["host"])

    def test_post_failure_is_not_retried(self):
        client = Mock()
        client.describe.side_effect = setup.PineconeHTTPError(404)
        client.create.side_effect = setup.PineconeHTTPError(500)
        with self.assertRaises(setup.PineconeHTTPError):
            setup.ensure_index(fake_config(), client, create=True)
        client.create.assert_called_once()

    def test_initial_visibility_404_does_not_create_twice(self):
        client = Mock()
        client.describe.side_effect = [setup.PineconeHTTPError(404), setup.PineconeHTTPError(404), description()]
        with patch.object(setup.time, "sleep"):
            setup.ensure_index(fake_config(), client, create=True)
        client.create.assert_called_once()

    def test_existing_compatible_index_is_not_recreated(self):
        client = Mock()
        client.describe.return_value = description()
        setup.ensure_index(fake_config(), client, create=True)
        client.create.assert_not_called()

    def test_mismatched_model_dimension_metric_and_truncation_rejected(self):
        changes = {"model": "different-model", "dimension": 512, "metric": "dotproduct",
                   "write_parameters": {"truncate": "END"}, "read_parameters": {"truncate": "END"}}
        for key, wrong in changes.items():
            result = description()
            result["schema"]["fields"]["chunk_text"]["embed"][key] = wrong
            with self.assertRaisesRegex(setup.SetupError, key):
                setup.validate_index(result, fake_config())

    def test_legacy_schema_missing_text_and_nonstored_text_rejected(self):
        legacy = description()
        legacy.pop("schema")
        missing = description()
        missing["schema"]["fields"] = {}
        nonstored = description()
        nonstored["schema"]["fields"]["chunk_text"]["store_text"] = False
        for result in (legacy, missing, nonstored):
            with self.assertRaises(setup.SetupError):
                setup.validate_index(result, fake_config())

    def test_check_rejects_initializing_or_hostless_index(self):
        for result in (description(ready=False), dict(description(), host=None)):
            client = Mock()
            client.describe.return_value = result
            with self.assertRaises(setup.SetupError):
                setup.ensure_index(fake_config(), client, create=False)

    def test_existing_incompatible_index_is_never_modified(self):
        client = Mock()
        wrong = description()
        wrong["schema"]["fields"]["chunk_text"]["embed"]["dimension"] = 768
        client.describe.return_value = wrong
        with self.assertRaises(setup.SetupError):
            setup.ensure_index(fake_config(), client, create=True)
        client.create.assert_not_called()

    def test_wrong_region_or_configured_host_rejected(self):
        wrong = description()
        wrong["deployment"]["region"] = "us-west-2"
        with self.assertRaisesRegex(setup.SetupError, "region"):
            setup.validate_index(wrong, fake_config())
        cfg = fake_config()
        cfg.settings["pinecone"]["index_host"] = "another.svc.pinecone.io"
        with self.assertRaisesRegex(setup.SetupError, "host"):
            setup.validate_index(description(), cfg)

    def test_only_pinecone_https_hosts_are_accepted(self):
        invalid = ["evil.example.com", "pinecone.io.evil.example", "https://evil.example",
                   "https://x.pinecone.io/path", "http://x.pinecone.io", "x.pinecone.io:443",
                   "https://x.pinecone.io@evil.example", "https://x.pinecone.io/?key=secret"]
        for host in invalid:
            with self.assertRaises(setup.SetupError):
                setup.normalize_host(host)
        self.assertEqual(setup.normalize_host("https://x.svc.pinecone.io"), "x.svc.pinecone.io")

    def test_poll_timeout_is_bounded(self):
        client = Mock()
        client.describe.return_value = description(ready=False)
        with patch.object(setup.time, "monotonic", side_effect=[0, 2]), \
             self.assertRaisesRegex(setup.SetupError, "Timed out"):
            setup.ensure_index(fake_config(), client, create=True, wait_timeout=1)
        client.create.assert_not_called()

    def test_cli_prints_only_verified_host_and_does_not_save_config(self):
        out = io.StringIO()
        with patch.object(setup, "load_app_config", return_value=fake_config()), \
             patch.object(setup, "PineconeControlPlane") as factory, redirect_stdout(out):
            factory.return_value.describe.return_value = description()
            self.assertEqual(setup.main(["--check"]), 0)
        self.assertIn('index_host = "test-medicines-abc123.svc.us-east-1.pinecone.io"', out.getvalue())
        self.assertIn("Save", out.getvalue())

    def test_cli_redacts_keys_in_error_messages(self):
        cfg = fake_config()
        cfg.validate.return_value = ["Bad setting " + cfg.pinecone_api_key + " " + cfg.openai_api_key]
        err = io.StringIO()
        with patch.object(setup, "load_app_config", return_value=cfg), redirect_stderr(err):
            self.assertEqual(setup.main([]), 1)
        self.assertNotIn(cfg.pinecone_api_key, err.getvalue())
        self.assertNotIn(cfg.openai_api_key, err.getvalue())

    def test_loader_failure_does_not_echo_exception_source(self):
        err = io.StringIO()
        with patch.object(setup, "load_app_config", side_effect=ValueError("synthetic-secret")), \
             redirect_stderr(err):
            self.assertEqual(setup.main([]), 1)
        self.assertNotIn("synthetic-secret", err.getvalue())

    def test_real_loader_integration_uses_temporary_empty_secrets(self):
        # Explicit path + cleared environment guarantees that this test never
        # reads the user's .streamlit/secrets.toml or environment credentials.
        with tempfile.TemporaryDirectory() as directory:
            secrets = Path(directory) / "empty-secrets.toml"
            secrets.write_text('PINECONE_API_KEY = ""\nOPENAI_API_KEY = ""\n', encoding="utf-8")
            with patch.dict(os.environ, {}, clear=True), \
                 patch.object(setup, "PineconeControlPlane") as client, \
                 redirect_stdout(io.StringIO()):
                self.assertEqual(setup.main(["--dry-run", "--secrets", str(secrets)]), 0)
            client.assert_not_called()


class TransportTests(unittest.TestCase):
    def test_request_uses_fixed_https_control_host_and_version(self):
        response = Mock()
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        response.read.return_value = b'{"name":"test-medicines"}'
        opener = Mock()
        opener.open.return_value = response
        with patch.object(setup, "build_opener", return_value=opener):
            client = setup.PineconeControlPlane("synthetic-secret", "2026-07")
            client.describe("name/with?separators")
        req = opener.open.call_args.args[0]
        self.assertEqual(req.full_url, "https://api.pinecone.io/indexes/name%2Fwith%3Fseparators")
        self.assertEqual(req.get_header("X-pinecone-api-version"), "2026-07")
        self.assertEqual(req.get_header("Api-key"), "synthetic-secret")

    def test_http_errors_never_include_server_body_or_key(self):
        for status in (401, 404, 500):
            opener = Mock()
            opener.open.side_effect = HTTPError("https://api.pinecone.io/indexes", status,
                                                "synthetic-secret", {}, io.BytesIO(b"synthetic-secret"))
            with patch.object(setup, "build_opener", return_value=opener):
                client = setup.PineconeControlPlane("synthetic-secret", "2026-07")
                with self.assertRaises(setup.PineconeHTTPError) as raised:
                    client.describe("test")
            self.assertEqual(raised.exception.status, status)
            self.assertNotIn("synthetic-secret", str(raised.exception))

    def test_network_errors_hide_low_level_details(self):
        opener = Mock()
        opener.open.side_effect = URLError("synthetic-secret")
        with patch.object(setup, "build_opener", return_value=opener):
            with self.assertRaises(setup.SetupError) as raised:
                setup.PineconeControlPlane("synthetic-secret", "2026-07").describe("test")
        self.assertNotIn("synthetic-secret", str(raised.exception))

    def test_redirect_handler_does_not_forward_credentials(self):
        handler = setup.NoRedirect()
        with self.assertRaises(HTTPError):
            handler.redirect_request(Mock(), Mock(), 302, "redirect", {}, "https://evil.example")


if __name__ == "__main__":
    unittest.main()
