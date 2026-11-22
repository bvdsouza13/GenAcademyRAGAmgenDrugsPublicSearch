"""Offline contract tests; every credential is synthetic and temporary."""

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from amgen_explorer.config import load_config


ROOT = Path(__file__).resolve().parents[1]


class ConfigTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.secrets = self.directory / "secrets.toml"
        self.environment = patch.dict(os.environ, {}, clear=True)
        self.environment.start()
        self.addCleanup(self.environment.stop)

    def load(self):
        return load_config(secrets_path=self.secrets)

    def test_missing_keys_allow_offline_validation_but_block_service_use(self):
        cfg = self.load()
        self.assertEqual(cfg.validate(), [])
        self.assertTrue(any("PINECONE_API_KEY" in e for e in cfg.validate(require_secrets=True)))
        self.assertTrue(any("OPENAI_API_KEY" in e for e in cfg.validate(require_chat=True)))

    def test_nonempty_environment_takes_precedence_over_secret_file(self):
        self.secrets.write_text('PINECONE_API_KEY="file-pc"\nOPENAI_API_KEY="file-ai"\n')
        with patch.dict(os.environ, {"PINECONE_API_KEY": "env-pc", "OPENAI_API_KEY": "env-ai"}):
            cfg = self.load()
        self.assertEqual(cfg.pinecone_api_key, "env-pc")
        self.assertEqual(cfg.openai_api_key, "env-ai")

    def test_blank_environment_falls_back_to_secret_file(self):
        self.secrets.write_text('PINECONE_API_KEY="file-pc"\nOPENAI_API_KEY="file-ai"\n')
        with patch.dict(os.environ, {"PINECONE_API_KEY": " ", "OPENAI_API_KEY": ""}):
            cfg = self.load()
        self.assertEqual(cfg.pinecone_api_key, "file-pc")
        self.assertEqual(cfg.openai_api_key, "file-ai")

    def test_secret_values_are_absent_from_representation_and_diagnostics(self):
        self.secrets.write_text('PINECONE_API_KEY="secret-pc-unique"\nOPENAI_API_KEY="secret-ai-unique"\n')
        cfg = self.load()
        diagnostics = repr(cfg) + str(cfg.validate(require_chat=True, require_host=True))
        self.assertNotIn("secret-pc-unique", diagnostics)
        self.assertNotIn("secret-ai-unique", diagnostics)
        self.assertNotIn("PINECONE_API_KEY", cfg.settings)

    def test_invalid_secret_toml_is_reported_without_its_source(self):
        self.secrets.write_text('PINECONE_API_KEY="secret-unterminated')
        with self.assertRaises(ValueError) as error:
            self.load()
        self.assertNotIn("secret-unterminated", str(error.exception))

    def test_paths_and_relative_config_are_independent_of_working_directory(self):
        previous = Path.cwd()
        try:
            os.chdir(self.directory)
            cfg = load_config("config/app.toml", secrets_path=self.secrets)
        finally:
            os.chdir(previous)
        self.assertEqual(cfg.root, ROOT)
        self.assertEqual(cfg.path("source_dir"), ROOT / "Documents")
        self.assertEqual(cfg.path("xml_output"), ROOT / "XML" / "AmgenProducts.xml")

    def test_path_escape_is_rejected(self):
        cfg = self.load()
        cfg.settings["paths"]["xml_output"] = "../outside.xml"
        self.assertTrue(any("paths.xml_output" in e for e in cfg.validate()))

    def test_model_and_dimension_mismatch_block_configuration(self):
        for name, value in (("embedding_model", "different-model"), ("dimension", 512), ("metric", "dotproduct")):
            with self.subTest(name=name):
                cfg = self.load()
                cfg.settings["pinecone"][name] = value
                self.assertTrue(cfg.validate())

    def test_invalid_chunk_bounds_and_overlap_are_rejected(self):
        for target, overlap in ((600, -1), (600, 201), (299, 80), (1201, 80), (80, 80)):
            with self.subTest(target=target, overlap=overlap):
                cfg = self.load()
                cfg.settings["chunking"].update(target_tokens=target, overlap_tokens=overlap)
                self.assertTrue(cfg.validate())

    def test_valid_host_is_optional_until_live_connection_is_requested(self):
        cfg = self.load()
        cfg.settings["pinecone"]["index_host"] = ""
        self.assertFalse(cfg.validate())
        self.assertTrue(cfg.validate(require_host=True))
        cfg.settings["pinecone"]["index_host"] = "amgen-123.svc.us-east1.pinecone.io"
        self.assertFalse(cfg.validate(require_host=True))

    def test_host_cannot_redirect_credentials_to_another_destination(self):
        for host in ("https://legit.pinecone.io", "evil.example", "pinecone.io.evil.example", "user@svc.pinecone.io", "svc.pinecone.io/path", "svc.pinecone.io:443", "svc.pinecone.io\n"):
            with self.subTest(host=host):
                cfg = self.load()
                cfg.settings["pinecone"]["index_host"] = host
                self.assertTrue(cfg.validate())

    def test_unknown_fields_and_wrong_types_are_rejected_safely(self):
        original = (ROOT / "config/app.toml").read_text()
        for content in (original + '\nunknown-secret-name="do-not-print"\n', original.replace("batch_size = 64", "batch_size = true")):
            config = self.directory / "custom.toml"
            config.write_text(content)
            with self.assertRaises(ValueError) as error:
                load_config(config, self.secrets)
            self.assertNotIn("do-not-print", str(error.exception))
            self.assertNotIn("unknown-secret-name", str(error.exception))

    def test_automatic_cloud_mutations_and_hosted_mode_are_rejected(self):
        for key, value in (("auto_create_index", True), ("auto_reindex", True), ("mode", "hosted"), ("auth_enabled", True)):
            with self.subTest(key=key):
                cfg = self.load()
                cfg.settings["app"][key] = value
                self.assertTrue(cfg.validate())

    def test_hosted_mode_is_valid_only_with_auth_enabled(self):
        cfg = self.load()
        cfg.settings["app"].update(mode="hosted", auth_enabled=True)
        self.assertFalse(cfg.validate())
        cfg.settings["app"]["auth_enabled"] = False
        self.assertTrue(any("Hosted mode requires auth_enabled=true" in error for error in cfg.validate()))

    def test_default_chat_model_accepts_max_reasoning(self):
        cfg = self.load()
        cfg.settings["openai"]["reasoning_effort"] = "max"
        self.assertEqual(cfg.validate(), [])

    def test_default_chat_model_rejects_unsupported_reasoning_efforts(self):
        for effort in ("none", "minimal"):
            with self.subTest(effort=effort):
                cfg = self.load()
                cfg.settings["openai"]["reasoning_effort"] = effort
                self.assertTrue(any("reasoning_effort" in e for e in cfg.validate()))

    def test_cli_distinguishes_offline_configuration_from_service_readiness(self):
        command = [sys.executable, str(ROOT / "scripts/check_config.py"), "--check", "--secrets", str(self.secrets)]
        result = subprocess.run(command, text=True, capture_output=True, cwd=self.directory)
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertIn("PINECONE_API_KEY: missing", result.stdout)
        self.assertIn("not live app readiness", result.stdout)
        required = subprocess.run(command + ["--require-secrets"], text=True, capture_output=True, cwd=self.directory)
        self.assertEqual(required.returncode, 1)

    def test_cli_never_prints_credentials(self):
        self.secrets.write_text('PINECONE_API_KEY="unique-cli-pc"\nOPENAI_API_KEY="unique-cli-ai"\n')
        result = subprocess.run([sys.executable, str(ROOT / "scripts/check_config.py"), "--secrets", str(self.secrets), "--require-secrets"], text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotIn("unique-cli", result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
