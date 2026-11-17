import re
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT / "plugins" / "doc-link" / "scripts"))

from clock import utc_now  # noqa: E402


class UtcNowTest(unittest.TestCase):
    def test_is_iso_8601_in_utc_up_to_seconds(self):
        value = utc_now()
        self.assertRegex(value, r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\+00:00$")

    def test_is_the_current_time(self):
        before = datetime.now(timezone.utc).replace(microsecond=0)
        parsed = datetime.fromisoformat(utc_now())
        after = datetime.now(timezone.utc)
        self.assertEqual(parsed.utcoffset(), timedelta(0))
        self.assertLessEqual(before, parsed)
        self.assertLessEqual(parsed, after)

    def test_has_no_fractional_seconds(self):
        self.assertIsNone(re.search(r"\.\d", utc_now()))


if __name__ == "__main__":
    unittest.main()
