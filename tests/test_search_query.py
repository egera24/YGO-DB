"""Unit tests for search query parser and compiler."""

from __future__ import annotations

import unittest

from ygo_app.search_query import (
    AndExpr,
    NotExpr,
    OrExpr,
    Phrase,
    SearchQueryError,
    Term,
    parse_search_query,
)


class TestParseSearchQuery(unittest.TestCase):
    def test_single_term(self):
        expr = parse_search_query("reveal")
        self.assertEqual(expr, Term("reveal"))

    def test_phrase(self):
        expr = parse_search_query('"You can reveal"')
        self.assertEqual(expr, Phrase("You can reveal"))

    def test_implicit_and(self):
        expr = parse_search_query("reveal hand")
        self.assertEqual(expr, AndExpr((Term("reveal"), Term("hand"))))

    def test_explicit_and(self):
        expr = parse_search_query("reveal AND hand")
        self.assertEqual(expr, AndExpr((Term("reveal"), Term("hand"))))

    def test_or(self):
        expr = parse_search_query("reveal OR hand")
        self.assertEqual(expr, OrExpr((Term("reveal"), Term("hand"))))

    def test_not_keyword(self):
        expr = parse_search_query("reveal NOT hand")
        self.assertEqual(
            expr, AndExpr((Term("reveal"), NotExpr(Term("hand"))))
        )

    def test_minus_not(self):
        expr = parse_search_query("reveal -hand")
        self.assertEqual(
            expr, AndExpr((Term("reveal"), NotExpr(Term("hand"))))
        )

    def test_hyphen_in_word(self):
        expr = parse_search_query("face-up")
        self.assertEqual(expr, Term("face-up"))

    def test_wildcard_term(self):
        expr = parse_search_query("millenn?um")
        self.assertEqual(expr, Term("millenn?um", wildcard=True))

    def test_parentheses(self):
        expr = parse_search_query("(reveal OR summon) hand")
        self.assertEqual(
            expr,
            AndExpr((OrExpr((Term("reveal"), Term("summon"))), Term("hand"))),
        )

    def test_or_precedence_over_and(self):
        expr = parse_search_query("a OR b AND c")
        self.assertEqual(
            expr, OrExpr((Term("a"), AndExpr((Term("b"), Term("c")))))
        )

    def test_empty_returns_none(self):
        self.assertIsNone(parse_search_query("   "))

    def test_unclosed_quote_raises(self):
        with self.assertRaises(SearchQueryError):
            parse_search_query('"open')

    def test_case_insensitive_operators(self):
        expr = parse_search_query("a or b and c")
        self.assertIsInstance(expr, OrExpr)


if __name__ == "__main__":
    unittest.main()
