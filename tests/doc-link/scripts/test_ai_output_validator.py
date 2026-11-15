import re
import sys
import unittest
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[3] / "plugins" / "doc-link" / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import ai_output_validator as v  # noqa: E402

PURPOSE_H = 260
ARRAY_H = 13


def valid_result(**overrides):
    result = {
        "title": "Title",
        "purpose": "a" * 10,
        "summary": ["s"] * 5,
        "applicable_tasks": ["t"],
        "keywords": ["k"] * 5,
    }
    result.update(overrides)
    return result


class BoundaryTest(unittest.TestCase):
    def test_valid_result_is_accepted(self):
        self.assertEqual(v.validate_generated_fields(valid_result()), [])

    def test_internal_limits(self):
        self.assertEqual(v.internal_limit(200), PURPOSE_H)
        self.assertEqual(v.internal_limit(10), ARRAY_H)

    def test_purpose_boundaries(self):
        for length, accepted in [
            (200, True),
            (201, True),
            (PURPOSE_H, True),
            (PURPOSE_H + 1, False),
        ]:
            with self.subTest(length=length):
                reasons = v.validate_generated_fields(
                    valid_result(purpose="a" * length)
                )
                self.assertEqual(reasons == [], accepted, reasons)

    def test_array_boundaries(self):
        for name in ("summary", "applicable_tasks", "keywords"):
            for count, accepted in [
                (10, True),
                (11, True),
                (ARRAY_H, True),
                (ARRAY_H + 1, False),
            ]:
                with self.subTest(name=name, count=count):
                    reasons = v.validate_generated_fields(
                        valid_result(**{name: ["x"] * count})
                    )
                    self.assertEqual(reasons == [], accepted, reasons)

    def test_array_minimums(self):
        for name, minimum in [("summary", 5), ("applicable_tasks", 1), ("keywords", 5)]:
            with self.subTest(name=name):
                self.assertEqual(
                    v.validate_generated_fields(
                        valid_result(**{name: ["x"] * minimum})
                    ),
                    [],
                )
                reasons = v.validate_generated_fields(
                    valid_result(**{name: ["x"] * (minimum - 1)})
                )
                self.assertEqual(len(reasons), 1)
                self.assertIn(name, reasons[0])

    def test_element_and_title_length_not_limited(self):
        reasons = v.validate_generated_fields(
            valid_result(title="t" * 5000, summary=["s" * 5000] * 5)
        )
        self.assertEqual(reasons, [])


class InvalidInputTest(unittest.TestCase):
    def test_missing_fields_are_rejected(self):
        for name in valid_result():
            with self.subTest(name=name):
                result = valid_result()
                del result[name]
                reasons = v.validate_generated_fields(result)
                self.assertEqual(len(reasons), 1)
                self.assertIn(name, reasons[0])

    def test_wrong_types_are_rejected(self):
        cases = [
            ("title", 1),
            ("title", None),
            ("purpose", ["a"]),
            ("purpose", None),
            ("summary", "text"),
            ("summary", None),
            ("applicable_tasks", {"a": 1}),
            ("keywords", ["k", "k", "k", "k", 5]),
        ]
        for name, value in cases:
            with self.subTest(name=name, value=value):
                reasons = v.validate_generated_fields(valid_result(**{name: value}))
                self.assertEqual(len(reasons), 1)
                self.assertIn(name, reasons[0])

    def test_empty_strings_are_rejected(self):
        self.assertTrue(v.validate_generated_fields(valid_result(title="  ")))
        self.assertTrue(v.validate_generated_fields(valid_result(purpose="")))

    def test_non_object_is_rejected(self):
        self.assertTrue(v.validate_generated_fields(None))
        self.assertTrue(v.validate_generated_fields([]))

    def test_all_problems_are_reported(self):
        reasons = v.validate_generated_fields({})
        self.assertEqual(len(reasons), 5)


class CodePointCountTest(unittest.TestCase):
    def test_combining_characters_count_per_code_point(self):
        # "e" + 結合アクセント は 1 書記素・2 コードポイント。H = 260 のとき 130 個で 260
        text = "é" * 130
        self.assertEqual(v.validate_generated_fields(valid_result(purpose=text)), [])
        self.assertTrue(v.validate_generated_fields(valid_result(purpose=text + "a")))

    def test_not_utf8_byte_count(self):
        # 260 コードポイントの日本語は UTF-8 で 780 バイトだが受理される
        self.assertEqual(
            v.validate_generated_fields(valid_result(purpose="あ" * PURPOSE_H)), []
        )
        self.assertTrue(
            v.validate_generated_fields(valid_result(purpose="あ" * (PURPOSE_H + 1)))
        )

    def test_emoji_counts_as_code_points(self):
        # 家族の絵文字は 1 書記素・5 コードポイント（ZWJ を含む）。52 個で 260
        family = "\U0001f468‍\U0001f469‍\U0001f467"
        self.assertEqual(len(family), 5)
        self.assertEqual(
            v.validate_generated_fields(valid_result(purpose=family * 52)), []
        )
        self.assertTrue(
            v.validate_generated_fields(valid_result(purpose=family * 52 + "a"))
        )


class NonDisclosureTest(unittest.TestCase):
    def all_reasons(self):
        collected = []
        collected += v.validate_generated_fields(valid_result(purpose="a" * 261))
        collected += v.validate_generated_fields(valid_result(purpose="a" * 300))
        collected += v.validate_generated_fields(valid_result(purpose=None))
        collected += v.validate_generated_fields(valid_result(purpose=""))
        for name in ("summary", "applicable_tasks", "keywords"):
            collected += v.validate_generated_fields(valid_result(**{name: ["x"] * 14}))
            collected += v.validate_generated_fields(valid_result(**{name: []}))
            collected += v.validate_generated_fields(valid_result(**{name: 3}))
        collected += v.validate_generated_fields({})
        collected += v.validate_generated_fields(None)
        return collected

    def test_reasons_do_not_contain_internal_limit_factor_or_margin(self):
        reasons = self.all_reasons()
        self.assertTrue(reasons)
        for reason in reasons:
            with self.subTest(reason=reason):
                for forbidden in ("260", "13", "1.3", "margin", "tolerance", "余白"):
                    # 13 は単語としての数値だけを見る
                    pattern = r"(?<![\d.])" + re.escape(forbidden) + r"(?![\d.])"
                    self.assertIsNone(re.search(pattern, reason, re.IGNORECASE))

    def test_reason_for_over_limit_cites_only_l(self):
        reasons = v.validate_generated_fields(valid_result(purpose="a" * 261))
        self.assertEqual(reasons, ["purpose must be at most 200 characters"])
        reasons = v.validate_generated_fields(valid_result(keywords=["x"] * 14))
        self.assertEqual(reasons, ["keywords must have at most 10 items"])


if __name__ == "__main__":
    unittest.main()
