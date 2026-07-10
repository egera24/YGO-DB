"""Lucene-style card search query parser and SQLAlchemy filter compiler."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto
from typing import TYPE_CHECKING

from sqlalchemy import ColumnElement, and_, cast, exists, func, not_, or_, select, String

from ygo_app.card_filters import (
    link_markers_contain_all,
    mechanic_filter,
    types_overlap_filter,
)
from ygo_app.models import (
    Card,
    CollectionItem,
    Printing,
    UserCardTag,
    UserFavorite,
)

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


class SearchQueryError(ValueError):
    pass


@dataclass
class SearchCompileContext:
    user_id: int | None = None
    session: Session | None = None
    format_code: str | None = None
    dialect: str = "postgresql"


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
class FieldTerm(SearchExpr):
    field: str
    text: str
    wildcard: bool = False
    case_sensitive: bool = False


@dataclass(frozen=True)
class FieldPhrase(SearchExpr):
    field: str
    text: str
    case_sensitive: bool = False


@dataclass(frozen=True)
class RangeExpr(SearchExpr):
    field: str
    op: str
    low: int | None
    high: int | None


@dataclass(frozen=True)
class EnumExpr(SearchExpr):
    field: str
    value: str
    values: tuple[str, ...] = ()


@dataclass(frozen=True)
class BoolExpr(SearchExpr):
    field: str
    value: bool


@dataclass(frozen=True)
class NotExpr(SearchExpr):
    child: SearchExpr


@dataclass(frozen=True)
class AndExpr(SearchExpr):
    children: tuple[SearchExpr, ...]


@dataclass(frozen=True)
class OrExpr(SearchExpr):
    children: tuple[SearchExpr, ...]


FIELD_ALIASES: dict[str, str] = {
    "n": "name",
    "name": "name",
    "d": "desc",
    "description": "desc",
    "desc": "desc",
    "a": "archetype",
    "archetype": "archetype",
    "summon": "summoning",
    "summoning": "summoning",
    "text": "text",
    "passcode": "passcode",
    "id": "passcode",
    "password": "passcode",
    "atk": "atk",
    "def": "def",
    "level": "level",
    "rank": "rank",
    "link": "link_rating",
    "link_rating": "link_rating",
    "scale": "pendulum_scale",
    "pendulum": "pendulum_scale",
    "pendulum_scale": "pendulum_scale",
    "category": "category",
    "type": "type",
    "mechanic": "mechanic",
    "attribute": "attribute",
    "race": "race",
    "cardtype": "cardtype",
    "marker": "marker",
    "markers": "marker",
    "set": "set",
    "set_code": "set",
    "tag": "tag",
    "owned": "owned",
    "favorite": "favorite",
    "format": "format",
    "banlist": "banlist",
    "points": "points",
}

TEXT_FIELDS = frozenset({"name", "desc", "archetype", "summoning", "text", "passcode"})
NUMERIC_FIELDS = frozenset({"atk", "def", "level", "rank", "link_rating", "pendulum_scale"})
ENUM_FIELDS = frozenset(
    {"category", "type", "mechanic", "attribute", "race", "cardtype", "marker", "set", "tag"}
)
BOOL_FIELDS = frozenset({"owned", "favorite"})
FORMAT_FIELDS = frozenset({"format", "banlist", "points"})

_TEXT_COLUMNS: dict[str, object] = {
    "name": Card.name,
    "desc": Card.desc,
    "archetype": Card.archetype,
    "summoning": Card.summoning_condition,
}

_NUMERIC_COLUMNS: dict[str, object] = {
    "atk": Card.atk,
    "def": Card.def_,
    "level": Card.level,
    "rank": Card.rank,
    "link_rating": Card.link_rating,
    "pendulum_scale": Card.pendulum_scale,
}

_DEFAULT_TEXT_COLUMNS = (Card.name, Card.desc, Card.archetype)

_TRUTHY = frozenset({"true", "yes", "1"})
_FALSY = frozenset({"false", "no", "0"})


class _Kind(Enum):
    WORD = auto()
    PHRASE = auto()
    AND = auto()
    OR = auto()
    NOT = auto()
    LPAREN = auto()
    RPAREN = auto()
    MINUS = auto()
    COLON = auto()
    EQUALS = auto()


@dataclass(frozen=True)
class _Token:
    kind: _Kind
    value: str = ""


def resolve_field(name: str) -> str | None:
    return FIELD_ALIASES.get(name.lower())


def parse_search_query(q: str) -> SearchExpr | None:
    """Parse a search string into an AST, or None if empty."""
    tokens = _tokenize(q)
    if not tokens:
        return None
    parser = _Parser(tokens)
    expr = parser.parse_or()
    if parser._peek() is not None:
        extra = parser._peek()
        raise SearchQueryError(
            f"Unexpected token: {extra.value!r}" if extra else "Unexpected token"
        )
    return expr


def compile_search_filter(
    expr: SearchExpr,
    ctx: SearchCompileContext | None = None,
) -> ColumnElement:
    return _compile(expr, ctx or SearchCompileContext())


def _extract_format_code(expr: SearchExpr) -> str | None:
    if isinstance(expr, EnumExpr) and expr.field == "format":
        return expr.value
    if isinstance(expr, (AndExpr, OrExpr)):
        for child in expr.children:
            found = _extract_format_code(child)
            if found:
                return found
    return None


def text_search_filter(
    q: str,
    ctx: SearchCompileContext | None = None,
) -> ColumnElement | None:
    """Parse q and compile to a SQLAlchemy filter, or None if q is empty."""
    base_ctx = ctx or SearchCompileContext()
    expr = parse_search_query(q)
    if expr is None:
        return None
    format_from_q = _extract_format_code(expr)
    dialect = "postgresql"
    if base_ctx.session is not None:
        dialect = base_ctx.session.get_bind().dialect.name
    compile_ctx = SearchCompileContext(
        user_id=base_ctx.user_id,
        session=base_ctx.session,
        format_code=format_from_q or base_ctx.format_code,
        dialect=dialect,
    )
    return compile_search_filter(expr, compile_ctx)


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
        if ch == ":":
            tokens.append(_Token(_Kind.COLON))
            i += 1
            continue
        if ch == "=":
            if i > 0 and q[i - 1] in "<>":
                i += 1
                continue
            tokens.append(_Token(_Kind.EQUALS))
            i += 1
            continue
        if ch == "-":
            if (i == 0 or q[i - 1].isspace()) and i + 1 < n and not q[i + 1].isspace():
                tokens.append(_Token(_Kind.MINUS))
                i += 1
                continue
        if ch in "<>":
            start = i
            i += 1
            if i < n and q[i] == "=":
                i += 1
            while i < n and q[i].isdigit():
                i += 1
            tokens.append(_Token(_Kind.WORD, q[start:i]))
            continue
        start = i
        while i < n and not q[i].isspace() and q[i] not in '()":=':
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
            field = resolve_field(tok.value)
            if field is not None and self._peek() is not None and self._peek().kind == _Kind.COLON:
                self._advance()
                return self._parse_field_expr(field)
            if self._peek() is not None and self._peek().kind == _Kind.COLON:
                self._advance()
                value_tok = self._advance()
                if value_tok is None:
                    raise SearchQueryError("Expected value after ':'")
                if value_tok.kind == _Kind.PHRASE:
                    combined = f'{tok.value}:"{value_tok.value}"'
                elif value_tok.kind == _Kind.WORD:
                    combined = f"{tok.value}:{value_tok.value}"
                else:
                    raise SearchQueryError(f"Unexpected token after ':'")
                wildcard = "*" in combined or "?" in combined
                return Term(combined, wildcard=wildcard)
            wildcard = "*" in tok.value or "?" in tok.value
            return Term(tok.value, wildcard=wildcard)
        raise SearchQueryError(f"Unexpected token in search query: {tok.value!r}")

    def _parse_field_expr(self, field: str) -> SearchExpr:
        if field in TEXT_FIELDS or field == "passcode":
            return self._parse_text_field(field)
        if field in NUMERIC_FIELDS:
            return self._parse_numeric_field(field)
        if field in BOOL_FIELDS:
            return self._parse_bool_field(field)
        if field == "points":
            return self._parse_numeric_field(field)
        if field in ENUM_FIELDS or field in FORMAT_FIELDS:
            return self._parse_enum_field(field)
        raise SearchQueryError(f"Unknown field: {field}")

    def _parse_text_field(self, field: str) -> SearchExpr:
        case_sensitive = False
        if self._match(_Kind.EQUALS):
            case_sensitive = True
        peek = self._peek()
        if peek is None:
            raise SearchQueryError(f"Expected value for {field}:")
        if peek.kind == _Kind.PHRASE:
            self._advance()
            return FieldPhrase(field, peek.value, case_sensitive=case_sensitive)
        if peek.kind == _Kind.WORD:
            self._advance()
            wildcard = "*" in peek.value or "?" in peek.value
            return FieldTerm(
                field,
                peek.value,
                wildcard=wildcard,
                case_sensitive=case_sensitive,
            )
        if peek.kind in (_Kind.OR, _Kind.AND, _Kind.NOT):
            keyword = peek.kind.name
            self._advance()
            return FieldTerm(field, keyword, case_sensitive=case_sensitive)
        raise SearchQueryError(f"Expected value for {field}:")

    def _parse_numeric_field(self, field: str) -> SearchExpr:
        peek = self._peek()
        if peek is None or peek.kind != _Kind.WORD:
            raise SearchQueryError(f"Expected numeric value for {field}:")
        raw = peek.value
        self._advance()

        if raw == "?":
            return RangeExpr(field, "null", None, None)

        for op in (">=", "<=", ">", "<"):
            if raw.startswith(op) and raw[len(op) :].isdigit():
                return RangeExpr(field, op, int(raw[len(op) :]), None)

        if ".." in raw:
            low_s, high_s = raw.split("..", 1)
            if not low_s.isdigit() or not high_s.isdigit():
                raise SearchQueryError(f"Invalid range for {field}: {raw!r}")
            return RangeExpr(field, "..", int(low_s), int(high_s))

        if raw.isdigit():
            return RangeExpr(field, "=", int(raw), None)

        raise SearchQueryError(f"Invalid numeric value for {field}: {raw!r}")

    def _parse_bool_field(self, field: str) -> SearchExpr:
        peek = self._peek()
        if peek is None or peek.kind != _Kind.WORD:
            raise SearchQueryError(f"Expected true/false for {field}:")
        raw = peek.value.lower()
        self._advance()
        if raw in _TRUTHY:
            return BoolExpr(field, True)
        if raw in _FALSY:
            return BoolExpr(field, False)
        raise SearchQueryError(f"Expected true/false for {field}: {peek.value!r}")

    def _parse_enum_field(self, field: str) -> SearchExpr:
        if field == "points":
            return self._parse_numeric_field(field)
        peek = self._peek()
        if peek is None:
            raise SearchQueryError(f"Expected value for {field}:")
        if peek.kind == _Kind.PHRASE:
            self._advance()
            return EnumExpr(field, peek.value)
        if peek.kind == _Kind.WORD:
            self._advance()
            if field == "marker" and "," in peek.value:
                values = tuple(v.strip() for v in peek.value.split(",") if v.strip())
                return EnumExpr(field, values[0] if values else peek.value, values=values)
            return EnumExpr(field, peek.value)
        raise SearchQueryError(f"Expected value for {field}:")


def _escape_like_literal(text: str) -> str:
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


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


def _text_pattern(text: str, *, wildcard: bool, case_sensitive: bool) -> tuple[str, bool]:
    if wildcard:
        pattern = f"%{_wildcard_to_like(text)}%"
    else:
        pattern = f"%{_escape_like_literal(text)}%"
    return pattern, case_sensitive


def _case_sensitive_contains(
    haystack: ColumnElement,
    needle: str,
    dialect: str,
) -> ColumnElement:
    if dialect == "sqlite":
        return func.instr(haystack, needle) > 0
    return func.strpos(haystack, needle) > 0


def _column_text_match(
    column,
    pattern: str,
    *,
    case_sensitive: bool,
    literal_text: str | None = None,
    wildcard: bool = False,
    dialect: str = "postgresql",
) -> ColumnElement:
    coalesced = func.coalesce(column, "")
    if not case_sensitive:
        return coalesced.ilike(pattern, escape="\\")
    if wildcard:
        if dialect == "sqlite":
            glob_pattern = pattern.replace("%", "*").replace("_", "?")
            return coalesced.op("GLOB")(glob_pattern)
        return coalesced.like(pattern, escape="\\")
    needle = literal_text if literal_text is not None else pattern.strip("%")
    return _case_sensitive_contains(coalesced, needle, dialect)


def _all_text_match(
    pattern: str,
    *,
    case_sensitive: bool,
    literal_text: str | None = None,
    wildcard: bool = False,
    dialect: str = "postgresql",
) -> ColumnElement:
    return or_(
        *(
            _column_text_match(
                field,
                pattern,
                case_sensitive=case_sensitive,
                literal_text=literal_text,
                wildcard=wildcard,
                dialect=dialect,
            )
            for field in _DEFAULT_TEXT_COLUMNS
        )
    )


def _false_filter() -> ColumnElement:
    return Card.id == -1


def _apply_int_range(column, min_val: int | None, max_val: int | None) -> list[ColumnElement]:
    clauses: list[ColumnElement] = []
    if min_val is not None:
        clauses.append(column >= min_val)
    if max_val is not None:
        clauses.append(column <= max_val)
    return clauses


def _compile_numeric_range(expr: RangeExpr) -> ColumnElement:
    if expr.field == "points":
        return _false_filter()

    column = _NUMERIC_COLUMNS.get(expr.field)
    if column is None:
        return _false_filter()

    if expr.op == "null":
        return column.is_(None)

    if expr.op == "=":
        return column == expr.low

    if expr.op == ">=":
        return column >= expr.low
    if expr.op == ">":
        return column > expr.low
    if expr.op == "<=":
        return column <= expr.low
    if expr.op == "<":
        return column < expr.low
    if expr.op == "..":
        return and_(*_apply_int_range(column, expr.low, expr.high))

    raise SearchQueryError(f"Unknown range operator: {expr.op}")


def _compile_passcode(expr: FieldTerm | FieldPhrase, dialect: str) -> ColumnElement:
    text = expr.text
    if isinstance(expr, FieldPhrase):
        if expr.case_sensitive:
            return _case_sensitive_contains(
                cast(Card.passcode, String), text, dialect
            )
        return cast(Card.passcode, String).ilike(
            f"%{_escape_like_literal(text)}%", escape="\\"
        )

    if expr.wildcard:
        pattern = f"%{_wildcard_to_like(text)}%"
        if expr.case_sensitive:
            if dialect == "sqlite":
                glob_pattern = pattern.replace("%", "*").replace("_", "?")
                return cast(Card.passcode, String).op("GLOB")(glob_pattern)
            return cast(Card.passcode, String).like(pattern, escape="\\")
        return cast(Card.passcode, String).ilike(pattern, escape="\\")

    if text.isdigit():
        return Card.passcode == int(text)

    pattern, case_sensitive = _text_pattern(
        text, wildcard=expr.wildcard, case_sensitive=expr.case_sensitive
    )
    if case_sensitive:
        return _case_sensitive_contains(cast(Card.passcode, String), text, dialect)
    return cast(Card.passcode, String).ilike(pattern, escape="\\")


def _compile_text_field(expr: FieldTerm | FieldPhrase, dialect: str) -> ColumnElement:
    field = expr.field
    if field == "text":
        if isinstance(expr, FieldPhrase):
            pattern, case_sensitive = _text_pattern(
                expr.text, wildcard=False, case_sensitive=expr.case_sensitive
            )
            return _all_text_match(
                pattern,
                case_sensitive=case_sensitive,
                literal_text=expr.text,
                dialect=dialect,
            )
        pattern, case_sensitive = _text_pattern(
            expr.text, wildcard=expr.wildcard, case_sensitive=expr.case_sensitive
        )
        return _all_text_match(
            pattern,
            case_sensitive=case_sensitive,
            literal_text=expr.text,
            wildcard=expr.wildcard,
            dialect=dialect,
        )

    if field == "passcode":
        return _compile_passcode(expr, dialect)

    column = _TEXT_COLUMNS.get(field)
    if column is None:
        return _false_filter()

    if isinstance(expr, FieldPhrase):
        pattern, case_sensitive = _text_pattern(
            expr.text, wildcard=False, case_sensitive=expr.case_sensitive
        )
        return _column_text_match(
            column,
            pattern,
            case_sensitive=case_sensitive,
            literal_text=expr.text,
            dialect=dialect,
        )

    pattern, case_sensitive = _text_pattern(
        expr.text, wildcard=expr.wildcard, case_sensitive=expr.case_sensitive
    )
    return _column_text_match(
        column,
        pattern,
        case_sensitive=case_sensitive,
        literal_text=expr.text,
        wildcard=expr.wildcard,
        dialect=dialect,
    )


def _compile_enum(expr: EnumExpr, ctx: SearchCompileContext) -> ColumnElement:
    field = expr.field
    value = expr.value

    if field == "category":
        return Card.category == value

    if field == "type":
        filt = types_overlap_filter([value])
        return filt if filt is not None else _false_filter()

    if field == "mechanic":
        filt = mechanic_filter(value)
        return filt if filt is not None else _false_filter()

    if field == "attribute":
        return Card.attribute.ilike(value)

    if field == "race":
        return Card.race.ilike(value)

    if field == "cardtype":
        return Card.type.ilike(f"%{value}%")

    if field == "marker":
        labels = list(expr.values) if expr.values else [value]
        clauses = link_markers_contain_all(labels)
        if not clauses:
            return _false_filter()
        return and_(*clauses)

    if field == "set":
        pattern = f"%{value}%"
        subq = (
            select(Printing.card_id)
            .where(
                Printing.card_id == Card.id,
                Printing.set_code.ilike(pattern),
            )
            .correlate(Card)
        )
        return exists(subq)

    if field == "tag":
        if ctx.user_id is None:
            return _false_filter()
        pattern = value if "%" in value else value
        subq = (
            select(UserCardTag.card_id)
            .where(
                UserCardTag.card_id == Card.id,
                UserCardTag.user_id == ctx.user_id,
                UserCardTag.tag.ilike(pattern),
            )
            .correlate(Card)
        )
        return exists(subq)

    if field == "format":
        return _compile_format_filter(value, ctx)

    if field == "banlist":
        return _compile_banlist_filter(value, ctx)

    return _false_filter()


def _compile_bool(expr: BoolExpr, ctx: SearchCompileContext) -> ColumnElement:
    positive = _compile_bool_positive(expr.field, ctx)
    return positive if expr.value else not_(positive)


def _compile_bool_positive(field: str, ctx: SearchCompileContext) -> ColumnElement:
    if ctx.user_id is None:
        return _false_filter()

    if field == "favorite":
        subq = (
            select(UserFavorite.card_id)
            .where(
                UserFavorite.card_id == Card.id,
                UserFavorite.user_id == ctx.user_id,
            )
            .correlate(Card)
        )
        return exists(subq)

    if field == "owned":
        subq = (
            select(Printing.card_id)
            .join(
                CollectionItem,
                (CollectionItem.set_code == Printing.set_code)
                & (CollectionItem.rarity_code == Printing.set_rarity_code)
                & (CollectionItem.user_id == ctx.user_id),
            )
            .where(Printing.card_id == Card.id)
            .correlate(Card)
        )
        return exists(subq)

    return _false_filter()


def _effective_format_code(ctx: SearchCompileContext, q_format: str | None = None) -> str | None:
    return q_format or ctx.format_code


def _compile_format_filter(format_code: str, ctx: SearchCompileContext) -> ColumnElement:
    if ctx.session is None:
        return _false_filter()

    from ygo_app.formats.context import resolve_format_search_context
    from ygo_app.formats.pool import format_pool_legality_exists, warn_if_legality_table_empty

    format_ctx = resolve_format_search_context(ctx.session, format_code)
    if not format_ctx:
        return _false_filter()

    clauses: list[ColumnElement] = []

    if format_ctx.rules.pool_uses_legality_table:
        warn_if_legality_table_empty(ctx.session, format_ctx.rules)
        clauses.append(format_pool_legality_exists(format_ctx.rules.code))

    if format_ctx.rules.disallow_link:
        clauses.append(or_(Card.mechanic.is_(None), Card.mechanic != "Link"))
    if format_ctx.rules.disallow_pendulum:
        clauses.append(or_(Card.mechanic.is_(None), Card.mechanic != "Pendulum"))

    if not clauses:
        return Card.id.is_not(None)
    return and_(*clauses)


def _compile_banlist_filter(status: str, ctx: SearchCompileContext) -> ColumnElement:
    if ctx.session is None:
        return _false_filter()

    format_code = _effective_format_code(ctx)
    if not format_code:
        return _false_filter()

    from ygo_app.formats.banlist import (
        db_statuses_for_effective_filters,
        partition_banlist_status_filters,
        parse_banlist_status_param,
        resolve_banlist_revision,
    )
    from ygo_app.formats.context import resolve_format_search_context
    from ygo_app.models import BanlistEntry

    format_ctx = resolve_format_search_context(ctx.session, format_code)
    if not format_ctx:
        return _false_filter()

    statuses = parse_banlist_status_param(status)
    if not statuses:
        return _false_filter()

    revision = resolve_banlist_revision(ctx.session, format_ctx.rules, None)
    if not revision:
        return _false_filter()

    restricted_statuses, include_unlimited = partition_banlist_status_filters(statuses)
    db_statuses = db_statuses_for_effective_filters(restricted_statuses, format_ctx.rules)
    conditions: list[ColumnElement] = []

    if restricted_statuses:
        if not db_statuses:
            return _false_filter()
        restricted = select(BanlistEntry.card_id).where(
            BanlistEntry.revision_id == revision.id,
            BanlistEntry.card_id.is_not(None),
            BanlistEntry.status.in_(db_statuses),
        )
        conditions.append(Card.id.in_(restricted))

    if include_unlimited:
        on_list = select(BanlistEntry.card_id).where(
            BanlistEntry.revision_id == revision.id,
            BanlistEntry.card_id.is_not(None),
        )
        conditions.append(~Card.id.in_(on_list))

    if not conditions:
        return _false_filter()
    if len(conditions) == 1:
        return conditions[0]
    return or_(*conditions)


def _compile_points(expr: RangeExpr, ctx: SearchCompileContext) -> ColumnElement:
    if ctx.session is None:
        return _false_filter()

    format_code = _effective_format_code(ctx)
    if not format_code:
        return _false_filter()

    from ygo_app.formats.context import resolve_format_search_context
    from ygo_app.models import GenesysPointEntry

    format_ctx = resolve_format_search_context(ctx.session, format_code)
    if not format_ctx or not format_ctx.rules.uses_point_list or not format_ctx.point_list:
        return _false_filter()

    points_min: int | None = None
    points_max: int | None = None

    if expr.op == "=":
        points_min = points_max = expr.low
    elif expr.op == ">=":
        points_min = expr.low
    elif expr.op == ">":
        points_min = (expr.low or 0) + 1
    elif expr.op == "<=":
        points_max = expr.low
    elif expr.op == "<":
        points_max = (expr.low or 0) - 1
    elif expr.op == "..":
        points_min, points_max = expr.low, expr.high

    point_subq = select(GenesysPointEntry.card_id).where(
        GenesysPointEntry.list_id == format_ctx.point_list.id,
        GenesysPointEntry.card_id.is_not(None),
    )
    if points_min is not None:
        point_subq = point_subq.where(GenesysPointEntry.points >= points_min)
    if points_max is not None:
        point_subq = point_subq.where(GenesysPointEntry.points <= points_max)

    if points_min is not None and points_min <= 0:
        all_listed = select(GenesysPointEntry.card_id).where(
            GenesysPointEntry.list_id == format_ctx.point_list.id
        )
        return or_(Card.id.in_(point_subq), ~Card.id.in_(all_listed))

    return Card.id.in_(point_subq)


def _compile(expr: SearchExpr, ctx: SearchCompileContext) -> ColumnElement:
    dialect = ctx.dialect
    if isinstance(expr, Phrase):
        pattern, _ = _text_pattern(expr.text, wildcard=False, case_sensitive=False)
        return _all_text_match(
            pattern, case_sensitive=False, literal_text=expr.text, dialect=dialect
        )
    if isinstance(expr, Term):
        pattern, _ = _text_pattern(expr.text, wildcard=expr.wildcard, case_sensitive=False)
        return _all_text_match(
            pattern,
            case_sensitive=False,
            literal_text=expr.text,
            wildcard=expr.wildcard,
            dialect=dialect,
        )
    if isinstance(expr, (FieldTerm, FieldPhrase)):
        return _compile_text_field(expr, dialect)
    if isinstance(expr, RangeExpr):
        if expr.field == "points":
            return _compile_points(expr, ctx)
        return _compile_numeric_range(expr)
    if isinstance(expr, EnumExpr):
        return _compile_enum(expr, ctx)
    if isinstance(expr, BoolExpr):
        return _compile_bool(expr, ctx)
    if isinstance(expr, NotExpr):
        return not_(_compile(expr.child, ctx))
    if isinstance(expr, AndExpr):
        return and_(*(_compile(child, ctx) for child in expr.children))
    if isinstance(expr, OrExpr):
        return or_(*(_compile(child, ctx) for child in expr.children))
    raise TypeError(f"Unknown search expression: {type(expr)!r}")
