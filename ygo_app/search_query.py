"""Google-style card search query parser and SQLAlchemy filter compiler."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto
from sqlalchemy import ColumnElement, and_, func, not_, or_

from ygo_app.models import Card


class SearchQueryError(ValueError):
    pass


@dataclass(frozen=True)
class SearchExpr:
    pass


@dataclass(frozen=True)
class Phrase(SearchExpr):
    text: str


@dataclass(frozen=True)
class Term(SearchExpr):
    text: str
    wildcard: bool = False


@dataclass(frozen=True)
class NotExpr(SearchExpr):
    child: SearchExpr


@dataclass(frozen=True)
class AndExpr(SearchExpr):
    children: tuple[SearchExpr, ...]


@dataclass(frozen=True)
class OrExpr(SearchExpr):
    children: tuple[SearchExpr, ...]


class _Kind(Enum):
    WORD = auto()
    PHRASE = auto()
    AND = auto()
    OR = auto()
    NOT = auto()
    LPAREN = auto()
    RPAREN = auto()
    MINUS = auto()


@dataclass(frozen=True)
class _Token:
    kind: _Kind
    value: str = ""


_SEARCHABLE_FIELDS = (Card.name, Card.desc, Card.archetype)


def parse_search_query(q: str) -> SearchExpr | None:
    """Parse a search string into an AST, or None if empty."""
    tokens = _tokenize(q)
    if not tokens:
        return None
    parser = _Parser(tokens)
    expr = parser.parse_or()
    if parser._peek() is not None:
        extra = parser._peek()
        raise SearchQueryError(f"Unexpected token: {extra.value!r}" if extra else "Unexpected token")
    return expr


def compile_search_filter(expr: SearchExpr) -> ColumnElement:
    return _compile(expr)


def text_search_filter(q: str) -> ColumnElement | None:
    """Parse q and compile to a SQLAlchemy filter, or None if q is empty."""
    expr = parse_search_query(q)
    if expr is None:
        return None
    return compile_search_filter(expr)


def _tokenize(q: str) -> list[_Token]:
    tokens: list[_Token] = []
    i = 0
    n = len(q)

    while i < n:
        ch = q[i]
        if ch.isspace():
            i += 1
            continue
        if ch == '"':
            i += 1
            parts: list[str] = []
            while i < n:
                if q[i] == "\\" and i + 1 < n:
                    parts.append(q[i + 1])
                    i += 2
                elif q[i] == '"':
                    i += 1
                    break
                else:
                    parts.append(q[i])
                    i += 1
            else:
                raise SearchQueryError("Unclosed quote in search query")
            tokens.append(_Token(_Kind.PHRASE, "".join(parts)))
            continue
        if ch == "(":
            tokens.append(_Token(_Kind.LPAREN))
            i += 1
            continue
        if ch == ")":
            tokens.append(_Token(_Kind.RPAREN))
            i += 1
            continue
        if ch == "-":
            if (i == 0 or q[i - 1].isspace()) and i + 1 < n and not q[i + 1].isspace():
                tokens.append(_Token(_Kind.MINUS))
                i += 1
                continue
        start = i
        while i < n and not q[i].isspace() and q[i] not in '()"':
            i += 1
        if i == start:
            i += 1
            continue
        word = q[start:i]
        upper = word.upper()
        if upper == "AND":
            tokens.append(_Token(_Kind.AND))
        elif upper == "OR":
            tokens.append(_Token(_Kind.OR))
        elif upper == "NOT":
            tokens.append(_Token(_Kind.NOT))
        else:
            tokens.append(_Token(_Kind.WORD, word))
    return tokens


class _Parser:
    def __init__(self, tokens: list[_Token]) -> None:
        self._tokens = tokens
        self._pos = 0

    def _peek(self) -> _Token | None:
        if self._pos >= len(self._tokens):
            return None
        return self._tokens[self._pos]

    def _advance(self) -> _Token | None:
        tok = self._peek()
        if tok is not None:
            self._pos += 1
        return tok

    def _match(self, kind: _Kind) -> bool:
        tok = self._peek()
        if tok is not None and tok.kind == kind:
            self._advance()
            return True
        return False

    def _at_primary_start(self) -> bool:
        tok = self._peek()
        if tok is None:
            return False
        return tok.kind in (
            _Kind.WORD,
            _Kind.PHRASE,
            _Kind.LPAREN,
            _Kind.NOT,
            _Kind.MINUS,
        )

    def parse_or(self) -> SearchExpr:
        left = self.parse_and()
        while self._match(_Kind.OR):
            right = self.parse_and()
            if isinstance(left, OrExpr):
                left = OrExpr((*left.children, right))
            else:
                left = OrExpr((left, right))
        return left

    def parse_and(self) -> SearchExpr:
        left = self.parse_not()
        while True:
            peek = self._peek()
            if peek is not None and peek.kind == _Kind.AND:
                self._advance()
            elif not self._at_primary_start():
                break
            right = self.parse_not()
            if isinstance(left, AndExpr):
                left = AndExpr((*left.children, right))
            else:
                left = AndExpr((left, right))
        return left

    def parse_not(self) -> SearchExpr:
        if self._match(_Kind.NOT) or self._match(_Kind.MINUS):
            return NotExpr(self.parse_not())
        return self.parse_primary()

    def parse_primary(self) -> SearchExpr:
        if self._match(_Kind.LPAREN):
            expr = self.parse_or()
            if not self._match(_Kind.RPAREN):
                raise SearchQueryError("Missing closing parenthesis")
            return expr
        tok = self._advance()
        if tok is None:
            raise SearchQueryError("Unexpected end of search query")
        if tok.kind == _Kind.PHRASE:
            return Phrase(tok.value)
        if tok.kind == _Kind.WORD:
            wildcard = "*" in tok.value or "?" in tok.value
            return Term(tok.value, wildcard=wildcard)
        raise SearchQueryError(f"Unexpected token in search query: {tok.value!r}")


def _escape_like_literal(text: str) -> str:
    return (
        text.replace("\\", "\\\\")
        .replace("%", "\\%")
        .replace("_", "\\_")
    )


def _wildcard_to_like(pattern: str) -> str:
    out: list[str] = []
    i = 0
    n = len(pattern)
    while i < n:
        ch = pattern[i]
        if ch == "*":
            out.append("%")
            i += 1
        elif ch == "?":
            out.append("_")
            i += 1
        else:
            start = i
            while i < n and pattern[i] not in "*?":
                i += 1
            out.append(_escape_like_literal(pattern[start:i]))
    return "".join(out)


def _field_match(pattern: str) -> ColumnElement:
    # coalesce avoids NULL ilike in OR/NOT (e.g. missing archetype on NOT queries)
    return or_(
        *(
            func.coalesce(field, "").ilike(pattern, escape="\\")
            for field in _SEARCHABLE_FIELDS
        )
    )


def _compile(expr: SearchExpr) -> ColumnElement:
    if isinstance(expr, Phrase):
        pattern = f"%{_escape_like_literal(expr.text)}%"
        return _field_match(pattern)
    if isinstance(expr, Term):
        if expr.wildcard:
            pattern = f"%{_wildcard_to_like(expr.text)}%"
        else:
            pattern = f"%{_escape_like_literal(expr.text)}%"
        return _field_match(pattern)
    if isinstance(expr, NotExpr):
        return not_(_compile(expr.child))
    if isinstance(expr, AndExpr):
        return and_(*(_compile(child) for child in expr.children))
    if isinstance(expr, OrExpr):
        return or_(*(_compile(child) for child in expr.children))
    raise TypeError(f"Unknown search expression: {type(expr)!r}")
