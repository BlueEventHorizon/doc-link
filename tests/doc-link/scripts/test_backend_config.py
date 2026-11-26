"""`backend_config`（強制スイッチの設定ファイル `.doc-link/config.json`）のテスト。AC-037・AC-048。"""

import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT / "plugins" / "doc-link" / "scripts"))

import backend_config  # noqa: E402


class LoadTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)

    def write(self, data: bytes):
        path = backend_config.config_path(self.root)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    def test_config_lives_at_the_project_root_under_doc_link(self):
        self.assertEqual(
            backend_config.config_path(self.root),
            self.root / ".doc-link" / "config.json",
        )

    def test_missing_file_means_auto(self):
        config = backend_config.load(self.root)
        self.assertEqual((config.backend, config.present), ("auto", False))

    def test_toc_and_auto_are_accepted(self):
        for value in ("toc", "auto"):
            with self.subTest(value=value):
                self.write(f'{{"backend": "{value}"}}'.encode())
                config = backend_config.load(self.root)
                self.assertEqual((config.backend, config.present), (value, True))

    def test_missing_key_means_auto(self):
        self.write(b"{}")
        config = backend_config.load(self.root)
        self.assertEqual((config.backend, config.present), ("auto", True))

    def test_invalid_files_are_rejected_without_falling_back_to_auto(self):
        cases = {
            "not json": b"{backend: toc",
            "not an object": b'["toc"]',
            "unknown key": b'{"backend": "toc", "port": 1}',
            "unknown value": b'{"backend": "doc-db"}',
            "not a string": b'{"backend": true}',
            "not utf-8": b'\xff\xfe{"backend": "toc"}',
        }
        for name, data in cases.items():
            with self.subTest(name=name):
                self.write(data)
                with self.assertRaises(backend_config.BackendConfigError) as raised:
                    backend_config.load(self.root)
                self.assertIsInstance(raised.exception.errors, list)
                self.assertTrue(raised.exception.errors)
                self.assertIn(".doc-link/config.json", raised.exception.errors[0])

    def test_a_directory_in_place_of_the_file_is_rejected(self):
        backend_config.config_path(self.root).mkdir(parents=True)
        with self.assertRaises(backend_config.BackendConfigError):
            backend_config.load(self.root)

    def test_config_file_does_not_disturb_the_state_listing(self):
        import state_store

        self.write(b'{"backend": "toc"}')
        self.assertEqual(state_store.list_document_ids(self.root), [])
        self.assertEqual(state_store.list_toc_keys(self.root), [])


if __name__ == "__main__":
    unittest.main()
