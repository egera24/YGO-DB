"""Unit tests for search query parser and compiler."""

from __future__ import annotations

import unittest

from ygo_app.search_query import (
    AndExpr,
    BoolExpr,
    EnumExpr,
    FieldPhrase,
    FieldTerm,
    NotExpr,
    OrExpr,
    Phrase,
    RangeExpr,
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

    def test_field_term(self):
        expr = parse_search_query("name:Number")
        self.assertEqual(expr, FieldTerm("name", "Number"))

    def test_field_case_sensitive(self):
        expr = parse_search_query("name:=Number")
        self.assertEqual(
            expr, FieldTerm("name", "Number", case_sensitive=True)
        )

    def test_field_phrase(self):
        expr = parse_search_query('name:"Number 39"')
        self.assertEqual(expr, FieldPhrase("name", "Number 39"))

    def test_field_case_sensitive_phrase(self):
        expr = parse_search_query('name:="Number 39"')
        self.assertEqual(
            expr, FieldPhrase("name", "Number 39", case_sensitive=True)
        )

    def test_field_alias(self):
        expr = parse_search_query("n:Utopia")
        self.assertEqual(expr, FieldTerm("name", "Utopia"))

    def test_unknown_field_becomes_plain_term(self):
        expr = parse_search_query("foo:bar")
        self.assertEqual(expr, Term("foo:bar"))

    def test_numeric_range_exact(self):
        expr = parse_search_query("atk:3000")
        self.assertEqual(expr, RangeExpr("atk", "=", 3000, None))

    def test_numeric_range_gte(self):
        expr = parse_search_query("atk:>=3000")
        self.assertEqual(expr, RangeExpr("atk", ">=", 3000, None))

    def test_numeric_range_span(self):
        expr = parse_search_query("level:4..8")
        self.assertEqual(expr, RangeExpr("level", "..", 4, 8))

    def test_passcode_in_compound(self):
        expr = parse_search_query("name:Utopia passcode:89631139")
        self.assertEqual(
            expr,
            AndExpr(
                (
                    FieldTerm("name", "Utopia"),
                    FieldTerm("passcode", "89631139"),
                )
            ),
        )

    def test_enum_field(self):
        expr = parse_search_query("mechanic:Xyz")
        self.assertEqual(expr, EnumExpr("mechanic", "Xyz"))

    def test_marker_list(self):
        expr = parse_search_query("markers:Top,Bottom")
        self.assertEqual(
            expr, EnumExpr("marker", "Top", values=("Top", "Bottom"))
        )

    def test_bool_field(self):
        expr = parse_search_query("owned:true")
        self.assertEqual(expr, BoolExpr("owned", True))

    def test_compound_field_query(self):
        expr = parse_search_query("name:=Number mechanic:Xyz")
        self.assertEqual(
            expr,
            AndExpr(
                (
                    FieldTerm("name", "Number", case_sensitive=True),
                    EnumExpr("mechanic", "Xyz"),
                )
            ),
        )

    def test_name_or_after_colon_is_value(self):
        expr = parse_search_query("name:OR")
        self.assertEqual(expr, FieldTerm("name", "OR"))


if __name__ == "__main__":
    unittest.main()
