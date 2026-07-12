"""Stage 1 — lee el Excel del cliente: hojas, verbatims, libro de códigos."""

from .excel import detect_sheets, parse_codebook, parse_verbatims

__all__ = ["detect_sheets", "parse_codebook", "parse_verbatims"]
