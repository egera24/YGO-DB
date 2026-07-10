"""Catalog pipeline errors."""

from __future__ import annotations


class CatalogPipelineError(Exception):
    """Base error for catalog sync."""


class ExpansionMappingError(CatalogPipelineError):
    def __init__(self, message: str, *, details: list[dict] | None = None):
        super().__init__(message)
        self.details = details or []


class PrintingCountMismatchError(CatalogPipelineError):
    def __init__(
        self,
        message: str,
        *,
        set_code: str | None = None,
        card_name: str | None = None,
        yugipedia_count: int | None = None,
        cardmarket_count: int | None = None,
    ):
        super().__init__(message)
        self.set_code = set_code
        self.card_name = card_name
        self.yugipedia_count = yugipedia_count
        self.cardmarket_count = cardmarket_count


class AmbiguousPriceOrderError(CatalogPipelineError):
    def __init__(self, message: str, *, set_code: str | None = None, card_name: str | None = None):
        super().__init__(message)
        self.set_code = set_code
        self.card_name = card_name


class CatalogDownloadError(CatalogPipelineError):
    pass
