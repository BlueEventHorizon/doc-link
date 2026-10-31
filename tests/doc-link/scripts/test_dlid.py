"""プラグイン共通 script `dlid.py`（DLID の認識と発行）の単体テスト。

期待値は実装ではなく、DES-008 §1・REQ-002 FR-001/FR-002・D-028 の規則から導く。
"""

import re
import sys
import unittest
from pathlib import Path
from unittest import mock

_SCRIPTS_DIR = Path(__file__).resolve().parents[3] / "plugins" / "doc-link" / "scripts"
sys.path.insert(0, str(_SCRIPTS_DIR))

import dlid  # noqa: E402

# 規則から書き起こした形式: `DLID-` と、0-9 と a-z から i・l・o・u を除いた 32 文字の 12 文字。
_ALPHABET = "0123456789" + "".join(
    c for c in "abcdefghijklmnopqrstuvwxyz" if c not in "ilou"
)
_EXPECTED_FORMAT = re.compile(r"DLID-[" + _ALPHABET + r"]{12}")


class TestAlphabetRule(unittest.TestCase):
    def test_rule_alphabet_has_32_chars(self):
        self.assertEqual(len(_ALPHABET), 32)


class TestIssueDlid(unittest.TestCase):
    def test_issued_value_matches_format(self):
        value = dlid.issue_dlid()
        self.assertIsNotNone(_EXPECTED_FORMAT.fullmatch(value), value)

    def test_issued_value_is_recognized(self):
        value = dlid.issue_dlid()
        self.assertEqual(dlid.recognize_dlid(value), value)

    def test_repeated_issue_keeps_format(self):
        values = [dlid.issue_dlid() for _ in range(2000)]
        for value in values:
            self.assertIsNotNone(_EXPECTED_FORMAT.fullmatch(value), value)
            self.assertEqual(dlid.recognize_dlid(value), value)
        # 60 ビット乱数なので、この件数で重複が出ることは実質的に無い
        self.assertEqual(len(set(values)), len(values))

    def test_uses_60_bit_secrets_random(self):
        with mock.patch.object(dlid.secrets, "randbits", return_value=0) as randbits:
            value = dlid.issue_dlid()
        randbits.assert_called_once_with(60)
        self.assertEqual(value, "DLID-000000000000")

    def test_max_60_bit_value_maps_to_last_char(self):
        with mock.patch.object(dlid.secrets, "randbits", return_value=2**60 - 1):
            value = dlid.issue_dlid()
        self.assertEqual(value, "DLID-zzzzzzzzzzzz")

    def test_each_5_bits_map_to_crockford_char_big_endian(self):
        # 値部分の各文字を 5 ビットずつ上位から並べた数を作り、同じ文字列に戻ることを確かめる
        expected_value = "0123456789ab"
        number = 0
        for c in expected_value:
            number = (number << 5) | _ALPHABET.index(c)
        with mock.patch.object(dlid.secrets, "randbits", return_value=number):
            value = dlid.issue_dlid()
        self.assertEqual(value, "DLID-" + expected_value)


class TestRecognizeDlid(unittest.TestCase):
    VALID = "DLID-7k3m9q2x4p8r"

    def test_valid_value_is_recognized(self):
        self.assertEqual(dlid.recognize_dlid(self.VALID), self.VALID)

    def test_all_alphabet_chars_are_accepted(self):
        for i in range(0, 32, 12):
            chunk = (_ALPHABET[i : i + 12] + "0" * 12)[:12]
            value = "DLID-" + chunk
            self.assertEqual(dlid.recognize_dlid(value), value)

    def test_unrecognizable_values_are_all_absent(self):
        cases = {
            # キーの欠落・null は None として渡される
            "missing_or_null": None,
            "empty": "",
            "whitespace_only": "   ",
            "whitespace_tab_newline": "\t\n",
            # 型違い
            "int": 123456789012,
            "float": 1.5,
            "bool_true": True,
            "bool_false": False,
            "list": [self.VALID],
            "dict": {"id": self.VALID},
            "bytes": self.VALID.encode(),
            # 長さ違い
            "too_short": "DLID-7k3m9q2x4p8",
            "too_long": "DLID-7k3m9q2x4p8rr",
            "prefix_only": "DLID-",
            "value_only": "7k3m9q2x4p8r",
            # プレフィックス違い
            "lower_prefix": "dlid-7k3m9q2x4p8r",
            "other_prefix": "DLIX-7k3m9q2x4p8r",
            "no_hyphen": "DLID7k3m9q2x4p8rx",
            "underscore": "DLID_7k3m9q2x4p8r",
            # 不正文字（Crockford Base32 で除かれる i・l・o・u、記号、全角）
            "char_i": "DLID-7k3m9q2x4p8i",
            "char_l": "DLID-7k3m9q2x4p8l",
            "char_o": "DLID-7k3m9q2x4p8o",
            "char_u": "DLID-7k3m9q2x4p8u",
            "symbol": "DLID-7k3m9q2x4p8-",
            "fullwidth_digit": "DLID-7k3m9q2x4p8１",
            "inner_space": "DLID-7k3m9q 2x4p8",
            # 大文字
            "upper_value": "DLID-7K3M9Q2X4P8R",
            "one_upper_char": "DLID-7k3m9q2x4p8R",
            # 前後の空白
            "leading_space": " " + self.VALID,
            "trailing_space": self.VALID + " ",
            "trailing_newline": self.VALID + "\n",
            # 複数の値
            "two_ids": self.VALID + " " + self.VALID,
        }
        for name, value in cases.items():
            with self.subTest(name=name):
                self.assertIsNone(dlid.recognize_dlid(value))


if __name__ == "__main__":
    unittest.main()
