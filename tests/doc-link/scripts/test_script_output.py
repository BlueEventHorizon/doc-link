import contextlib
import io
import json
import sys
import unittest
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[3] / "plugins" / "doc-link" / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import script_output  # noqa: E402


class ScriptOutputTest(unittest.TestCase):
    def test_emit_result_writes_json_and_returns_0(self):
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            code = script_output.emit_result({"b": 1, "a": "日本語"})
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(buffer.getvalue()), {"a": "日本語", "b": 1})
        self.assertIn("日本語", buffer.getvalue())

    def test_emit_error_writes_errors_array_and_returns_1(self):
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            code = script_output.emit_error(["失敗した"])
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(buffer.getvalue()), {"errors": ["失敗した"]})


if __name__ == "__main__":
    unittest.main()
