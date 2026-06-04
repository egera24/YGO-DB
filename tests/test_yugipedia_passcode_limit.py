"""Tests for Yugipedia passcode list truncation (test mode)."""

import unittest

from ygo_app.yugipedia.passcodes import limit_passcode_list


def _cards(n: int) -> list[dict]:
    return [{"password": f"{i:08d}", "name": f"Card {i}"} for i in range(n)]


class TestLimitPasscodeList(unittest.TestCase):
    def test_no_limit_returns_all(self) -> None:
        cards = _cards(10)
        self.assertEqual(limit_passcode_list(cards, None), cards)
        self.assertEqual(limit_passcode_list(cards, 0), cards)

    def test_truncates_to_first_n(self) -> None:
        cards = _cards(1000)
        limited = limit_passcode_list(cards, 500)
        self.assertEqual(len(limited), 500)
        self.assertEqual(limited[0]["password"], "00000000")
        self.assertEqual(limited[-1]["password"], "00000499")

    def test_limit_larger_than_list(self) -> None:
        cards = _cards(50)
        self.assertEqual(limit_passcode_list(cards, 500), cards)


if __name__ == "__main__":
    unittest.main()
