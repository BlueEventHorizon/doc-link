import json
import subprocess
import sys
import unittest
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[3] / "plugins" / "doc-link" / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import env_check  # noqa: E402


class EnvCheckTest(unittest.TestCase):
    def test_collect_environment_reports_python_and_markdown_it_py(self):
        environment = env_check.collect_environment()
        self.assertEqual(set(environment), {"python", "markdown_it_py"})
        self.assertTrue(environment["markdown_it_py"])

    def test_entry_script_exits_0_with_uv_run_locked(self):
        completed = subprocess.run(
            [
                "uv",
                "run",
                "--locked",
                str(SCRIPTS_DIR / "env_check.py"),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        result = json.loads(completed.stdout)
        self.assertTrue(result["python"].startswith("3.15"))
        self.assertTrue(result["markdown_it_py"])

    def test_invalid_argument_exits_2(self):
        completed = subprocess.run(
            [
                "uv",
                "run",
                "--locked",
                str(SCRIPTS_DIR / "env_check.py"),
                "--unknown",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 2)


if __name__ == "__main__":
    unittest.main()
